import { test } from "node:test";
import assert from "node:assert/strict";
import { createApp } from "../../server/app.js";
import { getDb } from "../../db/index.js";
import {
  validateComplaint,
  validateImage,
  csvCell,
} from "../../server/validation.js";
import { analyze, hotspots, metrics } from "../../server/analysis.js";
const session = {
  id: "a".repeat(64),
  csrf_token: "b".repeat(64),
  expires_at: "2099-01-01",
};
const complaint = {
  complaint_id: "CMP-TEST",
  title: "Dangerous pothole at school",
  description: "A deep pothole near the school has injured people for weeks.",
  category: "Road Damage",
  status: "Submitted",
  priority_level: "Critical",
  priority_score: 80,
  address: "Main Road",
  latitude: 0,
  longitude: 0,
  created_at: "2026-11-01 00:00:00",
  updated_at: "2026-11-01 00:00:00",
  resolved_at: null,
};
function fixture(reads: unknown[][]) {
  const writes: { action: string; table: unknown; data: unknown }[] = [];
  const chain = () => {
    const q: Record<string, unknown> = {};
    for (const key of ["from", "where", "orderBy", "leftJoin", "for"])
      q[key] = () => q;
    q.then = (resolve: (v: unknown) => unknown) =>
      Promise.resolve(reads.shift() ?? []).then(resolve);
    return q;
  };
  const database = {
    select: () => chain(),
    insert: (table: unknown) => ({
      values: (data: unknown) => {
        writes.push({ action: "insert", table, data });
        return {
          then: (resolve: (v: unknown) => unknown) =>
            Promise.resolve([]).then(resolve),
          onConflictDoNothing: async () => {},
        };
      },
    }),
    update: (table: unknown) => ({
      set: (data: unknown) => ({
        where: async () => {
          writes.push({ action: "update", table, data });
        },
      }),
    }),
    transaction: async (cb: (tx: unknown) => unknown) => cb(database),
  };
  return {
    app: createApp(database as unknown as ReturnType<typeof getDb>),
    writes,
  };
}
function request(path: string, form?: Record<string, string>, csrf = true) {
  const headers: Record<string, string> = {
    cookie: `urbanfix_session=${session.id}`,
  };
  if (path.startsWith("/admin"))
    headers.authorization =
      "Basic " + Buffer.from("admin:test-password").toString("base64");
  const body = form
    ? new URLSearchParams({
        ...form,
        ...(csrf ? { csrf_token: session.csrf_token } : {}),
      })
    : undefined;
  return new Request("https://example.test" + path, {
    method: form ? "POST" : "GET",
    headers,
    body,
  });
}
process.env.CIVICAI_ADMIN_AUTH_MODE = "password";
process.env.CIVICAI_ADMIN_PASSWORD = "test-password";
test("admin denies unauthenticated requests before querying data", async () => {
  const f = fixture([]);
  const res = await f.app(new Request("https://example.test/admin/"));
  assert.equal(res.status, 401);
  assert.match(res.headers.get("www-authenticate") ?? "", /Basic/);
  assert.equal(f.writes.length, 0);
});
test("CSRF failure rejects submission without writes", async () => {
  const f = fixture([[session]]);
  const res = await f.app(
    request("/submit/", { title: complaint.title }, false),
  );
  assert.equal(res.status, 403);
  assert.equal(f.writes.length, 0);
});
test("valid submission writes complaint, history, notification and session ownership atomically", async () => {
  const f = fixture([[session], []]);
  const res = await f.app(
    request("/submit/", {
      title: complaint.title,
      description: complaint.description,
      category: complaint.category,
    }),
  );
  assert.equal(res.status, 303);
  assert.match(res.headers.get("location") ?? "", /^\/submit\/success\/CMP-/);
  assert.equal(f.writes.length, 4);
  const stored = f.writes[0].data as Record<string, unknown>;
  assert.equal(stored.category, "Road Damage");
  assert.equal(stored.ai_needs_review, 0);
});
test("invalid submission returns field errors and no database writes", async () => {
  const f = fixture([[session]]);
  const res = await f.app(
    request("/submit/", {
      title: "short",
      description: "short",
      category: "Fake",
    }),
  );
  assert.equal(res.status, 422);
  assert.equal(f.writes.length, 0);
});
test("status change writes history and citizen notification", async () => {
  const f = fixture([[session], [complaint], [complaint]]);
  const res = await f.app(
    request("/admin/complaint/CMP-TEST/update", {
      new_status: "Resolved",
      resolution_message: "Road repaired.",
    }),
  );
  assert.equal(res.status, 303);
  assert.equal(f.writes.length, 3);
  assert.equal(
    (f.writes[0].data as Record<string, unknown>).status,
    "Resolved",
  );
  assert.equal(
    (f.writes[1].data as Record<string, unknown>).old_status,
    "Submitted",
  );
});
test("invalid resolution image prevents status changes", async () => {
  const f = fixture([[session], [complaint]]);
  const form = new FormData();
  form.set("csrf_token", session.csrf_token);
  form.set("new_status", "Resolved");
  form.set(
    "resolution_image",
    new File(["html content"], "fake.png", { type: "image/png" }),
  );
  const res = await f.app(
    new Request("https://example.test/admin/complaint/CMP-TEST/update", {
      method: "POST",
      headers: {
        cookie: `urbanfix_session=${session.id}`,
        authorization:
          "Basic " + Buffer.from("admin:test-password").toString("base64"),
      },
      body: form,
    }),
  );
  assert.equal(res.status, 422);
  assert.equal(f.writes.length, 0);
});
test("notifications cannot be marked read for another session complaint", async () => {
  const f = fixture([[session], [{ complaint_id: "CMP-OWNED" }]]);
  const res = await f.app(
    request("/submit/notifications/read-all", { complaint_id: "CMP-OTHER" }),
  );
  assert.equal(res.status, 403);
  assert.equal(f.writes.length, 0);
});
test("track returns stored history and associates found complaint with session", async () => {
  const f = fixture([
    [session],
    [complaint],
    [{ new_status: "Submitted", changed_at: complaint.created_at }],
    [],
  ]);
  const res = await f.app(request("/submit/track?complaint_id=CMP-TEST"));
  assert.equal(res.status, 200);
  assert.match(await res.text(), /CMP-TEST/);
  assert.equal(f.writes.length, 1);
});
test("CSV export uses active filters and neutralizes formulas", async () => {
  const f = fixture([
    [session],
    [
      { ...complaint, title: '=HYPERLINK("bad")' },
      { ...complaint, category: "Sewage", title: "excluded" },
    ],
  ]);
  const res = await f.app(
    request("/admin/reports/export.csv?category=Road%20Damage"),
  );
  assert.equal(res.status, 200);
  assert.match(res.headers.get("content-type") ?? "", /text\/csv/);
  const body = await res.text();
  assert.match(body, /'=HYPERLINK/);
  assert.ok(!body.includes("excluded"));
});
test("rejects nonfinite and partial coordinates", () => {
  for (const coords of [
    { latitude: "NaN", longitude: "77" },
    { latitude: "12", longitude: "" },
    { latitude: "91", longitude: "77" },
  ]) {
    const form = new FormData();
    for (const [k, v] of Object.entries({
      title: complaint.title,
      description: complaint.description,
      category: complaint.category,
      ...coords,
    }))
      form.set(k, v);
    assert.ok(validateComplaint(form).errors.length);
  }
});
test("image validation accepts signatures and rejects disguised HTML", async () => {
  assert.equal(
    (
      await validateImage(
        new File(
          [new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])],
          "image.png",
        ),
      )
    )?.extension,
    "png",
  );
  await assert.rejects(() =>
    validateImage(new File(["<script>"], "image.png")),
  );
});
test("classification, urgency, duplicate and hotspot analysis handle real data and zero coordinates", () => {
  const result = analyze(complaint, [complaint]);
  assert.equal(result.ai_category, "Road Damage");
  assert.equal(result.priority_level, "High");
  assert.equal(result.priority_score, 70);
  assert.equal(result.duplicate_matches.length, 1);
  const rows = [
    complaint,
    { ...complaint, complaint_id: "CMP-2", latitude: 0.001 },
    { ...complaint, complaint_id: "CMP-3", longitude: 0.001 },
  ];
  assert.equal(hotspots(rows).length, 1);
  assert.equal(hotspots(rows)[0].count, 3);
  assert.equal(metrics([]).resolution_rate, 0);
  assert.equal(metrics(rows).critical, 3);
  assert.equal(csvCell("=SUM(A1)"), '"\'=SUM(A1)"');
});

test('missing admin password locks administration while citizen pages remain available', async () => {
  const original = process.env.CIVICAI_ADMIN_PASSWORD;
  delete process.env.CIVICAI_ADMIN_PASSWORD;
  try {
    const admin = fixture([]);
    const locked = await admin.app(new Request('https://example.test/admin/'));
    assert.equal(locked.status, 503);
    assert.match(await locked.text(), /not configured/);
    assert.equal(admin.writes.length, 0);
    const citizen = fixture([[session]]);
    const page = await citizen.app(request('/submit/'));
    assert.equal(page.status, 200);
  } finally {
    if (original === undefined) delete process.env.CIVICAI_ADMIN_PASSWORD;
    else process.env.CIVICAI_ADMIN_PASSWORD = original;
  }
});
