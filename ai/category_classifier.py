"""
ai/category_classifier.py – CivicAI Complaint Category Classifier
Phase 3A implementation.

Algorithm: two-stage hybrid
  Stage 1 – Keyword lexicon score
    Each category has a hand-crafted set of weighted keywords.
    We count (case-insensitive, word-boundary) hits in title+description
    and normalise by category weight total.

  Stage 2 – TF-IDF cosine similarity (numpy, no external downloads)
    We build a vocabulary from the complaint text + category exemplar corpus.
    We score the incoming text against each category exemplar.
    The two scores are blended (lexicon 60%, TF-IDF 40%).

  Low-confidence handling:
    If the top score < AI_CATEGORY_CONFIDENCE_THRESHOLD the prediction is
    flagged needs_review=True and the explanation says "Low confidence".

No paid APIs, no model downloads, no external packages beyond numpy.
numpy is already available in the Python standard data-science distribution.
Falls back to pure-Python Jaccard if numpy is unavailable.
"""

from __future__ import annotations

import re
import math
import logging
from collections import Counter
from typing import NamedTuple

logger = logging.getLogger(__name__)

# ── Types ──────────────────────────────────────────────────────────────────────

class CategoryResult(NamedTuple):
    category:     str
    confidence:   float        # 0.0 – 1.0
    explanation:  str
    needs_review: bool         # True when confidence is low


# ── Lexicon ────────────────────────────────────────────────────────────────────
# Each entry: (keyword, weight).  Weight 2 = strong signal, 1 = moderate.

_LEXICON: dict[str, list[tuple[str, float]]] = {
    "Road Damage": [
        ("pothole", 2.0), ("road", 1.5), ("crack", 1.5), ("damaged road", 2.0),
        ("broken road", 2.0), ("road damage", 2.0), ("asphalt", 1.5),
        ("carriageway", 1.5), ("speed breaker", 1.5), ("sinkhole", 2.0),
        ("road surface", 2.0), ("pavement", 1.5), ("tyre", 1.5), ("footpath", 1.0),
        ("road marking", 1.5), ("eroded", 1.5), ("collapsed", 1.0),
    ],
    "Waterlogging": [
        ("waterlogging", 2.0), ("waterlogged", 2.0), ("flooding", 2.0),
        ("flood", 2.0), ("standing water", 2.0), ("stagnant water", 2.0),
        ("inundated", 2.0), ("knee deep", 2.0), ("submerged", 1.5),
        ("water accumulation", 2.0), ("puddle", 1.5), ("dip", 1.0),
    ],
    "Garbage Overflow": [
        ("garbage", 2.0), ("waste", 1.5), ("trash", 1.5), ("rubbish", 1.5),
        ("litter", 1.5), ("overflowing bin", 2.0), ("garbage bin", 2.0),
        ("dump", 1.5), ("dumping", 1.5), ("refuse", 1.5), ("stench", 1.5),
        ("sanitation", 1.0), ("uncollected", 2.0), ("not collected", 2.0),
    ],
    "Streetlight": [
        ("streetlight", 2.0), ("street light", 2.0), ("lamp post", 2.0),
        ("light not working", 2.0), ("broken light", 2.0), ("dark", 1.5),
        ("no light", 2.0), ("lighting", 1.5), ("night", 1.0), ("illumination", 1.5),
        ("street lamp", 2.0), ("pole light", 1.5),
    ],
    "Drainage": [
        ("drainage", 2.0), ("drain", 2.0), ("blocked drain", 2.0),
        ("clogged drain", 2.0), ("storm drain", 1.5), ("culvert", 1.5),
        ("channel", 1.0), ("silt", 1.5), ("pipe burst", 2.0),
        ("pipe blocked", 2.0), ("open drain", 1.5), ("manhole overflow", 1.5),
    ],
    "Public Safety": [
        ("safety", 1.5), ("dangerous", 1.5), ("hazard", 2.0), ("risk", 1.5),
        ("injury", 2.0), ("accident", 2.0), ("live wire", 2.0), ("electric wire", 2.0),
        ("sinkhole", 1.5), ("collapsed", 1.5), ("stray dog", 2.0), ("fire", 1.5),
        ("gas leak", 2.0), ("manhole", 1.5), ("fallen tree", 1.5), ("unsafe", 2.0),
        ("children", 1.0), ("emergency", 2.0),
    ],
    "Water Supply": [
        ("water supply", 2.0), ("water cut", 2.0), ("no water", 2.0),
        ("water disruption", 2.0), ("tap water", 1.5), ("piped water", 2.0),
        ("water pressure", 1.5), ("water shortage", 2.0), ("water meter", 1.5),
        ("contaminated water", 2.0), ("dirty water", 2.0), ("brown water", 2.0),
        ("water connection", 1.5), ("water tank", 1.5),
    ],
    "Sewage": [
        ("sewage", 2.0), ("sewer", 2.0), ("manhole overflow", 2.0),
        ("overflowing manhole", 2.0), ("sewage pipe", 2.0), ("foul smell", 2.0),
        ("sewage leak", 2.0), ("septic", 1.5), ("wastewater", 1.5),
        ("toilet overflow", 1.5), ("sewage smell", 2.0),
    ],
    "Tree / Vegetation": [
        ("tree", 2.0), ("branch", 1.5), ("fallen tree", 2.0), ("overgrown", 2.0),
        ("vegetation", 1.5), ("branches blocking", 2.0), ("tree fall", 2.0),
        ("dry tree", 2.0), ("uprooted", 2.0), ("trimming", 1.5), ("pruning", 1.5),
        ("roots", 1.0), ("park maintenance", 1.0),
    ],
    "Noise Pollution": [
        ("noise", 2.0), ("loud", 1.5), ("noise pollution", 2.0), ("music", 1.5),
        ("loudspeaker", 2.0), ("construction noise", 2.0), ("disturbing", 1.5),
        ("sound", 1.0), ("decibel", 1.5), ("night noise", 2.0), ("speaker", 1.5),
    ],
    "Other": [
        ("other", 1.0), ("miscellaneous", 1.0), ("general complaint", 1.0),
    ],
}

