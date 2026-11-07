import {
  randomBytes,
  randomUUID,
  timingSafeEqual,
  createHash,
} from "node:crypto";
import { eq, and, gt, inArray, desc, getTableColumns } from "drizzle-orm";
import { getDb } from "../db/index.js";
import * as tables from "../db/schema.js";
import { getStore } from "@netlify/blobs";
import { render } from "./render.js";
import {
  categories,
  statuses,
  priorityLevels,
  categoryDepartment,
} from "./settings.js";
import {
  analyze,
  brief,
  hotspots,
  insights,
  metrics,
  type Complaint,
} from "./analysis.js";
import {
  field,
  validateComplaint,
  validateImage,
  HttpError,
  csvCell,
} from "./validation.js";
const {
  complaints,
  departments,
  officers,
  statusHistory,
  actionNotes,
  duplicateLinks,
  notifications,
  sessions,
  trackedComplaints,
} = tables;
const token = () => randomBytes(32).toString("hex");
const digest = (s: string) => createHash("sha256").update(s).digest();
const equal = (a: string, b: string) => timingSafeEqual(digest(a), digest(b));
const env = (key: string) => process.env[key];
function adminAuth(req: Request) {
  const mode = env("CIVICAI_ADMIN_AUTH_MODE") || "password";
  if (mode === "open") return;
  if (mode !== "password")
    throw new HttpError(503, "Administration is disabled.");
  const password = env("CIVICAI_ADMIN_PASSWORD");
  if (!password)
    throw new HttpError(503, "Administrator access is not configured.");
  const header = req.headers.get("authorization") || "";
  let supplied = "";
  if (header.startsWith("Basic ")) {
    const decoded = Buffer.from(header.slice(6), "base64").toString();
    if (decoded.includes(":")) supplied = decoded.slice(decoded.indexOf(":") + 1);
  }
  if (!header.startsWith("Basic ") || !equal(supplied, password))
    throw new HttpError(401, "Administrator authentication required.");
}
function rowsAsComplaints(rows: unknown[]): Complaint[] {
  return rows as Complaint[];
}
async function allComplaints(db: ReturnType<typeof getDb>) {
  return rowsAsComplaints(
    await db
      .select({
        ...getTableColumns(complaints),
        department_name: departments.department_name,
        officer_name: officers.officer_name,
      })
      .from(complaints)
      .leftJoin(departments, eq(complaints.department_id, departments.id))
      .leftJoin(officers, eq(complaints.assigned_officer, officers.id))
      .orderBy(desc(complaints.created_at)),
  );
}
function filterRows(rows: Complaint[], params: URLSearchParams) {
  return rows.filter(
    (c) =>
      ![
        "category",
        "status",
        "priority",
        "department_id",
        "start_date",
        "end_date",
        "q",
      ].some((key) => {
        const value = params.get(key)?.trim();
        if (!value) return false;
        if (key === "q")
          return !`${c.complaint_id} ${c.title} ${c.address ?? ""}`
            .toLowerCase()
            .includes(value.toLowerCase());
        if (key === "start_date") return c.created_at.slice(0, 10) < value;
        if (key === "end_date") return c.created_at.slice(0, 10) > value;
        return (
          String(c[key === "priority" ? "priority_level" : key] ?? "") !== value
        );
      }),
  );
}
export function createApp(database?: ReturnType<typeof getDb>) {
  return async function app(req: Request): Promise<Response> {
    const url = new URL(req.url),
      path = url.pathname.replace(/\/$/, "") || "/";
    const headers = new Headers({
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    });
    const response = (
      body: string,
      status = 200,
      type = "text/html; charset=utf-8",
    ) => {
      headers.set("Content-Type", type);
      return new Response(body, { status, headers });
    };
    const redirect = (location: string) => {
      headers.set("Location", location);
      return new Response(null, { status: 303, headers });
    };
    try {
      if (path.startsWith("/admin")) adminAuth(req);
      if (!["GET", "POST", "HEAD"].includes(req.method))
        throw new HttpError(405, "Method not allowed.");
      if (path.startsWith("/uploads/")) {
        if (req.method !== "GET" && req.method !== "HEAD")
          throw new HttpError(405, "Method not allowed.");
        const name = path.slice(9);
        if (!/^[a-f0-9-]+\.(png|jpg|gif|webp)$/.test(name))
          throw new HttpError(404, "Image not found.");
        const data = await getStore({
          name: "complaint-images",
          consistency: "strong",
        }).get(name, { type: "arrayBuffer" });
        if (!data) throw new HttpError(404, "Image not found.");
        return new Response(req.method === "HEAD" ? null : data, {
          headers: {
            "Content-Type": `image/${name.endsWith(".jpg") ? "jpeg" : name.split(".").pop()}`,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "public, max-age=86400",
          },
        });
      }
      const db = database ?? getDb();
      const cookie = req.headers
        .get("cookie")
        ?.match(/(?:^|;\s*)urbanfix_session=([a-f0-9]{64})(?:;|$)/)?.[1];
      let session = cookie
        ? (
            await db
              .select()
              .from(sessions)
              .where(
                and(
                  eq(sessions.id, cookie),
                  gt(sessions.expires_at, new Date().toISOString()),
                ),
              )
          )[0]
        : undefined;
      if (!session) {
        session = (
          await db
            .insert(sessions)
            .values({
              id: token(),
              csrf_token: token(),
              expires_at: new Date(Date.now() + 30 * 86400000).toISOString(),
            })
            .returning()
        )[0];
        headers.append(
          "Set-Cookie",
          `urbanfix_session=${session.id}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000${url.protocol === "https:" ? "; Secure" : ""}`,
        );
      }
      const sid = session.id;
      let form = new FormData();
      if (req.method === "POST") {
        if (Number(req.headers.get("content-length") || 0) > 5 * 1024 * 1024)
          throw new HttpError(413, "Request is too large.");
        const origin = req.headers.get("origin");
        if (origin && origin !== url.origin)
          throw new HttpError(403, "Invalid request origin.");
        try {
          form = await req.formData();
        } catch {
          throw new HttpError(400, "Invalid form data.");
        }
        if (!equal(field(form, "csrf_token"), session.csrf_token))
          throw new HttpError(
            403,
            "Your session token is invalid. Reload the page and try again.",
          );
      }
      const tracked = async () =>
        (
          await db
            .select()
            .from(trackedComplaints)
            .where(eq(trackedComplaints.session_id, sid))
        ).map((r) => r.complaint_id);
      const track = async (cid: string) => {
        await db
          .insert(trackedComplaints)
          .values({ session_id: sid, complaint_id: cid })
          .onConflictDoNothing();
      };
      const view = (
        template: string,
        endpoint: string,
        data: Record<string, unknown> = {},
        status = 200,
      ) =>
        response(
          render(template, {
            request: { endpoint },
            csrf_token: () => session!.csrf_token,
            categories,
            statuses,
            priority_levels: priorityLevels,
            config: { AI_HOTSPOT_MIN_COMPLAINTS: 3 },
            ...data,
          }),
          status,
        );
      const upload = async (
        image: Awaited<ReturnType<typeof validateImage>>,
      ) => {
        if (!image) return null;
        const name = `${randomUUID()}.${image.extension}`;
        await getStore({ name: "complaint-images", consistency: "strong" }).set(
          name,
          image.bytes,
        );
        return name;
      };
      if (path === "/") {
        if (req.method === "POST")
          throw new HttpError(405, "Method not allowed.");
        const stats = metrics(await allComplaints(db));
        return view("home.html", "index", {
          stats: { ...stats, resolved: stats.resolved + stats.closed },
        });
      }
      if (path === "/submit") {
        if (req.method !== "POST")
          return view("submit/form.html", "submit.complaint_form", {
            errors: [],
            form_data: {},
          });
        const { input, errors } = validateComplaint(form);
        let image = null;
        try {
          image = await validateImage(form.get("image"));
        } catch (e) {
          if (e instanceof HttpError) errors.push(e.message);
          else throw e;
        }
        if (errors.length)
          return view(
            "submit/form.html",
            "submit.complaint_form",
            { errors, form_data: Object.fromEntries(form) },
            422,
          );
        const analysis = analyze(input, await allComplaints(db));
        const { duplicate_matches, suggestions, ...stored } = analysis;
        const cid = `CMP-${new Date().toISOString().slice(0, 10).replaceAll("-", "")}-${randomBytes(8).toString("hex").toUpperCase()}`;
        const image_path = await upload(image);
        try {
          await db.transaction(async (tx) => {
            await tx
              .insert(complaints)
              .values({ complaint_id: cid, ...input, ...stored, image_path });
            await tx
              .insert(statusHistory)
              .values({
                complaint_id: cid,
                new_status: "Submitted",
                action_note: "Complaint submitted by citizen.",
              });
            await tx
              .insert(notifications)
              .values({
                complaint_id: cid,
                title: "Complaint Registered",
                message: `Your complaint '${input.title}' (${cid}) has been recorded.`,
              });
            await tx
              .insert(trackedComplaints)
              .values({ session_id: sid, complaint_id: cid });
            if (duplicate_matches.length)
              await tx
                .insert(duplicateLinks)
                .values(
                  duplicate_matches.map((d) => ({ complaint_id: cid, ...d })),
                );
          });
        } catch (error) {
          if (image_path) await getStore("complaint-images").delete(image_path);
          throw error;
        }
        return redirect(`/submit/success/${cid}`);
      }
      if (path === "/submit/track") {
        const cid =
          req.method === "POST"
            ? field(form, "complaint_id")
            : url.searchParams.get("complaint_id")?.trim();
        if (!cid)
          return view(
            "track.html",
            "submit.track",
            {
              complaint: null,
              history: [],
              notifications: [],
              error_message:
                req.method === "POST" ? "Enter a complaint ID." : null,
            },
            req.method === "POST" ? 400 : 200,
          );
        const complaint = (
          await db
            .select()
            .from(complaints)
            .where(eq(complaints.complaint_id, cid))
        )[0];
        if (!complaint)
          return view(
            "track.html",
            "submit.track",
            {
              complaint: null,
              history: [],
              notifications: [],
              error_message: `Complaint ID ${cid} not found.`,
            },
            404,
          );
        await track(cid);
        const history = await db
          .select()
          .from(statusHistory)
          .where(eq(statusHistory.complaint_id, cid))
          .orderBy(statusHistory.changed_at);
        return view("track.html", "submit.track", {
          complaint,
          history,
          notifications: await db
            .select()
            .from(notifications)
            .where(eq(notifications.complaint_id, cid))
            .orderBy(desc(notifications.created_at)),
          error_message: null,
        });
      }
      if (path.startsWith("/submit/success/")) {
        const cid = path.slice("/submit/success/".length);
        const complaint = (
          await db
            .select()
            .from(complaints)
            .where(eq(complaints.complaint_id, cid))
        )[0];
        if (!complaint) throw new HttpError(404, "Complaint not found.");
        return view("submit/success.html", "submit.success", {
          complaint,
          complaint_id: cid,
        });
      }
      if (path.startsWith("/submit/notifications")) {
        let ids = await tracked();
        const selected =
          url.searchParams.get("complaint_id") || field(form, "complaint_id");
        if (selected) ids = ids.filter((id) => id === selected);
        if (req.method === "POST") {
          if (!ids.length)
            throw new HttpError(403, "No authorized complaints.");
          const match = path.match(/^\/submit\/notifications\/(\d+)\/read$/);
          if (path !== "/submit/notifications/read-all" && !match)
            throw new HttpError(404, "Page not found.");
          const condition = and(
            inArray(notifications.complaint_id, ids),
            ...(match ? [eq(notifications.id, Number(match[1]))] : []),
          );
          await db.update(notifications).set({ is_read: 1 }).where(condition);
          return redirect("/submit/notifications");
        }
        if (path !== "/submit/notifications")
          throw new HttpError(404, "Page not found.");
        const items = ids.length
          ? await db
              .select()
              .from(notifications)
              .where(inArray(notifications.complaint_id, ids))
              .orderBy(desc(notifications.created_at))
          : [];
        return view("submit/notifications.html", "submit.notifications_view", {
          notifications: items,
          unread_count: items.filter((n) => !n.is_read).length,
          active_cids: ids,
          searched_cid: selected,
        });
      }
      if (path === "/admin/brief/generate" && req.method === "POST")
        return redirect("/admin/brief");
      const detail = path.match(
        /^\/admin\/complaint\/([^/]+)(?:\/(update|add_note))?$/,
      );
      if (detail) {
        const cid = decodeURIComponent(detail[1]);
        const complaint = (
          await db
            .select()
            .from(complaints)
            .where(eq(complaints.complaint_id, cid))
        )[0];
        if (!complaint) throw new HttpError(404, "Complaint not found.");
        if (detail[2]) {
          if (req.method !== "POST")
            throw new HttpError(405, "Method not allowed.");
          if (detail[2] === "add_note") {
            const note = field(form, "note");
            if (!note || note.length > 1000)
              throw new HttpError(
                422,
                "Note must be between 1 and 1000 characters.",
              );
            await db.insert(actionNotes).values({ complaint_id: cid, note });
            return redirect(`/admin/complaint/${cid}`);
          }
          const newStatus = field(form, "new_status");
          if (newStatus && !statuses.includes(newStatus))
            throw new HttpError(422, "Invalid status.");
          const patch: Partial<typeof complaints.$inferInsert> = {
            updated_at: new Date().toISOString(),
          };
          if (newStatus) {
            patch.status = newStatus;
            patch.resolved_at = ["Resolved", "Closed"].includes(newStatus)
              ? complaint.resolved_at || new Date().toISOString()
              : null;
          }
          const assign = form.has("department_id") || form.has("officer_id");
          if (assign) {
            const d = field(form, "department_id"),
              o = field(form, "officer_id");
            const department_id = d && d !== "0" ? Number(d) : null,
              officer_id = o && o !== "0" ? Number(o) : null;
            if (
              department_id !== null &&
              (!Number.isSafeInteger(department_id) ||
                !(
                  await db
                    .select()
                    .from(departments)
                    .where(eq(departments.id, department_id))
                ).length)
            )
              throw new HttpError(422, "Invalid department.");
            if (officer_id !== null) {
              if (!Number.isSafeInteger(officer_id))
                throw new HttpError(422, "Invalid officer.");
              const officer = (
                await db
                  .select()
                  .from(officers)
                  .where(eq(officers.id, officer_id))
              )[0];
              if (
                !officer ||
                !department_id ||
                officer.department_id !== department_id
              )
                throw new HttpError(
                  422,
                  "Officer must belong to the selected department.",
                );
            }
            patch.department_id = department_id;
            patch.assigned_officer = officer_id;
          }
          const resolution = field(form, "resolution_message");
          if (
            resolution.length > 2000 ||
            field(form, "action_note").length > 1000
          )
            throw new HttpError(422, "Notes are too long.");
          if (resolution) patch.resolution_message = resolution;
          const image = await validateImage(form.get("resolution_image"));
          const imagePath = await upload(image);
          if (imagePath) patch.resolution_image_path = imagePath;
          try {
            await db.transaction(async (tx) => {
              // Lock the row so concurrent updates append history for the actual previous status.
              const [current] = await tx
                .select()
                .from(complaints)
                .where(eq(complaints.complaint_id, cid))
                .for("update");
              await tx
                .update(complaints)
                .set(patch)
                .where(eq(complaints.complaint_id, cid));
              if (newStatus && newStatus !== current.status) {
                await tx
                  .insert(statusHistory)
                  .values({
                    complaint_id: cid,
                    old_status: current.status,
                    new_status: newStatus,
                    action_note: field(form, "action_note") || null,
                  });
                await tx
                  .insert(notifications)
                  .values({
                    complaint_id: cid,
                    title: "Status Updated",
                    message: `Your complaint is now ${newStatus}.${resolution ? " " + resolution : ""}`,
                  });
              }
              if (assign)
                await tx
                  .insert(notifications)
                  .values({
                    complaint_id: cid,
                    title: "Assignment Updated",
                    message:
                      "The department or officer assignment for your complaint has changed.",
                  });
            });
          } catch (error) {
            if (imagePath) await getStore("complaint-images").delete(imagePath);
            throw error;
          }
          return redirect(`/admin/complaint/${cid}`);
        }
        if (req.method === "POST")
          throw new HttpError(405, "Method not allowed.");
        const depts = await db.select().from(departments),
          all_officers = await db.select().from(officers);
        const analysis = analyze({ ...complaint }, []);
        return view("admin/detail.html", "admin.complaint_detail", {
          complaint,
          department: depts.find((d) => d.id === complaint.department_id),
          officer: all_officers.find(
            (o) => o.id === complaint.assigned_officer,
          ),
          departments: depts,
          all_officers,
          status_history: await db
            .select()
            .from(statusHistory)
            .where(eq(statusHistory.complaint_id, cid))
            .orderBy(statusHistory.changed_at),
          action_notes: await db
            .select()
            .from(actionNotes)
            .where(eq(actionNotes.complaint_id, cid))
            .orderBy(actionNotes.created_at),
          duplicate_links: await db
            .select()
            .from(duplicateLinks)
            .where(eq(duplicateLinks.complaint_id, cid)),
          dept_recommendation: {
            recommended_department:
              categoryDepartment[complaint.ai_category || complaint.category],
            rationale: "Recommended from complaint category.",
          },
          clarity_feedback: { suggestions: analysis.suggestions },
        });
      }
      if (req.method === "POST")
        throw new HttpError(405, "Method not allowed.");
      if (path.startsWith("/admin")) {
        const rows = await allComplaints(db);
        const stats = metrics(rows);
        if (path === "/admin") {
          const filtered = filterRows(rows, url.searchParams);
          const sort = url.searchParams.get("sort") || "submitted",
            order = url.searchParams.get("order") === "asc" ? "asc" : "desc";
          const keys: Record<string, string> = {
            complaint_id: "complaint_id",
            title: "title",
            category: "category",
            address: "address",
            status: "status",
            priority: "priority_score",
            submitted: "created_at",
          };
          const key = keys[sort] || "created_at";
          filtered.sort(
            (a, b) =>
              (typeof a[key] === "number"
                ? Number(a[key]) - Number(b[key])
                : String(a[key] ?? "").localeCompare(String(b[key] ?? ""))) *
              (order === "asc" ? 1 : -1),
          );
          const page_size = 100,
            total_pages = Math.max(1, Math.ceil(filtered.length / page_size)),
            page = Math.min(
              total_pages,
              Math.max(1, parseInt(url.searchParams.get("page") || "1") || 1),
            );
          return view("admin/dashboard.html", "admin.dashboard", {
            complaints: filtered.slice(
              (page - 1) * page_size,
              page * page_size,
            ),
            stats,
            page,
            total_pages,
            total_matching: filtered.length,
            page_size,
            active_q: url.searchParams.get("q") || "",
            active_category: url.searchParams.get("category") || "",
            active_status: url.searchParams.get("status") || "",
            active_priority: url.searchParams.get("priority") || "",
            active_sort: sort,
            active_order: order,
          });
        }
        if (path === "/admin/map" || path === "/admin/hotspots") {
          const geo = rows.filter(
              (c) => c.latitude !== null && c.longitude !== null,
            ),
            clusters = hotspots(geo);
          return view(
            path === "/admin/map" ? "admin/map.html" : "admin/hotspots.html",
            path === "/admin/map" ? "admin.map_view" : "admin.hotspots",
            {
              complaints: geo,
              complaints_json: geo,
              hotspots: clusters,
              hotspots_json: clusters,
              total_geo: geo.length,
            },
          );
        }
        if (path === "/admin/brief")
          return view("admin/brief.html", "admin.action_brief", {
            brief: brief(rows),
          });
        if (path === "/admin/analytics")
          return view("admin/analytics.html", "admin.analytics_view", {
            metrics: stats,
            insights: insights(rows),
            hotspots: hotspots(rows),
          });
        if (path === "/admin/reports" || path === "/admin/reports/export.csv") {
          const filtered = filterRows(rows, url.searchParams);
          if (path.endsWith(".csv")) {
            headers.set(
              "Content-Disposition",
              'attachment; filename="urbanfix_complaints.csv"',
            );
            const keys = [
              "complaint_id",
              "title",
              "category",
              "status",
              "priority_level",
              "priority_score",
              "address",
              "department_name",
              "officer_name",
              "created_at",
              "resolved_at",
              "resolution_message",
            ];
            return response(
              [keys, ...filtered.map((c) => keys.map((k) => c[k]))]
                .map((row) => row.map(csvCell).join(","))
                .join("\r\n"),
              200,
              "text/csv; charset=utf-8",
            );
          }
          return view("admin/reports.html", "admin.reports_view", {
            complaints: filtered,
            total_count: filtered.length,
            resolved_count: filtered.filter((c) =>
              ["Resolved", "Closed"].includes(c.status),
            ).length,
            critical_count: filtered.filter(
              (c) => c.priority_level === "Critical",
            ).length,
            departments: await db.select().from(departments),
            active_category: url.searchParams.get("category") || "",
            active_status: url.searchParams.get("status") || "",
            active_priority: url.searchParams.get("priority") || "",
            active_dept: Number(url.searchParams.get("department_id")) || null,
            active_start: url.searchParams.get("start_date") || "",
            active_end: url.searchParams.get("end_date") || "",
          });
        }
      }
      throw new HttpError(404, "Page not found.");
    } catch (error) {
      if (error instanceof HttpError) {
        if (error.status === 401)
          headers.set("WWW-Authenticate", 'Basic realm="URBANFIX Admin"');
        return response(
          error.message,
          error.status,
          "text/plain; charset=utf-8",
        );
      }
      console.error(
        "Request failed",
        error instanceof Error ? error.name : "Unknown error",
      );
      return response(
        "The service is temporarily unavailable. Please try again.",
        503,
        "text/plain; charset=utf-8",
      );
    }
  };
}
export default createApp();
