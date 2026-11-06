"""
ai/department_recommender.py – Intelligent Department and Authority Recommendations
Phase 5.3 Implementation for URBANFIX.

Analyzes complaint category and description text to recommend the most suitable
municipal department with a clear explanation, and suggests officers if available.
"""

from __future__ import annotations

import logging
from typing import NamedTuple
import database as db

logger = logging.getLogger(__name__)


class DepartmentRecommendation(NamedTuple):
    recommended_department: str
    department_id: int | None
    rationale: str
    suggested_officer: str | None
    suggested_officer_id: int | None
    confidence: float


# Category-to-Department authoritative mapping
_DEPT_CATEGORY_MAP = {
    "Road Damage": "Public Works",
    "Drainage": "Water & Sanitation",
    "Waterlogging": "Water & Sanitation",
    "Water Supply": "Water & Sanitation",
    "Sewage": "Water & Sanitation",
    "Garbage Overflow": "Waste Management",
    "Streetlight": "Electrical Department",
    "Public Safety": "Traffic & Safety",
    "Tree / Vegetation": "Parks & Environment",
    "Noise Pollution": "Parks & Environment",
}

# Domain keyword cues for cross-category nuance
_DEPT_KEYWORD_CUES = {
    "Public Works": [
        "pothole", "asphalt", "tar", "road", "pavement", "footpath", "sidewalk",
        "speed breaker", "bridge", "flyover", "divider", "curb", "sinkhole",
    ],
    "Water & Sanitation": [
        "pipe", "pipeline", "leak", "water supply", "drinking water", "drainage",
        "sewer", "sewage", "manhole", "waterlogging", "flood", "stagnant water",
    ],
    "Waste Management": [
        "garbage", "trash", "waste", "dump", "dustbin", "litter", "debris",
        "dead animal", "sanitation bin", "rubbish", "stench",
    ],
    "Electrical Department": [
        "streetlight", "light", "lamp", "pole", "wire", "cable", "transformer",
        "electric shock", "high voltage", "dark road", "power cut",
    ],
    "Traffic & Safety": [
        "traffic", "signal", "hazard", "accident", "barricade", "zebra crossing",
        "blind spot", "rash driving", "parking obstruction",
    ],
    "Parks & Environment": [
        "tree", "branch", "park", "garden", "foliage", "overgrown", "noise",
        "loudspeaker", "pollution", "smoke", "greenery",
    ],
}


class DepartmentRecommender:
    """Intelligent department and officer recommendation engine."""

    def recommend(
        self,
        category: str,
        title: str = "",
        description: str = "",
        departments: list[dict] | None = None,
    ) -> DepartmentRecommendation:
        """
        Produce a department recommendation based on category and textual cues.
        """
        title_lower = (title or "").lower()
        desc_lower = (description or "").lower()
        full_text = f"{title_lower} {desc_lower}"

        # 1. Primary department candidate from category mapping
        primary_dept_name = _DEPT_CATEGORY_MAP.get(category, "Public Works")
        rationale_parts = []
        confidence = 0.85

        if category in _DEPT_CATEGORY_MAP:
            rationale_parts.append(
                f"Issues categorized as '{category}' fall directly under the jurisdiction of the {primary_dept_name}."
            )

        # 2. Check keyword cues for cross-department nuances
        keyword_hits = 0
        for dept_name, cues in _DEPT_KEYWORD_CUES.items():
            hits = [kw for kw in cues if kw in full_text]
            if hits:
                if dept_name == primary_dept_name:
                    keyword_hits += len(hits)
                    rationale_parts.append(
                        f"Detected domain keywords ({', '.join(hits[:3])}) matching {dept_name} operations."
                    )
                elif len(hits) >= 3 and category == "Other":
                    # Strong signal overrides 'Other'
                    primary_dept_name = dept_name
                    confidence = 0.75
                    rationale_parts = [
                        f"Text analysis detected strong keywords ({', '.join(hits[:3])}) corresponding to {dept_name}."
                    ]
                    break

        if not rationale_parts:
            rationale_parts.append(
                f"Assigned to {primary_dept_name} based on standard municipal operational guidelines."
            )

        rationale = " ".join(rationale_parts)

        # 3. Match with database records
        all_depts = departments or [dict(r) for r in db.get_all_departments()]
        target_dept = next(
            (d for d in all_depts if d.get("department_name") == primary_dept_name),
            None,
        )

        dept_id = target_dept.get("id") if target_dept else None
        suggested_officer = None
        suggested_officer_id = None

        if dept_id:
            officers = [dict(o) for o in db.get_officers_by_department(dept_id)]
            if officers:
                # Suggest first available officer
                first_off = officers[0]
                suggested_officer = first_off.get("officer_name")
                suggested_officer_id = first_off.get("id")
                rationale += f" Suggested duty officer: {suggested_officer}."

        return DepartmentRecommendation(
            recommended_department=primary_dept_name,
            department_id=dept_id,
            rationale=rationale,
            suggested_officer=suggested_officer,
            suggested_officer_id=suggested_officer_id,
            confidence=min(1.0, confidence + (0.05 if keyword_hits > 0 else 0.0)),
        )


_recommender_instance: DepartmentRecommender | None = None


def get_recommender() -> DepartmentRecommender:
    """Return singleton instance of DepartmentRecommender."""
    global _recommender_instance
    if _recommender_instance is None:
        _recommender_instance = DepartmentRecommender()
    return _recommender_instance
