"""
ai/ai_engine.py – CivicAI AI Orchestrator
Phase 3 implementation: chains categorisation + duplicate detection.
Priority scoring, hotspot detection, and action briefs are Phase 4–6.
"""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


class AIEngine:
    """
    Central AI orchestrator.

    Phase 3 implements:
      - NLP categorisation (keyword + TF-IDF, no downloads)
      - Duplicate detection (TF-IDF cosine similarity, no downloads)

    Phase 4+ will add:
      - Priority scoring
      - Hotspot detection
      - Action brief generation

    All AI failures are caught and logged; the submission flow is never blocked.
    """

    def __init__(self) -> None:
        self._classifier = None
        self._detector   = None
        self._priority   = None
        self._load_models()

    def _load_models(self) -> None:
        """Load classifier, detector, and priority engine — failures are isolated."""
        try:
            from ai.category_classifier import get_classifier
            self._classifier = get_classifier()
        except Exception as exc:
            logger.error("Failed to load CategoryClassifier: %s", exc)

        try:
            from ai.duplicate_detector import get_detector
            self._detector = get_detector()
        except Exception as exc:
            logger.error("Failed to load DuplicateDetector: %s", exc)

        try:
            from ai.priority_engine import get_priority_engine
            self._priority = get_priority_engine()
        except Exception as exc:
            logger.error("Failed to load PriorityEngine: %s", exc)

        logger.info(
            "AIEngine ready (classifier=%s, detector=%s, priority=%s).",
            "ok" if self._classifier else "FAILED",
            "ok" if self._detector   else "FAILED",
            "ok" if self._priority   else "FAILED",
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    def process_complaint(
        self,
        complaint_id: str,
        title: str,
        description: str,
        category: str,
        existing_complaints: list[dict] | None = None,
    ) -> dict:
        """
        Run the full Phase 3 AI pipeline on a new complaint.

        Args:
            complaint_id:        The newly saved complaint's ID.
            title:               Complaint title.
            description:         Complaint description.
            category:            Citizen-selected category (never overwritten).
            existing_complaints: Pre-fetched corpus for duplicate detection.
                                 If None, the detector fetches from DB itself.

        Returns dict with keys:
            ai_category, ai_confidence, ai_explanation, ai_needs_review,
            duplicate_matches (list of DuplicateMatch),
            priority_score, priority_level, priority_reason
        """
        result: dict = {
            # Categorisation defaults
            "ai_category":      category,     # safe default = citizen choice
            "ai_confidence":    0.0,
            "ai_explanation":   "",
            "ai_needs_review":  False,
            # Duplicate detection defaults
            "duplicate_matches": [],
            # Priority defaults
            "priority_score":   0,
            "priority_level":   "Low",
            "priority_reason":  "",
        }

        # ── Step 1: Categorisation ────────────────────────────────────
        if self._classifier is not None:
            try:
                cat_result = self._classifier.classify(title, description)
                result["ai_category"]    = cat_result.category
                result["ai_confidence"]  = cat_result.confidence
                result["ai_explanation"] = cat_result.explanation
                result["ai_needs_review"] = cat_result.needs_review
                logger.info(
                    "AI category for %s: %s (conf=%.2f, review=%s)",
                    complaint_id,
                    cat_result.category,
                    cat_result.confidence,
                    cat_result.needs_review,
                )
            except Exception as exc:
                logger.error("Categorisation failed for %s: %s", complaint_id, exc)

        # ── Step 2: Duplicate detection ───────────────────────────────
        if self._detector is not None:
            try:
                matches = self._detector.find_duplicates(
                    complaint_id=complaint_id,
                    title=title,
                    description=description,
                    existing_complaints=existing_complaints,
                )
                result["duplicate_matches"] = matches
                if matches:
                    logger.info(
                        "Duplicate detection for %s: %d match(es) found.",
                        complaint_id, len(matches),
                    )
            except Exception as exc:
                logger.error("Duplicate detection failed for %s: %s", complaint_id, exc)

        # ── Step 3: Priority scoring ──────────────────────────────────
        if self._priority is not None:
            try:
                dup_count = len(result["duplicate_matches"])
                pri = self._priority.score(
                    category        = result["ai_category"],
                    title           = title,
                    description     = description,
                    duplicate_count = dup_count,
                )
                result["priority_score"]  = pri.priority_score
                result["priority_level"]  = pri.priority_level
                result["priority_reason"] = pri.priority_reason
                logger.info(
                    "Priority for %s: %s (%d) — %s",
                    complaint_id, pri.priority_level,
                    pri.priority_score, pri.priority_reason[:80],
                )
            except Exception as exc:
                logger.error("Priority scoring failed for %s: %s", complaint_id, exc)

        return result

    # ── Legacy stub methods (kept for backwards compat) ───────────────────────

    def categorise(self, text: str) -> str:
        """Single-string categorisation (legacy interface)."""
        if self._classifier:
            result = self._classifier.classify(text, "")
            return result.category
        return "Other"

    def summarise(self, title: str, description: str) -> str:
        """AI summary generation – Phase 4."""
        return ""


# ── Module-level singleton ─────────────────────────────────────────────────────

_engine_instance: AIEngine | None = None


def get_engine() -> AIEngine:
    """Return a cached AIEngine instance (loaded once at startup)."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = AIEngine()
    return _engine_instance
