"""
ai/clarity_analyzer.py – Complaint Description Quality & Clarity Analyzer
Phase 5.1 Implementation for URBANFIX.

Evaluates citizen complaint text for actionable completeness, detecting
missing landmarks or vague language and offering constructive guidance.
"""

from __future__ import annotations

import re
from typing import NamedTuple


class ClarityAnalysis(NamedTuple):
    is_clear: bool
    suggestions: list[str]
    missing_elements: list[str]
    word_count: int


_LOCATION_CUES = [
    "near", "opposite", "behind", "next to", "beside", "cross", "crossing",
    "junction", "street", "road", "lane", "avenue", "circle", "gate",
    "corner", "pillar", "block", "sector", "phase", "plot", "building",
    "school", "hospital", "park", "temple", "bus stop", "metro",
]

_VAGUE_PATTERNS = [
    r"^please fix (this|it)\.?$",
    r"^urgent help needed\.?$",
    r"^problem here\.?$",
    r"^issue in my area\.?$",
]


class ClarityAnalyzer:
    """Analyzes complaint descriptions for clarity and actionable details."""

    def analyze(self, description: str, address: str | None = None) -> ClarityAnalysis:
        desc = (description or "").strip()
        words = re.findall(r"\b\w+\b", desc)
        word_count = len(words)
        suggestions: list[str] = []
        missing_elements: list[str] = []

        # Check for vague phrasing
        desc_lower = desc.lower()
        for pattern in _VAGUE_PATTERNS:
            if re.match(pattern, desc_lower):
                suggestions.append(
                    "Description is very generic. Describing the exact nature of the problem helps teams prepare the right equipment."
                )
                missing_elements.append("Specific problem details")
                break

        # Check length
        if word_count < 8:
            suggestions.append(
                "Providing a bit more detail (e.g. approximate size, severity, or how long the issue has persisted) speeds up resolution."
            )
            missing_elements.append("Severity or duration details")

        # Check location indicators in description if address is not given
        has_address = bool(address and len(address.strip()) > 3)
        has_location_cue = any(cue in desc_lower for cue in _LOCATION_CUES)

        if not has_address and not has_location_cue:
            suggestions.append(
                "No landmarks or street references were detected. Mentioning nearby landmarks or crossroads helps workers locate the site quickly."
            )
            missing_elements.append("Landmark or location cue")

        is_clear = len(suggestions) == 0
        if is_clear:
            suggestions.append("Description is clear and actionable for field inspectors.")

        return ClarityAnalysis(
            is_clear=is_clear,
            suggestions=suggestions,
            missing_elements=missing_elements,
            word_count=word_count,
        )


_analyzer_instance: ClarityAnalyzer | None = None


def get_clarity_analyzer() -> ClarityAnalyzer:
    """Return singleton instance of ClarityAnalyzer."""
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = ClarityAnalyzer()
    return _analyzer_instance
