"""
config.py – CivicAI Application Configuration
All tuneable settings live here. No secret credentials are hardcoded.
"""

import os

# ── Base paths ────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_DIR  = os.path.join(BASE_DIR, "database")
DATABASE_PATH = os.path.join(DATABASE_DIR, "civicai.db")

# ── File uploads ──────────────────────────────────────────────────────────────
UPLOAD_DIR            = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS    = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_IMAGE_SIZE_BYTES  = 5 * 1024 * 1024   # 5 MB

# ── Flask application settings ────────────────────────────────────────────────
# SECRET_KEY should be overridden via environment variable in production.
SECRET_KEY       = os.environ.get("CIVICAI_SECRET_KEY", "dev-secret-change-in-production")
DEBUG            = os.environ.get("CIVICAI_DEBUG", "true").lower() == "true"
HOST             = os.environ.get("CIVICAI_HOST", "127.0.0.1")
PORT             = int(os.environ.get("CIVICAI_PORT", "5000"))

# ── Complaint settings ────────────────────────────────────────────────────────
COMPLAINT_ID_PREFIX  = "CMP"
COMPLAINT_CATEGORIES = [
    "Road Damage",
    "Waterlogging",
    "Garbage Overflow",
    "Streetlight",
    "Drainage",
    "Public Safety",
    "Water Supply",
    "Sewage",
    "Tree / Vegetation",
    "Noise Pollution",
    "Other",
]

PRIORITY_LEVELS = ["Low", "Medium", "High", "Critical"]

COMPLAINT_STATUSES = [
    "Submitted",
    "Under Review",
    "Assigned",
    "In Progress",
    "Resolved",
    "Closed",
    "Rejected",
]

# ── AI settings ───────────────────────────────────────────────────────────────

# Duplicate detection: blended four-signal threshold (0.0 – 1.0)
# Signals: title 50%, description 30%, category 10%, geo proximity 10%.
# 0.60 catches identical-title complaints with different descriptions.
AI_SIMILARITY_THRESHOLD = 0.60

# Categorisation: minimum confidence for auto-accept (0.0 – 1.0)
# Predictions below this value set needs_review=True.
AI_CATEGORY_CONFIDENCE_THRESHOLD = 0.55

# Hotspot detection
AI_HOTSPOT_RADIUS_KM        = 0.5    # cluster radius in km
AI_HOTSPOT_MIN_COMPLAINTS   = 3      # minimum complaints to declare a hotspot

# Priority scoring thresholds (Phase 3C)
AI_PRIORITY_CRITICAL_MIN    = 75     # score >= 75 → Critical
AI_PRIORITY_HIGH_MIN        = 50     # score >= 50 → High
AI_PRIORITY_MEDIUM_MIN      = 25     # score >= 25 → Medium
# score < 25 → Low

# Action brief settings (Phase 3E)
AI_BRIEF_MAX_STEPS          = 5      # max recommended steps in a brief

# ── Admin authentication (Phase 4D) ──────────────────────────────────────────
# ADMIN_AUTH_MODE controls how /admin/* routes are protected.
#   "open"     – no authentication required (local dev only)
#   "password" – HTTP Basic Auth using CIVICAI_ADMIN_PASSWORD env var
#   "disabled" – admin routes return 503 (maintenance / lockdown)
# The application refuses to start in "password" mode if the env var is empty.
ADMIN_AUTH_MODE     = os.environ.get("CIVICAI_ADMIN_AUTH_MODE", "open")
ADMIN_PASSWORD      = os.environ.get("CIVICAI_ADMIN_PASSWORD", "")

# ── Dashboard pagination (Phase 4E) ──────────────────────────────────────────
# Maximum complaints shown per page on the admin dashboard.
DASHBOARD_PAGE_SIZE = int(os.environ.get("CIVICAI_PAGE_SIZE", "100"))
