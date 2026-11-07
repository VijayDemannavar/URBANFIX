import { test } from "node:test";
import assert from "node:assert/strict";
import { render } from "../../server/render.js";
import { metrics, brief } from "../../server/analysis.js";
import { categories, statuses, priorityLevels } from "../../server/settings.js";
const complaint = {
  complaint_id: "CMP-TEST",
  title: "<script>alert(1)</script>",
  description: "A dangerous pothole near the school",
  category: "Road Damage",
  status: "Submitted",
  priority_level: "High",
  priority_score: 55,
  created_at: "2026-11-06 10:00:00",
  updated_at: "2026-11-06 10:00:00",
  resolved_at: null,
  latitude: 12,
  longitude: 77,
  address: "Main Road",
  ai_needs_review: 0,
  ai_confidence: 0.8,
};
for (const name of [
  "home.html",
  "submit/form.html",
  "submit/success.html",
  "track.html",
  "submit/notifications.html",
  "admin/dashboard.html",
  "admin/detail.html",
  "admin/map.html",
  "admin/hotspots.html",
  "admin/brief.html",
  "admin/analytics.html",
  "admin/reports.html",
])
  test(`renders ${name} with populated records`, () => {
    const rows = [complaint];
    const context = {
      request: { endpoint: "index" },
      csrf_token: () => "test-csrf",
      categories,
      statuses,
      priority_levels: priorityLevels,
      complaint,
      complaint_id: complaint.complaint_id,
      complaints: rows,
      stats: metrics(rows),
      metrics: metrics(rows),
      brief: brief(rows),
      form_data: {},
      errors: [],
      history: [],
      status_history: [],
      action_notes: [],
      duplicate_links: [],
      departments: [],
      all_officers: [],
      hotspots: [],
      hotspots_json: [],
      complaints_json: rows,
      notifications: [],
      active_cids: [],
      insights: [],
      total_geo: 1,
      page: 1,
      total_pages: 1,
      page_size: 100,
      total_matching: 1,
      active_sort: "submitted",
      active_order: "desc",
      total_count: 1,
    };
    const html = render(name, context);
    assert.ok(html.includes("URBANFIX"));
    assert.ok(!html.includes("<script>alert(1)</script>"));
  });
