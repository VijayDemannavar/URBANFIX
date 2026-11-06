"""
ai/predictive_insights.py – Predictive Civic Issue & Trend Insights
Phase 5.4 & 5.5 Implementation for URBANFIX.

Generates data-driven predictive insights, recurring problem alerts,
and category trend indicators from real historical complaints.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class CivicInsight:
    insight_type: str        # 'trend', 'recurring_hazard', 'maintenance_alert', 'performance'
    title: str
    description: str
    evidence: str
    confidence_label: str    # e.g., 'High Confidence', 'Estimated Trend', 'Early Signal'
    urgency_level: str       # 'Low', 'Medium', 'High', 'Critical'
    suggested_action: str


class PredictiveInsightsEngine:
    """Extracts actionable predictive insights from historical complaint records."""

    def generate_insights(self, complaints: List[Dict[str, Any]]) -> List[CivicInsight]:
        """
        Analyze a list of complaint dicts and return structured predictive insights.
        Never fabricates data; if data is sparse, returns honest baseline insights.
        """
        if not complaints:
            return [
                CivicInsight(
                    insight_type="trend",
                    title="Awaiting Historical Data",
                    description="Insufficient complaint records to generate predictive trend models.",
                    evidence="0 complaint records currently recorded in the active dataset.",
                    confidence_label="Baseline Observation",
                    urgency_level="Low",
                    suggested_action="Continue registering citizen reports to activate predictive forecasting.",
                )
            ]

        insights: List[CivicInsight] = []
        total = len(complaints)

        # 1. Category distribution and dominant trends
        cat_counts = Counter(c.get("category", "Other") for c in complaints)
        top_cat, top_cat_count = cat_counts.most_common(1)[0]
        top_cat_pct = round((top_cat_count / total) * 100, 1)

        if top_cat_pct >= 25.0 and top_cat_count >= 2:
            insights.append(
                CivicInsight(
                    insight_type="trend",
                    title=f"Elevated Category Cluster: {top_cat}",
                    description=f"{top_cat} accounts for {top_cat_pct}% of all logged issues.",
                    evidence=f"{top_cat_count} of {total} complaints belong to '{top_cat}'.",
                    confidence_label="High Confidence",
                    urgency_level="High" if top_cat in ("Public Safety", "Road Damage", "Sewage") else "Medium",
                    suggested_action=f"Dispatch preventive maintenance crews specializing in {top_cat}.",
                )
            )

        # 2. Recurring location analysis
        addr_counts = Counter(
            (c.get("address") or "").strip()
            for c in complaints
            if c.get("address") and len(c.get("address").strip()) > 3
        )
        recurring_locs = [(addr, cnt) for addr, cnt in addr_counts.items() if cnt >= 2]

        for addr, cnt in recurring_locs[:3]:
            insights.append(
                CivicInsight(
                    insight_type="recurring_hazard",
                    title=f"Recurring Problem Spot: {addr[:45]}",
                    description=f"Multiple complaints ({cnt}) have been logged near the same location.",
                    evidence=f"{cnt} independent reports reference location '{addr}'.",
                    confidence_label="High Confidence",
                    urgency_level="High" if cnt >= 3 else "Medium",
                    suggested_action="Perform on-site audit to address underlying structural cause rather than symptoms.",
                )
            )

        # 3. Critical urgency backlog insight
        critical_unresolved = [
            c for c in complaints
            if c.get("priority_level") == "Critical"
            and c.get("status") not in ("Resolved", "Closed")
        ]
        if critical_unresolved:
            insights.append(
                CivicInsight(
                    insight_type="maintenance_alert",
                    title="Critical Public Safety Backlog",
                    description=f"There {'are' if len(critical_unresolved) != 1 else 'is'} {len(critical_unresolved)} unresolved critical-priority complaint{'s' if len(critical_unresolved) != 1 else ''}.",
                    evidence=f"IDs: {', '.join(c.get('complaint_id', '') for c in critical_unresolved[:4])}",
                    confidence_label="Direct Observation",
                    urgency_level="Critical",
                    suggested_action="Immediate emergency escalation to designated municipal departmental head.",
                )
            )

        # 4. Seasonal or infrastructure foresight
        water_issues = sum(
            1 for c in complaints
            if c.get("category") in ("Waterlogging", "Drainage", "Sewage")
        )
        if water_issues >= 2:
            insights.append(
                CivicInsight(
                    insight_type="maintenance_alert",
                    title="Drainage & Stormwater Vulnerability",
                    description="Multiple drainage or waterlogging reports indicate localized stormwater conveyance bottlenecks.",
                    evidence=f"{water_issues} drainage/waterlogging reports detected in current dataset.",
                    confidence_label="Estimated Trend",
                    urgency_level="Medium",
                    suggested_action="Pre-monsoon culvert desilting and drain grate clearing recommended.",
                )
            )

        if not insights:
            insights.append(
                CivicInsight(
                    insight_type="performance",
                    title="Steady Civic Operations",
                    description="Complaints are evenly distributed across categories with no acute hazard clusters detected.",
                    evidence=f"Distribution across {len(cat_counts)} categories shows stable incoming report rates.",
                    confidence_label="Baseline Observation",
                    urgency_level="Low",
                    suggested_action="Maintain standard response schedules.",
                )
            )

        return insights


_insights_engine: PredictiveInsightsEngine | None = None


def get_insights_engine() -> PredictiveInsightsEngine:
    """Return singleton instance of PredictiveInsightsEngine."""
    global _insights_engine
    if _insights_engine is None:
        _insights_engine = PredictiveInsightsEngine()
    return _insights_engine
