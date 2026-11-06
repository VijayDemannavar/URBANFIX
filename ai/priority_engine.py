"""
ai/priority_engine.py – CivicAI Priority Scoring Engine
Phase 3C implementation.

SCORING MODEL
─────────────
Priority score is an integer in [0, 100] built from additive factors:

  1. Category base score  (0–40)
     Each civic category carries a baseline urgency.
     Public Safety leads at 40 because life-risk is implicit.

  2. Urgency keywords  (+25, once)
     Phrases indicating danger to life or limb.
     Examples: accident, collapse, fire, electrocution, injury, fatality.

  3. Infrastructure-risk keywords  (+15, once)
     Indicators that a service is disabled or access is blocked.
     Examples: road closed, no water, no electricity, collapsed, blocked drain.

  4. Scope keywords  (+10, once)
     Language suggesting many people are affected.
     Examples: entire area, multiple, hundreds, whole colony.

  5. Duration keywords  (+10, once)
     Language suggesting the problem has persisted for a long time.
     Examples: weeks, months, since last year, long time.

  6. Duplicate count bonus  (+5 per confirmed duplicate, max +15)
     Multiple independent reports of the same issue signal wider impact.

Final score is clamped to [0, 100].

LEVEL MAPPING (from config)
────────────────────────────
  Critical  →  score ≥ AI_PRIORITY_CRITICAL_MIN   (default 75)
  High      →  score ≥ AI_PRIORITY_HIGH_MIN        (default 50)
  Medium    →  score ≥ AI_PRIORITY_MEDIUM_MIN      (default 25)
  Low       →  score  < AI_PRIORITY_MEDIUM_MIN

No paid APIs. No model downloads. Pure Python + config.
"""

from __future__ import annotations

import re
import logging
from typing import NamedTuple

logger = logging.getLogger(__name__)


# ── Result type ────────────────────────────────────────────────────────────────

class PriorityResult(NamedTuple):
    priority_score:  int     # 0–100
    priority_level:  str     # Low | Medium | High | Critical
    priority_reason: str     # human-readable explanation


# ── Keyword tables ─────────────────────────────────────────────────────────────

# Danger-to-life / urgent safety signals
_URGENCY_PHRASES: list[str] = [
    "accident", "accidents", "injured", "injury", "injuries",
    "fatality", "fatalities", "death", "died", "killed",
    "collapse", "collapsed", "collapsing",
    "fire", "burning", "smoke",
    "electrocution", "electric shock", "live wire", "exposed wire",
    "flood", "flooded", "flooding", "submerged",
    "attack", "attacked", "robbery", "assault", "assaulted", "violence",
    "emergency", "dangerous", "hazardous", "life-threatening",
    "blood", "bleeding",
]

# Infrastructure failure / service disruption signals
_INFRA_PHRASES: list[str] = [
    "road closed", "road blocked", "path blocked", "blocked road",
    "no water", "no water supply", "water cut", "water outage",
    "no electricity", "power outage", "power cut", "no power",
    "no streetlight", "no light", "dark road",
    "blocked drain", "drain blocked", "drain overflow",
    "sewage overflow", "sewage blocked",
    "bridge damaged", "bridge broken",
    "collapsed road", "road collapse",
    "manhole open", "open manhole", "uncovered manhole",
    "gas leak",
]

# Wide-impact / scope signals
_SCOPE_PHRASES: list[str] = [
    "entire area", "entire street", "entire road", "entire colony",
    "whole area", "whole street",
    "multiple", "several complaints",
    "hundreds of", "thousands of",
    "all residents", "everyone", "entire neighbourhood",
    "very large",
]

# Long-duration / neglect signals
_DURATION_PHRASES: list[str] = [
    "for weeks", "past weeks", "several weeks",
    "for months", "past months", "several months",
    "for years", "past years", "since last year",
    "long time", "a long time", "very long",
    "since ages", "since forever",
    "weeks ago", "months ago", "years ago",
    "not fixed", "still not", "never fixed", "no action",
    "repeatedly reported", "reported multiple times",
    "ignored", "no response",
]

# Category baseline urgency scores (0–40)
_CATEGORY_BASE: dict[str, int] = {
    "Public Safety":    50,   # life-safety always scores high baseline
    "Road Damage":      30,
    "Waterlogging":     25,
    "Drainage":         22,
    "Sewage":           20,
    "Streetlight":      22,   # raised: non-functional light is a safety risk
    "Garbage Overflow": 15,
    "Water Supply":     20,
    "Tree / Vegetation": 12,
    "Noise Pollution":  10,
    "Other":            10,
}

# Bonus per confirmed duplicate complaint, capped at MAX_DUPLICATE_BONUS
_DUPLICATE_BONUS_PER  = 5
_MAX_DUPLICATE_BONUS  = 15


