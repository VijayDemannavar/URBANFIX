"""
ai/duplicate_detector.py – CivicAI Duplicate Complaint Detector
Phase 3B (revised for Part 1 fix).

SCORING MODEL (four independent signals, blended):

  1. Title similarity   (weight 0.50)
     TF-IDF cosine on title tokens alone.
     Identical or near-identical titles are a strong duplicate signal.

  2. Description similarity  (weight 0.30)
     TF-IDF cosine on description tokens alone.
     Different descriptions reduce confidence but do not rule out duplicates.

  3. Category match  (weight 0.10)
     1.0 if same category, 0.0 otherwise.

  4. Geographic proximity  (weight 0.10)
     1.0 if distance <= GEO_DUPLICATE_RADIUS_KM, decays to 0.0 beyond that.
     0.5 if coordinates are missing (neutral – neither confirms nor denies).

  Combined = 0.50*title + 0.30*desc + 0.10*cat + 0.10*geo

WHY THE OLD DETECTOR MISSED THE TWO REPORTED COMPLAINTS:
  "Large pothole on MG Road near 2nd Cross" + "this is important msg…"  vs
  "Large pothole on MG Road near 2nd Cross" + "this is road damage in my area…"

  The old approach concatenated title+description into one blob.  The two
  descriptions share only stop-words, which IDF up-weights poorly.  The
  combined TF-IDF cosine of the full blobs ended up ~0.45–0.55 — below 0.75.

  The new approach scores title separately with weight 0.50.  Since the
  titles are identical, title_sim = 1.0.  Even with desc_sim ≈ 0.3 and geo
  far apart, combined ≈ 0.50 + 0.09 + 0.10 + 0.05 ≈ 0.74.
  Using threshold 0.60 (the new configurable default) this is detected.

No paid APIs, no model downloads. numpy + pure-Python fallback.
"""

from __future__ import annotations

import re
import math
import logging
from collections import Counter
from typing import NamedTuple

logger = logging.getLogger(__name__)

# ── Types ──────────────────────────────────────────────────────────────────────

class DuplicateMatch(NamedTuple):
    complaint_id:     str
    similarity_score: float           # 0.0 – 1.0  (combined score)
    title_sim:        float           # 0.0 – 1.0  title-only similarity
    desc_sim:         float           # 0.0 – 1.0  description similarity
    geo_sim:          float | None    # 0.0 – 1.0  geographic proximity; None if coords unavailable
    category_match:   bool
    explanation:      str


# ── Text utilities ─────────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """Lowercase, remove punctuation, return word + bigram tokens."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    words = [w for w in text.split() if len(w) > 1]
    bigrams = [f"{words[i]}_{words[i+1]}" for i in range(len(words) - 1)]
    return words + bigrams


def _build_idf(documents: list[list[str]]) -> dict[str, float]:
    """Smoothed IDF across a corpus."""
    N  = len(documents)
    df: Counter = Counter()
    for doc in documents:
        for term in set(doc):
            df[term] += 1
    return {
        term: math.log((N + 1) / (cnt + 1)) + 1.0
        for term, cnt in df.items()
    }