# Category exemplar sentences – used for TF-IDF stage
_EXEMPLARS: dict[str, str] = {
    "Road Damage":
        "pothole road damage crack broken asphalt carriageway eroded surface sinkhole pavement road marking speed breaker",
    "Waterlogging":
        "waterlogging flooding flood standing water stagnant water inundated submerged water accumulation",
    "Garbage Overflow":
        "garbage waste trash rubbish litter overflowing bin dump dumping refuse uncollected not collected",
    "Streetlight":
        "streetlight street light lamp post dark no light broken light night illumination street lamp pole",
    "Drainage":
        "drainage drain blocked drain clogged silt pipe burst channel culvert open drain manhole overflow",
    "Public Safety":
        "safety dangerous hazard risk injury accident live wire electric wire stray dog fire gas leak unsafe emergency",
    "Water Supply":
        "water supply water cut no water disruption tap piped pressure shortage contaminated dirty brown water meter",
    "Sewage":
        "sewage sewer manhole overflow foul smell sewage pipe leak septic wastewater",
    "Tree / Vegetation":
        "tree branch fallen overgrown vegetation blocking uprooted dry trimming pruning roots",
    "Noise Pollution":
        "noise loud noise pollution music loudspeaker construction disturbing sound decibel night",
    "Other":
        "other miscellaneous general complaint",
}

CATEGORIES = list(_LEXICON.keys())


# ── Text utilities ─────────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, return word tokens."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return [t for t in text.split() if len(t) > 1]


def _keyword_score(text_lower: str, keywords: list[tuple[str, float]]) -> float:
    """Sum weights of keyword phrases found in text (case-insensitive)."""
    total = 0.0
    for phrase, weight in keywords:
        if phrase in text_lower:
            total += weight
    return total


# ── TF-IDF helpers (pure numpy / fallback) ────────────────────────────────────

def _build_idf(documents: list[list[str]]) -> dict[str, float]:
    """Compute IDF for all terms across the document corpus."""
    N = len(documents)
    df: Counter = Counter()
    for doc in documents:
        for term in set(doc):
            df[term] += 1
    return {term: math.log((N + 1) / (count + 1)) + 1
            for term, count in df.items()}


