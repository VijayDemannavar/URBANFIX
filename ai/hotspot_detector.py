"""
ai/hotspot_detector.py – CivicAI Geographic Hotspot Detection Module
Phase 3D implementation.

ALGORITHM
─────────
DBSCAN-style spatial clustering using Haversine distance.

  1. Filter complaints: keep only rows with valid, finite latitude/longitude.
     Valid means: isinstance float/int, math.isfinite, lat in [-90,90],
     lon in [-180,180].
  2. For each unvisited point P:
     a. Compute P's neighbourhood (all points within radius_km of P).
     b. If |neighbourhood| < min_complaints  → mark as noise, continue.
     c. Start a new cluster seeded with P and its neighbours.
     d. For each unprocessed neighbour Q in the queue:
        – Compute Q's neighbourhood.
        – If |Q-neighbourhood| >= min_complaints, merge Q's neighbours
          into the current cluster's expansion queue.
        – Mark Q as a cluster member regardless.
     e. Once the queue is exhausted, emit the cluster.
  3. For each cluster, compute:
     – Geometric centre (arithmetic mean of lat / lon).
     – Dominant category (Counter, most common wins).
     – critical_count: members where priority_level == 'Critical'.
     – high_count:     members where priority_level == 'High'.
     – avg_priority_score: arithmetic mean of priority_score values.

No paid APIs. No model downloads. Pure Python + math + collections.
"""

from __future__ import annotations

import math
import logging
from collections import Counter
from typing import NamedTuple

logger = logging.getLogger(__name__)


# ── Result type ────────────────────────────────────────────────────────────────

class Hotspot(NamedTuple):
    center_lat:         float
    center_lon:         float
    complaint_ids:      list        # list[str]
    count:              int
    dominant_category:  str
    radius_km:          float
    critical_count:     int
    high_count:         int
    avg_priority_score: float


