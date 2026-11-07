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
const routes: Record<string, string> = {
  index: "/",
  "submit.complaint_form": "/submit/",
  "submit.track": "/submit/track",
  "submit.success": "/submit/success/:complaint_id",
  "submit.notifications_view": "/submit/notifications",
  "submit.notification_mark_read":
    "/submit/notifications/:notification_id/read",
  "submit.notification_mark_all_read": "/submit/notifications/read-all",
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