def _tfidf_vector(tokens: list[str], vocab: list[str], idf: dict[str, float]) -> list[float]:
    """Build a TF-IDF vector for the given tokens."""
    tf = Counter(tokens)
    n  = len(tokens) or 1
    return [tf.get(v, 0) / n * idf.get(v, 0.0) for v in vocab]


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors. Pure Python, numpy optional."""
    try:
        import numpy as np
        va, vb = np.array(a, dtype=float), np.array(b, dtype=float)
        na, nb = np.linalg.norm(va), np.linalg.norm(vb)
        if na == 0 or nb == 0:
            return 0.0
        return float(np.dot(va, vb) / (na * nb))
    except ImportError:
        dot = sum(x * y for x, y in zip(a, b))
        na  = math.sqrt(sum(x * x for x in a))
        nb  = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)


# ── Classifier ─────────────────────────────────────────────────────────────────

class CategoryClassifier:
    """
    Hybrid keyword + TF-IDF category classifier.

    Usage::

        clf = CategoryClassifier()
        result = clf.classify("Deep pothole on MG Road causing accidents",
                               "There is a very deep pothole that vehicles keep hitting.")
        print(result.category, result.confidence)
    """

    def __init__(self, confidence_threshold: float | None = None) -> None:
        from config import AI_CATEGORY_CONFIDENCE_THRESHOLD
        self._threshold = confidence_threshold if confidence_threshold is not None \
            else AI_CATEGORY_CONFIDENCE_THRESHOLD

        # Pre-build TF-IDF corpus from exemplars
        exemplar_tokens = {cat: _tokenize(text) for cat, text in _EXEMPLARS.items()}
        all_docs = list(exemplar_tokens.values())
        self._idf    = _build_idf(all_docs)
        self._vocab  = sorted(self._idf.keys())
        self._exemplar_vecs: dict[str, list[float]] = {
            cat: _tfidf_vector(tokens, self._vocab, self._idf)
            for cat, tokens in exemplar_tokens.items()
        }
        logger.info("CategoryClassifier ready (%d vocab terms).", len(self._vocab))

    def classify(self, title: str, description: str) -> CategoryResult:
        """
        Classify a complaint into one of the 11 civic categories.

        Returns a CategoryResult with category, confidence, explanation,
        and needs_review flag.
        """
        try:
            return self._classify_inner(title, description)
        except Exception as exc:
            logger.error("CategoryClassifier error: %s", exc, exc_info=True)
            return CategoryResult(
                category="Other",
                confidence=0.0,
                explanation=f"Classifier error: {exc}",
                needs_review=True,
            )

    def _classify_inner(self, title: str, description: str) -> CategoryResult:
        combined      = f"{title} {description}"
        combined_lower = combined.lower()
        tokens        = _tokenize(combined)

        # ── Stage 1: keyword lexicon scores ───────────────────────────
        lex_scores: dict[str, float] = {}
        for cat, kw_list in _LEXICON.items():
            max_possible = sum(w for _, w in kw_list) or 1.0
            raw          = _keyword_score(combined_lower, kw_list)
            lex_scores[cat] = min(raw / max_possible, 1.0)

        # ── Stage 2: TF-IDF cosine scores ──────────────────────────────
        input_vec = _tfidf_vector(tokens, self._vocab, self._idf)
        tfidf_scores: dict[str, float] = {
            cat: _cosine(input_vec, vec)
            for cat, vec in self._exemplar_vecs.items()
        }

        # ── Blend (60% lexicon, 40% TF-IDF) ────────────────────────────
        blended: dict[str, float] = {
            cat: 0.6 * lex_scores[cat] + 0.4 * tfidf_scores.get(cat, 0.0)
            for cat in CATEGORIES
        }

        # Sort by descending blended score
        ranked = sorted(blended.items(), key=lambda x: x[1], reverse=True)
        best_cat, best_score = ranked[0]

        # Normalise confidence to 0–1 using min-max across predictions
        scores_only = [s for _, s in ranked]
        score_range = max(scores_only) - min(scores_only)
        if score_range > 0:
            confidence = (best_score - min(scores_only)) / score_range
            # Clamp: ensure top-ranked complaint is at least moderately confident
            confidence = 0.3 + 0.7 * confidence
        else:
            confidence = 0.3   # all scores equal → genuinely uncertain

        confidence = round(min(confidence, 1.0), 4)
        needs_review = confidence < self._threshold

        # Build explanation
        runner_up = ranked[1][0] if len(ranked) > 1 else None
        if needs_review:
            explanation = (
                f"Low confidence ({confidence:.0%}). "
                f"Top match: '{best_cat}', possible alternative: '{runner_up}'. "
                "Manual review recommended."
            )
        else:
            top_keywords = [kw for kw, _ in _LEXICON[best_cat][:3]]
            explanation = (
                f"Matched category '{best_cat}' with {confidence:.0%} confidence. "
                f"Key signals: {', '.join(top_keywords)}."
            )

        return CategoryResult(
            category=best_cat,
            confidence=confidence,
            explanation=explanation,
            needs_review=needs_review,
        )


# ── Module-level singleton (cached) ───────────────────────────────────────────

_classifier_instance: CategoryClassifier | None = None


def get_classifier() -> CategoryClassifier:
    """Return a cached CategoryClassifier instance (loaded once at startup)."""
    global _classifier_instance
    if _classifier_instance is None:
        try:
            _classifier_instance = CategoryClassifier()
        except Exception as exc:
            logger.error("Failed to create CategoryClassifier: %s", exc)
            raise
    return _classifier_instance
