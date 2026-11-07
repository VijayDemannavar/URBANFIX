import nunjucks from "nunjucks";
import path from "node:path";
nunjucks.installJinjaCompat();
export const views = new nunjucks.Environment(
  new nunjucks.FileSystemLoader(path.join(process.cwd(), "templates")),
  { autoescape: true },
);
views.addFilter(
  "tojson",
  (value) =>
    new nunjucks.runtime.SafeString(
      JSON.stringify(value ?? null)
        .replace(/</g, "\\u003c")
        .replace(/>/g, "\\u003e")
        .replace(/&/g, "\\u0026"),
    ),
);
views.addFilter("format", (format: string, value: number) =>
  Number(value ?? 0).toFixed(Number(format.match(/\.(\d+)/)?.[1] ?? 0)),
);

export function parseToDate(val: unknown): Date | null {
  if (val === null || val === undefined) return null;
  if (val instanceof Date) return isNaN(val.getTime()) ? null : val;
  if (typeof val === "number") {
    const d = new Date(val);
    return isNaN(d.getTime()) ? null : d;
  }
  const s = String(val).trim();
  if (
    !s ||
    s.toLowerCase() === "none" ||
    s.toLowerCase() === "null" ||
    s.toLowerCase() === "undefined" ||
    s === "-"
  ) {
    return null;
  }

  // Handle Date-Only values: YYYY-MM-DD
  const dateOnlyMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (dateOnlyMatch) {
    const y = Number(dateOnlyMatch[1]);
    const m = Number(dateOnlyMatch[2]);
    const d = Number(dateOnlyMatch[3]);
    if (m < 1 || m > 12 || d < 1 || d > 31) return null;
    const dateObj = new Date(Date.UTC(y, m - 1, d, 12, 0, 0));
    return isNaN(dateObj.getTime()) ? null : dateObj;
  }

  let iso = s;
  // Normalize space separator between date and time to 'T'
  if (/^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}/.test(iso)) {
    iso = iso.replace(/\s+/, "T");
  }

  // Check if timezone is already present (Z/z or numeric offset)
  const hasTimezone = /[Zz]$|[+-]\d{2}(?::?\d{2})?$/.test(iso);
  if (!hasTimezone) {
    // If it's a date-time string without timezone (e.g. SQLite "2026-11-06 18:30:00"),
    // interpret as UTC by appending 'Z'
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(iso)) {
      iso += "Z";
    }
  }

  const d = new Date(iso);
  return isNaN(d.getTime()) ? null : d;
}

export function formatDate(val: unknown, def = "-"): string {
  const d = parseToDate(val);
  if (!d) return def;
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).formatToParts(d);
  const day = parts.find((p) => p.type === "day")?.value ?? "";
  const month = parts.find((p) => p.type === "month")?.value ?? "";
  const year = parts.find((p) => p.type === "year")?.value ?? "";
  return `${day} ${month} ${year}`;
}

export function formatTime(val: unknown, def = "-"): string {
  const d = parseToDate(val);
  if (!d) return def;
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  }).format(d);
}

export function formatDateTime(val: unknown, def = "-"): string {
  const d = parseToDate(val);
  if (!d) return def;
  const dateStr = formatDate(val, def);
  const timeStr = formatTime(val, def);
  if (dateStr === def || timeStr === def) return def;
  return `${dateStr}, ${timeStr}`;
}

export function toIso(val: unknown): string {
  const d = parseToDate(val);
  if (!d) return "";
  return d.toISOString().replace(/\.\d{3}Z$/, "Z");
}

views.addFilter("format_date", (val: unknown, def = "-") => formatDate(val, def));
views.addFilter("format_time", (val: unknown, def = "-") => formatTime(val, def));
views.addFilter("format_datetime", (val: unknown, def = "-") => formatDateTime(val, def));
views.addFilter("to_iso", (val: unknown) => toIso(val));

views.addGlobal("format_date", (val: unknown, def = "-") => formatDate(val, def));
views.addGlobal("format_time", (val: unknown, def = "-") => formatTime(val, def));
views.addGlobal("format_datetime", (val: unknown, def = "-") => formatDateTime(val, def));
views.addGlobal("to_iso", (val: unknown) => toIso(val));
views.addGlobal("current_year", () => new Date().getFullYear());
views.addGlobal("current_date", () => formatDate(new Date()));
const routes: Record<string, string> = {
  index: "/",
  "submit.complaint_form": "/submit/",
  "submit.track": "/submit/track",
  "submit.success": "/submit/success/:complaint_id",
  "submit.notifications_view": "/submit/notifications",
  "submit.notification_mark_read":
    "/submit/notifications/:notification_id/read",
  "submit.notification_mark_all_read": "/submit/notifications/read-all",
  "admin.login": "/admin/login",
  "admin.demo_login": "/admin/demo",
  "admin.logout": "/admin/logout",
  "admin.dashboard": "/admin/",
  "admin.complaint_detail": "/admin/complaint/:complaint_id",
  "admin.complaint_update": "/admin/complaint/:complaint_id/update",
  "admin.complaint_add_note": "/admin/complaint/:complaint_id/add_note",
  "admin.hotspots": "/admin/hotspots",
  "admin.map_view": "/admin/map",
  "admin.analytics_view": "/admin/analytics",
  "admin.reports_view": "/admin/reports",
  "admin.reports_export_csv": "/admin/reports/export.csv",
  "admin.action_brief": "/admin/brief",
  "admin.action_brief_generate": "/admin/brief/generate",
  static: "/static/:filename",
  serve_upload: "/uploads/:filename",
};
export function urlFor(name: string, kwargs: Record<string, unknown> = {}) {
  let target = routes[name];
  if (!target) throw new Error("Unknown route");
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(kwargs)) {
    if (key === "__keywords") continue;
    if (target.includes(":" + key))
      target = target.replace(
        ":" + key,
        key === "filename"
          ? String(value).split("/").map(encodeURIComponent).join("/")
          : encodeURIComponent(String(value)),
      );
    else if (value !== null && value !== undefined && value !== "")
      query.set(key, String(value));
  }
  return target + (query.size ? "?" + query : "");
}
views.addGlobal("url_for", urlFor);
views.addGlobal("get_flashed_messages", () => []);
export function render(
  template: string,
  context: Record<string, unknown> = {},
) {
  return views.render(template, context);
}