# ── Haversine distance (kept from original stub) ───────────────────────────────

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great-circle distance in kilometres between two coordinates.
    """
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


# ── Coordinate validation ──────────────────────────────────────────────────────

def _is_valid_coord(lat, lon) -> bool:
    """
    Return True only when both lat and lon are finite numeric values within
    valid geographic ranges:
        latitude  : -90.0  ≤ lat ≤  90.0
        longitude : -180.0 ≤ lon ≤ 180.0
    Rejects None, non-numeric types, NaN, and ±Inf.
    """
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return False
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return False
    if not (-90.0 <= lat <= 90.0):
        return False
    if not (-180.0 <= lon <= 180.0):
        return False
    return True


# ── Engine class ───────────────────────────────────────────────────────────────

class HotspotDetector:
    """
    Identifies geographic clusters of complaints (hotspots) using a
    DBSCAN-style radius expansion algorithm with Haversine distance.

    Instantiate once via get_hotspot_detector(); call detect() as needed.
    """

    def __init__(self, radius_km: float | None = None,
                 min_complaints: int | None = None) -> None:
        from config import AI_HOTSPOT_RADIUS_KM, AI_HOTSPOT_MIN_COMPLAINTS
        self.radius_km      = radius_km      if radius_km      is not None else AI_HOTSPOT_RADIUS_KM
        self.min_complaints = min_complaints if min_complaints is not None else AI_HOTSPOT_MIN_COMPLAINTS
        logger.info(
            "HotspotDetector ready (radius=%.2f km, min_complaints=%d).",
            self.radius_km, self.min_complaints,
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    def detect(self, complaints: list[dict]) -> list[Hotspot]:
        """
        Run DBSCAN-lite clustering on a list of complaint dicts.

        Each dict must contain at minimum:
            complaint_id  (str)
            latitude      (float | None)
            longitude     (float | None)
            category      (str)

        Optional (used for priority statistics):
            priority_level  (str)   – 'Critical' | 'High' | 'Medium' | 'Low'
            priority_score  (float) – 0.0 – 100.0

        Returns:
            List of Hotspot NamedTuples, ordered by cluster size descending.
        """
        # ── 1. Filter to valid coordinates ─────────────────────────────────
        valid = [
            c for c in complaints
            if _is_valid_coord(c.get("latitude"), c.get("longitude"))
        ]

        if len(valid) < self.min_complaints:
            return []

        # Sort for deterministic output across runs
        valid.sort(key=lambda c: c.get("complaint_id", ""))

        n = len(valid)

        # ── 2. Pre-compute neighbourhoods for every point ───────────────────
        # neighbourhoods[i] = set of indices within radius_km of point i
        neighbourhoods: list[set[int]] = []
        for i, pi in enumerate(valid):
            nbrs: set[int] = set()
            for j, pj in enumerate(valid):
                if i != j:
                    d = haversine_km(
                        pi["latitude"], pi["longitude"],
                        pj["latitude"], pj["longitude"],
                    )
                    if d <= self.radius_km:
                        nbrs.add(j)
            neighbourhoods.append(nbrs)

        # ── 3. DBSCAN expansion ─────────────────────────────────────────────
        visited   = [False] * n   # processed as cluster member or noise
        in_cluster = [-1] * n     # cluster label (-1 = noise / unassigned)
        clusters: list[list[int]] = []

        for i in range(n):
            if visited[i]:
                continue

            nbrs = neighbourhoods[i]
            if len(nbrs) + 1 < self.min_complaints:
                # Point i cannot seed a cluster; mark as noise for now
                visited[i] = True
                continue

            # Start a new cluster
            cluster_idx = len(clusters)
            clusters.append([])

            # Seed with point i
            visited[i]    = True
            in_cluster[i] = cluster_idx
            clusters[cluster_idx].append(i)

            # Expansion queue (indices to process)
            queue = list(nbrs)
            queued = set(nbrs)  # avoid duplicates in queue

            while queue:
                j = queue.pop(0)
                if not visited[j]:
                    visited[j]    = True
                    in_cluster[j] = cluster_idx
                    clusters[cluster_idx].append(j)

                    j_nbrs = neighbourhoods[j]
                    if len(j_nbrs) + 1 >= self.min_complaints:
                        # Q is a core point; merge its neighbours into queue
                        for k in j_nbrs:
                            if not visited[k] and k not in queued:
                                queue.append(k)
                                queued.add(k)
                elif in_cluster[j] == -1:
                    # Border point: assign to this cluster even if visited
                    in_cluster[j] = cluster_idx
                    clusters[cluster_idx].append(j)

        # ── 4. Build Hotspot objects ────────────────────────────────────────
        hotspots: list[Hotspot] = []

        for members in clusters:
            if len(members) < self.min_complaints:
                continue  # noise cluster

            pts = [valid[i] for i in members]

            center_lat = sum(p["latitude"]  for p in pts) / len(pts)
            center_lon = sum(p["longitude"] for p in pts) / len(pts)

            complaint_ids = [p["complaint_id"] for p in pts]

            categories    = [p.get("category", "Other") for p in pts]
            dominant_cat  = Counter(categories).most_common(1)[0][0]

            critical_count = sum(
                1 for p in pts if p.get("priority_level") == "Critical"
            )
            high_count = sum(
                1 for p in pts if p.get("priority_level") == "High"
            )

            scores = [
                float(p["priority_score"])
                for p in pts
                if p.get("priority_score") is not None
            ]
            avg_score = sum(scores) / len(scores) if scores else 0.0

            hotspots.append(Hotspot(
                center_lat         = round(center_lat, 6),
                center_lon         = round(center_lon, 6),
                complaint_ids      = complaint_ids,
                count              = len(pts),
                dominant_category  = dominant_cat,
                radius_km          = self.radius_km,
                critical_count     = critical_count,
                high_count         = high_count,
                avg_priority_score = round(avg_score, 2),
            ))

        hotspots.sort(key=lambda h: h.count, reverse=True)
        logger.info("HotspotDetector: found %d hotspot(s) from %d geo-located complaints.",
                    len(hotspots), len(valid))
        return hotspots


# ── Module-level singleton ─────────────────────────────────────────────────────

_detector_instance: HotspotDetector | None = None


def get_hotspot_detector() -> HotspotDetector:
    """Return a cached HotspotDetector instance."""
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = HotspotDetector()
    return _detector_instance
