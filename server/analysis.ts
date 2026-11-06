import { lexicon } from "./lexicon.js";
import {
  categoryDepartment,
  categories,
  statuses,
  priorityLevels,
} from "./settings.js";
export type Complaint = {
  complaint_id: string;
  title: string;
  description: string;
  category: string;
  status: string;
  priority_level: string;
  priority_score: number;
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  created_at: string;
  resolved_at: string | null;
  department_name?: string | null;
  [key: string]: unknown;
};
const words = (s: string) => new Set(s.toLowerCase().match(/[a-z0-9]+/g) ?? []);
function similarity(a: string, b: string) {
  const x = words(a),
    y = words(b);
  return x.size && y.size
    ? [...x].filter((v) => y.has(v)).length / Math.sqrt(x.size * y.size)
    : 0;
}
export function distance(
  a: Pick<Complaint, "latitude" | "longitude">,
  b: Pick<Complaint, "latitude" | "longitude">,
) {
  if (
    a.latitude === null ||
    a.longitude === null ||
    b.latitude === null ||
    b.longitude === null
  )
    return Infinity;
  const rad = Math.PI / 180;
  const dlat = (a.latitude - b.latitude) * rad,
    dlon = (a.longitude - b.longitude) * rad;
  return (
    6371 *
    2 *
    Math.asin(
      Math.min(
        1,
        Math.sqrt(
          Math.sin(dlat / 2) ** 2 +
            Math.cos(a.latitude * rad) *
              Math.cos(b.latitude * rad) *
              Math.sin(dlon / 2) ** 2,
        ),
      ),
    )
  );
}
export function analyze(
  input: {
    title: string;
    description: string;
    category: string;
    latitude: number | null;
    longitude: number | null;
    address: string | null;
  },
  existing: Complaint[],
) {
  const text =
    `${input.title} ${input.title} ${input.description}`.toLowerCase();
  const matches = Object.entries(lexicon._LEXICON)
    .map(([cat, terms]) => ({
      cat,
      score: terms.reduce(
        (s, [term, weight]) =>
          s + (text.includes(String(term)) ? Number(weight) : 0),
        0,
      ),
    }))
    .sort((a, b) => b.score - a.score);
  const best = matches[0];
  const category = best?.score > 0 ? best.cat : input.category;
  const confidence =
    best?.score > 0 ? Math.min(0.95, 0.5 + best.score / 30) : 0;
  const duplicate_matches = existing
    .map((c) => ({
      matched_complaint_id: c.complaint_id,
      similarity_score:
        0.5 * similarity(input.title, c.title) +
        0.3 * similarity(input.description, c.description) +
        0.1 * Number(category === c.category) +
        0.1 * Number(distance(input, c) <= 0.5),
    }))
    .filter((c) => c.similarity_score >= 0.6);
  let score =
    (lexicon._CATEGORY_BASE as Record<string, number>)[category] ?? 10;
  const reasons = [`Category baseline: ${score}`];
  for (const [phrases, bonus, label] of [
    [lexicon._URGENCY_PHRASES, 25, "Safety risk"],
    [lexicon._INFRA_PHRASES, 15, "Service disruption"],
    [lexicon._SCOPE_PHRASES, 10, "Wide impact"],
    [lexicon._DURATION_PHRASES, 10, "Persistent issue"],
  ] as const) {
    if (phrases.some((p) => text.includes(p))) {
      score += bonus;
      reasons.push(label);
    }
  }
  score = Math.min(100, score + Math.min(15, duplicate_matches.length * 5));
  const suggestions = [];
  if (
    !input.address &&
    !/street|road|near|opposite|ward|sector/i.test(input.description)
  )
    suggestions.push("Add a precise location or nearby landmark.");
  if (input.description.length < 80)
    suggestions.push(
      "Describe the impact and how long the issue has persisted.",
    );
  return {
    ai_category: category,
    ai_confidence: confidence,
    ai_needs_review: Number(confidence < 0.55),
    ai_explanation:
      best?.score > 0
        ? `Matched civic category keywords for ${category}.`
        : "No strong keyword match; citizen category retained for review.",
    ai_suggested_dept: categoryDepartment[category],
    ai_feedback: suggestions.join(" "),
    priority_score: score,
    priority_level:
      score >= 75
        ? "Critical"
        : score >= 50
          ? "High"
          : score >= 25
            ? "Medium"
            : "Low",
    priority_reason: reasons.join("; "),
    duplicate_matches,
    suggestions,
  };
}
export function hotspots(rows: Complaint[]) {
  const geo = rows.filter((c) => c.latitude !== null && c.longitude !== null);
  const seen = new Set<string>();
  const result = [];
  for (const c of geo) {
    if (seen.has(c.complaint_id)) continue;
    const group = geo.filter(
      (d) => !seen.has(d.complaint_id) && distance(c, d) <= 0.5,
    );
    if (group.length < 3) continue;
    group.forEach((d) => seen.add(d.complaint_id));
    const counts = categories
      .map(
        (category) =>
          [
            category,
            group.filter((d) => d.category === category).length,
          ] as const,
      )
      .sort((a, b) => b[1] - a[1]);
    result.push({
      index: result.length + 1,
      center_lat: group.reduce((s, d) => s + d.latitude!, 0) / group.length,
      center_lon: group.reduce((s, d) => s + d.longitude!, 0) / group.length,
      count: group.length,
      complaint_ids: group.map((d) => d.complaint_id),
      dominant_category: counts[0][0],
      radius_km: 0.5,
      critical_count: group.filter((d) => d.priority_level === "Critical")
        .length,
      high_count: group.filter((d) => d.priority_level === "High").length,
      avg_priority_score:
        group.reduce((s, d) => s + d.priority_score, 0) / group.length,
      attention_reason:
        "Multiple complaints within 500 metres; coordinate a site inspection.",
    });
  }
  return result;
}
export function metrics(rows: Complaint[]) {
  const counts: Record<string, number> = {};
  for (const label of [...statuses, ...priorityLevels])
    counts[label.toLowerCase().replaceAll(" ", "_")] = rows.filter(
      (c) => c.status === label || c.priority_level === label,
    ).length;
  const resolved = rows.filter((c) =>
    ["Resolved", "Closed"].includes(c.status),
  );
  const times = resolved
    .filter((c) => c.resolved_at)
    .map(
      (c) => (Date.parse(c.resolved_at!) - Date.parse(c.created_at)) / 86400000,
    );
  const open = rows.filter(
    (c) => !["Resolved", "Closed", "Rejected"].includes(c.status),
  );
  const months = [...new Set(rows.map((c) => c.created_at.slice(0, 7)))].sort();
  return {
    ...counts,
    resolved: counts.resolved,
    closed: counts.closed,
    critical: counts.critical,
    total: rows.length,
    pending: counts.submitted + counts.under_review,
    active_categories: new Set(rows.map((c) => c.category)).size,
    resolution_rate: rows.length
      ? Math.round((resolved.length / rows.length) * 1000) / 10
      : 0,
    avg_resolution_days: times.length
      ? Math.round((times.reduce((s, n) => s + n, 0) / times.length) * 10) / 10
      : 0,
    category_distribution: categories
      .map((category) => ({
        category,
        count: rows.filter((c) => c.category === category).length,
      }))
      .filter((c) => c.count)
      .sort((a, b) => b.count - a.count),
    department_distribution: [
      ...new Set(rows.map((c) => c.department_name || "Unassigned")),
    ].map((department) => ({
      department,
      total: rows.filter(
        (c) => (c.department_name || "Unassigned") === department,
      ).length,
      unresolved: open.filter(
        (c) => (c.department_name || "Unassigned") === department,
      ).length,
    })),
    monthly_trends: months.map((month) => ({
      month,
      count: rows.filter((c) => c.created_at.startsWith(month)).length,
      resolved: resolved.filter((c) => c.created_at.startsWith(month)).length,
    })),
    unresolved_long: open
      .toSorted((a, b) => a.created_at.localeCompare(b.created_at))
      .slice(0, 10),
    critical_urgent: open
      .filter((c) => c.priority_level === "Critical")
      .toSorted((a, b) => b.priority_score - a.priority_score)
      .slice(0, 10),
  };
}
export function brief(rows: Complaint[]) {
  const m = metrics(rows);
  const open = rows.filter(
    (c) => !["Resolved", "Closed", "Rejected"].includes(c.status),
  );
  return {
    status: rows.length ? "ok" : "empty",
    generated_at: new Date().toISOString(),
    total_analysed: rows.length,
    situation_summary: `${rows.length} complaints recorded; ${open.length} require action. ${m.critical} critical complaints need prompt assessment.`,
    priority_overview: m,
    top_categories: m.category_distribution
      .slice(0, 5)
      .map((c) => [c.category, c.count]),
    affected_locations: [
      ...new Set(open.map((c) => c.address).filter(Boolean)),
    ].slice(0, 5),
    urgent_complaints: open
      .toSorted((a, b) => b.priority_score - a.priority_score)
      .slice(0, 5)
      .map((c) => c.complaint_id),
    hotspot_analysis: hotspots(rows),
    recommendations: open.length
      ? [
          "Assess critical safety issues first.",
          "Assign unallocated complaints to the responsible department.",
          "Inspect complaint clusters together and publish resolution evidence.",
        ]
      : ["Review completed work and monitor new submissions."],
    dept_recommendations: Object.fromEntries(
      [...new Set(open.map((c) => categoryDepartment[c.category]))].map(
        (name) => [
          name,
          [
            `Review ${open.filter((c) => categoryDepartment[c.category] === name).length} open complaints and schedule field work.`,
          ],
        ],
      ),
    ),
  };
}
export function insights(rows: Complaint[]) {
  return metrics(rows)
    .category_distribution.filter((c) => c.count >= 3)
    .map((c) => ({
      title: `Recurring ${c.category.toLowerCase()} reports`,
      urgency_level: "High",
      description: "Repeated reports suggest a persistent service issue.",
      evidence: `${c.count} complaints in this category.`,
      suggested_action: `Ask ${categoryDepartment[c.category]} to investigate recurring causes.`,
      confidence_label: "Based on observed complaint counts",
    }));
}
