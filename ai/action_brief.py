"""
ai/action_brief.py – CivicAI Action Brief Generator
Phase 3E implementation.

PURPOSE
───────
Produces a structured, data-driven situation brief for admin officers.
The brief is generated entirely from existing complaint records and the
HotspotDetector — no LLM APIs, no external services, no model downloads.

OUTPUT STRUCTURE (ActionBrief dataclass)
─────────────────────────────────────────
  generated_at        – ISO timestamp of generation
  total_analysed      – number of complaints used as input
  situation_summary   – overall picture (plain text)
  top_categories      – list[(category, count)] top-3
  affected_locations  – list of unique non-empty addresses (up to 5)
  priority_overview   – dict with critical/high/medium/low counts
  urgent_complaints   – list of top complaint IDs needing immediate attention
  hotspot_analysis    – list[HotspotSummary] (per cluster)
  recommendations     – list[str] ordered by priority
  dept_recommendations – dict{dept_name: [action_str, …]}
  status              – "ok" | "empty" | "partial"

DESIGN RULES
────────────
- All output is traceable to real complaint records.
- No data is invented: locations, IDs, categories all come from the DB.
- Empty/missing data is handled gracefully: returns a "no data" brief.
- The brief is advisory — it never changes complaint records.
- Thread-safe: generates on every call from current DB state.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Tuple, Dict

logger = logging.getLogger(__name__)


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class HotspotSummary:
    """Summary of a single geographic hotspot cluster."""
    index:              int          # 1-based
    center_lat:         float
    center_lon:         float
    count:              int
    dominant_category:  str
    critical_count:     int
    high_count:         int
    avg_priority_score: float
    complaint_ids:      List[str]
    attention_reason:   str          # plain-English explanation


@dataclass
class ActionBrief:
    """Structured situation brief for admin officers."""
    generated_at:         str                         # ISO 8601
    total_analysed:       int
    situation_summary:    str
    top_categories:       List[Tuple[str, int]]       # [(category, count), …]
    affected_locations:   List[str]                   # unique addresses (≤5)
    priority_overview:    Dict[str, int]              # critical/high/medium/low
    urgent_complaints:    List[str]                   # complaint_ids (≤10)
    hotspot_analysis:     List[HotspotSummary]
    recommendations:      List[str]
    dept_recommendations: Dict[str, List[str]]
    status:               str                         # "ok" | "empty" | "partial"


# ── Department → category mapping ─────────────────────────────────────────────
# Guides the "dept_recommendations" section without inventing responsibilities.

_DEPT_CATEGORIES: Dict[str, List[str]] = {
    "Public Works":          ["Road Damage", "Drainage", "Tree / Vegetation"],
    "Water & Sanitation":    ["Waterlogging", "Water Supply", "Sewage", "Drainage"],
    "Waste Management":      ["Garbage Overflow"],
    "Electrical Department": ["Streetlight"],
    "Traffic & Safety":      ["Public Safety", "Road Damage"],
    "Parks & Environment":   ["Tree / Vegetation", "Noise Pollution", "Garbage Overflow"],
}

# Urgency signals for plain-text reasons
_URGENT_CATEGORIES = {"Public Safety", "Road Damage", "Waterlogging", "Sewage"}


# ── Generator ─────────────────────────────────────────────────────────────────

class ActionBriefGenerator:
    """
    Generates a structured ActionBrief from current complaint database state.

    Instantiate via ``get_brief_generator()``.  Call ``generate(complaints,
    hotspots)`` with pre-fetched data to produce the brief.

    All heavy lifting (DB reads, hotspot detection) is done by the caller
    (the route handler) so this class stays pure and easily testable.
    """

    def __init__(self) -> None:
        logger.info("ActionBriefGenerator initialised (Phase 3E).")

    # ── Public API ─────────────────────────────────────────────────────────────

    def generate(
        self,
        complaints: list[dict],
        hotspots: list | None = None,
    ) -> ActionBrief:
        """
        Generate a situation brief from complaint data.

        Parameters
        ----------
        complaints:
            List of complaint dicts (each must have at minimum: complaint_id,
            title, category, status, priority_level, priority_score, address).
            Extra keys (latitude, longitude) are used when present.
        hotspots:
            Optional list of Hotspot NamedTuples (from HotspotDetector.detect).
            Pass None or [] to skip hotspot analysis.

        Returns
        -------
        ActionBrief dataclass.  Never raises — returns a status="empty" brief
        on empty input and logs errors for unexpected failures.
        """
        try:
            return self._build_brief(complaints, hotspots or [])
        except Exception as exc:
            logger.error("ActionBriefGenerator.generate failed: %s", exc)
            return _empty_brief(status="partial")

    # ── Legacy stub methods (kept for backward compatibility) ──────────────────

    def generate_cluster_brief(self, cluster: dict) -> str:
        """
        Generate a brief for a single hotspot cluster (legacy interface).
        Returns a plain-text summary string.
        """
        count = cluster.get("count", 0)
        cat   = cluster.get("dominant_category", "complaints")
        lat   = cluster.get("center_lat", 0)
        lon   = cluster.get("center_lon", 0)
        if count == 0:
            return ""
        return (
            f"Hotspot of {count} {cat} complaint(s) centred near "
            f"({lat:.4f}, {lon:.4f}). "
            f"Immediate inspection recommended."
        )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _build_brief(
        self,
        complaints: list[dict],
        hotspots: list,
    ) -> ActionBrief:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        if not complaints:
            return _empty_brief(generated_at=now)

        total = len(complaints)

        # ── Category breakdown ────────────────────────────────────────────
        cat_counter: Counter = Counter()
        for c in complaints:
            cat_counter[c.get("category") or "Unknown"] += 1
        top_categories = cat_counter.most_common(3)   # [(cat, n), …]

        # ── Location extraction ───────────────────────────────────────────
        addresses: list[str] = []
        seen: set[str] = set()
        for c in complaints:
            addr = (c.get("address") or "").strip()
            if addr and addr not in seen:
                seen.add(addr)
                addresses.append(addr)
        affected_locations = addresses[:5]

        # ── Priority overview ─────────────────────────────────────────────
        priority_counts: Dict[str, int] = {
            "critical": 0, "high": 0, "medium": 0, "low": 0
        }
        for c in complaints:
            level = (c.get("priority_level") or "Low").lower()
            if level in priority_counts:
                priority_counts[level] += 1
            else:
                priority_counts["low"] += 1

        # ── Urgent complaints (top by priority_score, then by Critical/High) ─
        sorted_by_score = sorted(
            complaints,
            key=lambda c: (
                float(c.get("priority_score") or 0),
            ),
            reverse=True,
        )
        # Filter to non-resolved, non-closed
        open_complaints = [
            c for c in sorted_by_score
            if c.get("status") not in ("Resolved", "Closed", "Rejected")
        ]
        urgent_complaints = [c["complaint_id"] for c in open_complaints[:10]]

        # ── Situation summary ─────────────────────────────────────────────
        situation_summary = self._build_situation_summary(
            total, top_categories, priority_counts, hotspots
        )

        # ── Hotspot analysis ──────────────────────────────────────────────
        hotspot_analysis = self._build_hotspot_analysis(hotspots)

        # ── Recommendations ───────────────────────────────────────────────
        recommendations = self._build_recommendations(
            complaints, top_categories, priority_counts, hotspots
        )

        # ── Department-wise recommendations ──────────────────────────────
        dept_recommendations = self._build_dept_recommendations(
            complaints, cat_counter
        )

        status = "ok" if total > 0 else "empty"

        return ActionBrief(
            generated_at         = now,
            total_analysed       = total,
            situation_summary    = situation_summary,
            top_categories       = top_categories,
            affected_locations   = affected_locations,
            priority_overview    = priority_counts,
            urgent_complaints    = urgent_complaints,
            hotspot_analysis     = hotspot_analysis,
            recommendations      = recommendations,
            dept_recommendations = dept_recommendations,
            status               = status,
        )

    def _build_situation_summary(
        self,
        total: int,
        top_categories: list,
        priority_counts: dict,
        hotspots: list,
    ) -> str:
        critical = priority_counts.get("critical", 0)
        high     = priority_counts.get("high", 0)

        parts: list[str] = []
        parts.append(f"A total of {total} complaint(s) are currently on record.")

        if top_categories:
            top_cat, top_n = top_categories[0]
            pct = round(top_n / total * 100)
            parts.append(
                f"The most reported category is {top_cat} "
                f"({top_n} complaints, {pct}% of total)."
            )

        if critical > 0:
            parts.append(
                f"⚠ {critical} complaint(s) are rated Critical priority and require immediate attention."
            )
        if high > 0:
            parts.append(
                f"{high} complaint(s) are High priority."
            )

        if hotspots:
            parts.append(
                f"{len(hotspots)} geographic hotspot(s) have been detected, "
                f"indicating concentrated problem areas."
            )

        return " ".join(parts)

    def _build_hotspot_analysis(self, hotspots: list) -> list[HotspotSummary]:
        summaries: list[HotspotSummary] = []
        for idx, h in enumerate(hotspots, start=1):
            reason = _hotspot_reason(h)
            summaries.append(HotspotSummary(
                index              = idx,
                center_lat         = h.center_lat,
                center_lon         = h.center_lon,
                count              = h.count,
                dominant_category  = h.dominant_category,
                critical_count     = h.critical_count,
                high_count         = h.high_count,
                avg_priority_score = h.avg_priority_score,
                complaint_ids      = list(h.complaint_ids),
                attention_reason   = reason,
            ))
        return summaries

    def _build_recommendations(
        self,
        complaints: list[dict],
        top_categories: list,
        priority_counts: dict,
        hotspots: list,
    ) -> list[str]:
        recs: list[str] = []

        # 1. Critical-priority actions
        critical_n = priority_counts.get("critical", 0)
        if critical_n > 0:
            recs.append(
                f"Immediately escalate {critical_n} Critical-priority complaint(s) to department heads "
                f"for same-day action."
            )

        # 2. Category-specific actions
        for cat, count in top_categories:
            action = _category_action(cat, count)
            if action:
                recs.append(action)

        # 3. Hotspot-specific actions
        for h in hotspots[:3]:   # top 3 hotspots
            recs.append(
                f"Deploy a field inspection team to the {h.dominant_category} hotspot "
                f"centred near ({h.center_lat:.4f}, {h.center_lon:.4f}) "
                f"affecting {h.count} complaints."
            )

        # 4. Unassigned high-priority complaints
        unassigned_critical = [
            c for c in complaints
            if c.get("priority_level") in ("Critical", "High")
            and not c.get("department_id")
            and c.get("status") not in ("Resolved", "Closed", "Rejected")
        ]
        if unassigned_critical:
            recs.append(
                f"Assign {len(unassigned_critical)} unassigned High/Critical complaint(s) "
                f"to the relevant departments without delay."
            )

        # 5. Long-open complaints (status Submitted or Under Review)
        pending = [
            c for c in complaints
            if c.get("status") in ("Submitted", "Under Review")
        ]
        if len(pending) > 5:
            recs.append(
                f"{len(pending)} complaints are still in 'Submitted' or 'Under Review' status. "
                f"Review and assign these to appropriate departments."
            )

        # Limit to AI_BRIEF_MAX_STEPS
        try:
            from config import AI_BRIEF_MAX_STEPS
            recs = recs[:AI_BRIEF_MAX_STEPS]
        except ImportError:
            recs = recs[:5]

        return recs

    def _build_dept_recommendations(
        self,
        complaints: list[dict],
        cat_counter: Counter,
    ) -> Dict[str, List[str]]:
        """
        For each department, produce targeted actions based on complaint volume
        in its assigned categories.
        """
        dept_recs: Dict[str, List[str]] = {}

        for dept, cats in _DEPT_CATEGORIES.items():
            dept_actions: list[str] = []

            # Collect complaints in this dept's categories that are open
            open_in_cats = [
                c for c in complaints
                if c.get("category") in cats
                and c.get("status") not in ("Resolved", "Closed", "Rejected")
            ]
            if not open_in_cats:
                continue

            total_dept = len(open_in_cats)
            critical_n = sum(
                1 for c in open_in_cats if c.get("priority_level") == "Critical"
            )
            high_n = sum(
                1 for c in open_in_cats if c.get("priority_level") == "High"
            )

            dept_actions.append(
                f"{total_dept} open complaint(s) in assigned categories."
            )
            if critical_n:
                dept_actions.append(
                    f"⚠ {critical_n} Critical-priority complaint(s) require immediate action."
                )
            if high_n:
                dept_actions.append(
                    f"{high_n} High-priority complaint(s) need prompt follow-up."
                )

            # Top category for this dept
            dept_cat_counts = Counter(
                c.get("category") for c in open_in_cats
            )
            if dept_cat_counts:
                top_cat, top_n = dept_cat_counts.most_common(1)[0]
                dept_actions.append(
                    f"Focus on {top_cat} issues ({top_n} open complaint(s))."
                )

            dept_recs[dept] = dept_actions

        return dept_recs


# ── Utility helpers ───────────────────────────────────────────────────────────

def _empty_brief(
    generated_at: str | None = None,
    status: str = "empty",
) -> ActionBrief:
    """Return a placeholder brief for an empty dataset."""
    now = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    return ActionBrief(
        generated_at         = now,
        total_analysed       = 0,
        situation_summary    = "No complaints are currently on record. The brief will be available once complaints have been submitted.",
        top_categories       = [],
        affected_locations   = [],
        priority_overview    = {"critical": 0, "high": 0, "medium": 0, "low": 0},
        urgent_complaints    = [],
        hotspot_analysis     = [],
        recommendations      = ["No complaints on record. Await citizen submissions before generating an action brief."],
        dept_recommendations = {},
        status               = status,
    )


def _hotspot_reason(hotspot) -> str:
    """Plain-English reason why a hotspot needs attention."""
    parts: list[str] = [
        f"{hotspot.count} complaints of type '{hotspot.dominant_category}' are "
        f"concentrated within {hotspot.radius_km:.1f} km."
    ]
    if hotspot.critical_count > 0:
        parts.append(
            f"{hotspot.critical_count} of these are Critical priority."
        )
    if hotspot.high_count > 0:
        parts.append(f"{hotspot.high_count} are High priority.")
    if hotspot.avg_priority_score >= 50:
        parts.append(
            f"Average priority score is {hotspot.avg_priority_score:.1f}/100 — above threshold."
        )
    return " ".join(parts)


def _category_action(category: str, count: int) -> str | None:
    """Return a department-level recommendation for a category."""
    _actions: Dict[str, str] = {
        "Road Damage":       "Dispatch road maintenance crew to inspect and repair reported potholes and damaged surfaces.",
        "Waterlogging":      "Coordinate with drainage teams to clear blocked drains and pumping stations in affected areas.",
        "Garbage Overflow":  "Increase collection frequency in high-complaint areas and clear overflowing waste bins.",
        "Streetlight":       "Raise a bulk repair order for non-functional streetlights and prioritise dangerous road segments.",
        "Drainage":          "Inspect and clear blocked drainage channels; escalate to Water & Sanitation department.",
        "Public Safety":     "Alert Traffic & Safety department; increase patrol and monitoring in affected areas.",
        "Water Supply":      "Check supply lines for leaks or blockages; coordinate emergency tanker supply where needed.",
        "Sewage":            "Deploy sewage maintenance teams and inspect affected manholes and pipelines.",
        "Tree / Vegetation": "Arrange tree-trimming or removal for safety hazards; coordinate with Parks & Environment.",
        "Noise Pollution":   "Issue noise complaint notices; escalate persistent violations to relevant authorities.",
    }
    template = _actions.get(category)
    if not template:
        return None
    return f"[{category} – {count} open]: {template}"


# ── Module-level singleton ─────────────────────────────────────────────────────

_generator_instance: ActionBriefGenerator | None = None


def get_brief_generator() -> ActionBriefGenerator:
    """Return a cached ActionBriefGenerator instance."""
    global _generator_instance
    if _generator_instance is None:
        _generator_instance = ActionBriefGenerator()
    return _generator_instance