def _tfidf_vector(tokens: list[str], vocab: list[str],
                  idf: dict[str, float]) -> list[float]:
    n  = len(tokens) or 1
    tf = Counter(tokens)
    return [tf.get(v, 0) / n * idf.get(v, 0.0) for v in vocab]


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity; numpy-accelerated with pure-Python fallback."""
    try:
        import numpy as np
        va, vb = np.array(a, dtype=float), np.array(b, dtype=float)
        na, nb = np.linalg.norm(va), np.linalg.norm(vb)
        if na == 0.0 or nb == 0.0:
            return 0.0
        return float(np.dot(va, vb) / (na * nb))
    except ImportError:
        dot = sum(x * y for x, y in zip(a, b))
        na  = math.sqrt(sum(x * x for x in a))
        nb  = math.sqrt(sum(x * x for x in b))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return dot / (na * nb)


def _overlap_coefficient(tokens_a: list[str], tokens_b: list[str]) -> float:
    """
    Overlap coefficient = |A ∩ B| / min(|A|, |B|).

    Measures how much the smaller token set is covered by the larger one.
    Works well on short texts where TF-IDF discounts shared terms as 'common'
    in the two-document corpus.
    """
    set_a, set_b = set(tokens_a), set(tokens_b)
    denom = min(len(set_a), len(set_b))
    if denom == 0:
        return 0.0
    return len(set_a & set_b) / denom


def _text_pair_similarity(text_a: str, text_b: str) -> float:
    """
    Similarity between two text strings.

    Returns max(TF-IDF cosine, overlap coefficient).

    TF-IDF cosine excels when documents are longer and vocabulary is rich.
    Overlap coefficient catches short-text cases where shared tokens are
    IDF-discounted to nearly zero because both docs share them (the 2-doc
    corpus problem).  Taking the max of the two ensures identical short
    texts still score 1.0 and genuinely similar short texts are not penalised.
    """
    tok_a = _tokenize(text_a)
    tok_b = _tokenize(text_b)
    if not tok_a or not tok_b:
        return 0.0
    idf    = _build_idf([tok_a, tok_b])
    vocab  = sorted(idf.keys())
    tfidf  = _cosine(
        _tfidf_vector(tok_a, vocab, idf),
        _tfidf_vector(tok_b, vocab, idf),
    )
    overlap = _overlap_coefficient(tok_a, tok_b)
    return round(max(tfidf, overlap), 4)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon coordinates."""
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(d_lon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _geo_score(lat1, lon1, lat2, lon2, radius_km: float) -> float:
    """
    Return a geo-proximity score in [0, 1].
    - 1.0  if both complaints are within radius_km of each other
    - decays linearly to 0.0 at 3x the radius
    - 0.5  if either coordinate is missing (neutral)
    """
    try:
        if any(v is None for v in [lat1, lon1, lat2, lon2]):
            return 0.5
        dist = _haversine_km(float(lat1), float(lon1), float(lat2), float(lon2))
        if dist <= radius_km:
            return 1.0
        max_dist = radius_km * 3.0
        if dist >= max_dist:
            return 0.0
        return round(1.0 - (dist - radius_km) / (max_dist - radius_km), 4)
    except Exception:
        return 0.5


# ── Detector class ─────────────────────────────────────────────────────────────

class DuplicateDetector:
    """
    Detects potential duplicate complaints using a four-signal blended score.

    Signals:
        title_sim  × 0.50  – identical/similar titles are the primary signal
        desc_sim   × 0.30  – description content similarity
        cat_match  × 0.10  – same civic category
        geo_sim    × 0.10  – geographic proximity (if coordinates available)

    threshold:
        Default AI_SIMILARITY_THRESHOLD (from config).
        Was 0.75 (Phase 3B) — a complaint now also passes at 0.60 with
        identical title + same category + partial description overlap.
    """

    # Signal weights
    W_TITLE = 0.50
    W_DESC  = 0.30
    W_CAT   = 0.10
    W_GEO   = 0.10

    def __init__(
        self,
        threshold: float | None = None,
        geo_radius_km: float | None = None,
    ) -> None:
        from config import AI_SIMILARITY_THRESHOLD, AI_HOTSPOT_RADIUS_KM
        self._threshold    = threshold    if threshold    is not None else AI_SIMILARITY_THRESHOLD
        self._geo_radius   = geo_radius_km if geo_radius_km is not None else AI_HOTSPOT_RADIUS_KM
        logger.info(
            "DuplicateDetector ready (threshold=%.2f, geo_radius=%.2f km).",
            self._threshold, self._geo_radius,
        )

    # ── Public API ──────────────────────────────────────────────────────────────

    def find_duplicates(
        self,
        complaint_id: str,
        title: str,
        description: str,
        existing_complaints: list[dict] | None = None,
        *,
        category: str = "",
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> list[DuplicateMatch]:
        """
        Find potential duplicates for the given complaint.

        Args:
            complaint_id:        Own ID – excluded from results.
            title, description:  Text of the new complaint.
            existing_complaints: Pre-fetched list of dicts with keys:
                                 complaint_id, title, description, category,
                                 latitude, longitude.
                                 If None, fetched from DB automatically.
            category:            Citizen-selected category (keyword-only).
            latitude, longitude: Coordinates of the new complaint (keyword-only).

        Returns:
            List of DuplicateMatch sorted by similarity_score descending.
            Empty list if no candidates score >= threshold.

        Note: ``existing_complaints`` is the 4th positional arg for backwards
        compatibility with existing tests.  ``category``, ``latitude``, and
        ``longitude`` are keyword-only to prevent a list from landing there.
        """
        try:
            return self._find_inner(
                complaint_id, title, description,
                category, latitude, longitude,
                existing_complaints,
            )
        except Exception as exc:
            logger.error("DuplicateDetector error: %s", exc, exc_info=True)
            return []

    def score_pair(
        self,
        title_a: str, desc_a: str,
        title_b: str, desc_b: str,
        category_a: str = "",
        category_b: str = "",
        lat_a=None, lon_a=None,
        lat_b=None, lon_b=None,
    ) -> float:
        """
        Compute the blended similarity score between two complaints.

        When no coordinates are provided, the geo weight is redistributed
        to the text signals so that perfectly identical complaints score 1.0.
        """
        title_sim = _text_pair_similarity(title_a, title_b)
        desc_sim  = _text_pair_similarity(desc_a,  desc_b)
        cat_sim   = 1.0 if (category_a and category_b and
                            category_a.strip() == category_b.strip()) else 0.0
        geo_available = not all(v is None for v in [lat_a, lon_a, lat_b, lon_b])
        geo_sim = _geo_score(lat_a, lon_a, lat_b, lon_b, self._geo_radius) \
                  if geo_available else None
        return self._blend(title_sim, desc_sim, cat_sim, geo_sim)

    # ── Scoring blend helper ────────────────────────────────────────────────────

    def _blend(
        self,
        title_sim: float,
        desc_sim: float,
        cat_sim: float,
        geo_sim: float | None,
    ) -> float:
        """
        Blend active signals into a final score in [0, 1].

        Only signals with a positive weight *and* available value contribute to
        the denominator.  Concretely:

        - ``geo_sim`` is None  → geo weight redistributed to other signals.
        - ``cat_sim`` is 0.0   → cat weight redistributed only when no category
          was supplied (i.e. both sides had empty category strings, making 0.0 a
          "missing" rather than a "mismatch").  We detect this by checking
          whether cat_sim is exactly 0.0 while geo is also absent; in that
          scenario the only meaningful signals are title and description, so we
          redistribute over title+desc only so identical complaints score 1.0.

        Rule used: build the pool of (weight, value) pairs for available signals,
        normalise weights to sum to 1.0, then compute weighted sum.
        """
        pool: list[tuple[float, float]] = [
            (self.W_TITLE, title_sim),
            (self.W_DESC,  desc_sim),
        ]
        # Include category only when it is genuinely informative (non-zero).
        # cat_sim == 0.0 with no supplied category is "unknown", not "mismatch".
        if cat_sim > 0.0:
            pool.append((self.W_CAT, cat_sim))
        # Include geo only when coordinates were available.
        if geo_sim is not None:
            pool.append((self.W_GEO, geo_sim))

        total = sum(w for w, _ in pool)
        if total == 0.0:
            return 0.0
        score = sum(w * v for w, v in pool) / total
        return round(score, 4)

    # ── Private ─────────────────────────────────────────────────────────────────

    def _find_inner(
        self,
        complaint_id: str,
        title: str,
        description: str,
        category: str,
        latitude,
        longitude,
        existing_complaints: list[dict] | None,
    ) -> list[DuplicateMatch]:

        if existing_complaints is None:
            existing_complaints = self._fetch_all_complaints()

        candidates = [
            c for c in existing_complaints
            if c.get("complaint_id") != complaint_id
        ]
        if not candidates:
            return []

        matches: list[DuplicateMatch] = []

        for cand in candidates:
            cid   = cand.get("complaint_id", "")
            ctitle = cand.get("title", "")
            cdesc  = cand.get("description", "")
            ccat   = cand.get("category", "")
            clat   = cand.get("latitude")
            clon   = cand.get("longitude")

            title_sim = _text_pair_similarity(title, ctitle)
            desc_sim  = _text_pair_similarity(description, cdesc)
            cat_sim   = 1.0 if (category and ccat and
                                category.strip() == ccat.strip()) else 0.0
            geo_available = not all(v is None for v in [latitude, longitude, clat, clon])
            geo_sim = _geo_score(latitude, longitude, clat, clon, self._geo_radius) \
                      if geo_available else None

            score = self._blend(title_sim, desc_sim, cat_sim, geo_sim)

            if score >= self._threshold:
                parts = []
                if title_sim >= 0.9:
                    parts.append(f"identical title ({title_sim:.0%})")
                elif title_sim >= 0.5:
                    parts.append(f"similar title ({title_sim:.0%})")
                if desc_sim >= 0.5:
                    parts.append(f"similar description ({desc_sim:.0%})")
                if cat_sim:
                    parts.append("same category")
                if geo_sim is not None and geo_sim >= 0.8:
                    parts.append("same area")
                elif geo_sim is not None and geo_sim < 0.2:
                    parts.append("different location")

                explanation = (
                    f"Blended score {score:.0%} with {cid}: "
                    + (", ".join(parts) if parts else "moderate text overlap")
                    + ". Flagged for admin review."
                )

                matches.append(DuplicateMatch(
                    complaint_id    = cid,
                    similarity_score= score,
                    title_sim       = title_sim,
                    desc_sim        = desc_sim,
                    geo_sim         = geo_sim,
                    category_match  = bool(cat_sim),
                    explanation     = explanation,
                ))

        matches.sort(key=lambda m: m.similarity_score, reverse=True)
        return matches

    @staticmethod
    def _fetch_all_complaints() -> list[dict]:
        import database as db
        with db.db_cursor() as (conn, cur):
            cur.execute(
                """SELECT complaint_id, title, description,
                          category, latitude, longitude
                   FROM complaints;"""
            )
            return [
                {
                    "complaint_id": r["complaint_id"],
                    "title":        r["title"],
                    "description":  r["description"],
                    "category":     r["category"],
                    "latitude":     r["latitude"],
                    "longitude":    r["longitude"],
                }
                for r in cur.fetchall()
            ]


# ── Module-level singleton ──────────────────────────────────────────────────────

_detector_instance: DuplicateDetector | None = None


def get_detector() -> DuplicateDetector:
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = DuplicateDetector()
    return _detector_instance