# ── Engine class ───────────────────────────────────────────────────────────────

class PriorityEngine:
    """
    Assigns a numeric priority score (0–100) and human-readable level
    to each complaint using rule-based NLP signals.

    No model downloads, no paid APIs.  Instantiate once; call ``score()``.
    """

    def __init__(self) -> None:
        from config import (
            AI_PRIORITY_CRITICAL_MIN,
            AI_PRIORITY_HIGH_MIN,
            AI_PRIORITY_MEDIUM_MIN,
        )
        self._critical_min = AI_PRIORITY_CRITICAL_MIN
        self._high_min     = AI_PRIORITY_HIGH_MIN
        self._medium_min   = AI_PRIORITY_MEDIUM_MIN
        logger.info(
            "PriorityEngine ready (Critical≥%d, High≥%d, Medium≥%d).",
            self._critical_min, self._high_min, self._medium_min,
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    def score(
        self,
        category: str,
        title: str,
        description: str,
        duplicate_count: int = 0,
    ) -> PriorityResult:
        """
        Compute priority for a complaint.

        Args:
            category:        Civic category string (from COMPLAINT_CATEGORIES).
            title:           Complaint title.
            description:     Complaint description.
            duplicate_count: Number of confirmed duplicate/similar complaints
                             already in the system.  Each adds a small bonus
                             to reflect community-wide impact.

        Returns:
            PriorityResult(priority_score, priority_level, priority_reason)
        """
        text = (title + " " + description).lower()
        factors: list[str] = []
        total = 0

        # ── Factor 1: Category base score ─────────────────────────────────────
        base = _CATEGORY_BASE.get(category, _CATEGORY_BASE["Other"])
        total += base
        factors.append(f"category '{category}' base={base}")

        # ── Factor 2: Urgency keywords ────────────────────────────────────────
        urgency_hit = _any_phrase(text, _URGENCY_PHRASES)
        if urgency_hit:
            total += 25
            factors.append(f"urgency signal '{urgency_hit}' +25")

        # ── Factor 3: Infrastructure-risk keywords ────────────────────────────
        infra_hit = _any_phrase(text, _INFRA_PHRASES)
        if infra_hit:
            total += 15
            factors.append(f"infrastructure risk '{infra_hit}' +15")

        # ── Factor 4: Scope keywords ──────────────────────────────────────────
        scope_hit = _any_phrase(text, _SCOPE_PHRASES)
        if scope_hit:
            total += 10
            factors.append(f"wide scope '{scope_hit}' +10")

        # ── Factor 5: Duration / neglect keywords ─────────────────────────────
        duration_hit = _any_phrase(text, _DURATION_PHRASES)
        if duration_hit:
            total += 10
            factors.append(f"long duration '{duration_hit}' +10")

        # ── Factor 6: Duplicate count bonus ──────────────────────────────────
        if duplicate_count > 0:
            dup_bonus = min(duplicate_count * _DUPLICATE_BONUS_PER,
                           _MAX_DUPLICATE_BONUS)
            total += dup_bonus
            factors.append(
                f"{duplicate_count} duplicate(s) +{dup_bonus}"
            )

        # ── Clamp and map to level ────────────────────────────────────────────
        final_score = max(0, min(100, total))
        level       = self.score_to_level(final_score)
        reason      = "; ".join(factors)

        logger.debug(
            "Priority: %s | score=%d | level=%s | factors=[%s]",
            title[:40], final_score, level, reason,
        )
        return PriorityResult(
            priority_score  = final_score,
            priority_level  = level,
            priority_reason = reason,
        )

    def score_to_level(self, score: int) -> str:
        """Map a numeric score [0–100] to a priority level string."""
        if score >= self._critical_min:
            return "Critical"
        if score >= self._high_min:
            return "High"
        if score >= self._medium_min:
            return "Medium"
        return "Low"


# ── Phrase-matching helper ─────────────────────────────────────────────────────

def _any_phrase(text: str, phrases: list[str]) -> str | None:
    """
    Return the first phrase from ``phrases`` found in ``text``, or None.

    Matches whole-word boundaries for single words; substring match for
    multi-word phrases (to catch "road closed at junction" etc.)
    """
    for phrase in phrases:
        if " " in phrase:
            # Multi-word: simple substring match (text is already lowercased)
            if phrase in text:
                return phrase
        else:
            # Single word: whole-word boundary
            if re.search(r"\b" + re.escape(phrase) + r"\b", text):
                return phrase
    return None


# ── Module-level singleton ─────────────────────────────────────────────────────

_engine_instance: PriorityEngine | None = None


def get_priority_engine() -> PriorityEngine:
    """Return a cached PriorityEngine instance."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = PriorityEngine()
    return _engine_instance
