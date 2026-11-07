"""
routes/admin.py – CivicAI Admin Dashboard Blueprint

Routes:
  GET  /admin                                     → dashboard with stats + complaint table
  GET  /admin/complaint/<complaint_id>            → complaint detail page
  POST /admin/complaint/<complaint_id>/update     → update status + assignment (Phase 4B)
  POST /admin/complaint/<complaint_id>/add_note   → add action note (Phase 4B)
  GET  /admin/hotspots                            → geographic hotspot map (Phase 3D)

Authentication (Phase 4D):
  Controlled by config.ADMIN_AUTH_MODE:
    "open"     – no credentials required (development)
    "password" – HTTP Basic Auth via CIVICAI_ADMIN_PASSWORD env var
    "disabled" – all routes return 503
"""

import base64
from collections import defaultdict
import csv
import hmac
import io
import logging
import os
import time

import sqlite3

from flask import (
    Blueprint, render_template, request, abort,
    redirect, url_for, flash, current_app, Response,
    session,
)
from ai.hotspot_detector import get_hotspot_detector

import database as db
from config import (
    COMPLAINT_CATEGORIES, COMPLAINT_STATUSES, PRIORITY_LEVELS,
    ADMIN_AUTH_MODE, ADMIN_PASSWORD, ADMIN_USERNAME, DASHBOARD_PAGE_SIZE,
    UPLOAD_DIR,
)
from routes.csrf import verify_csrf

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ── Admin Login Rate Limiting ────────────────────────────────────────────────
_FAILED_LOGINS = defaultdict(list)
_MAX_LOGIN_FAILURES = 5
_LOCKOUT_SECONDS = 60
_WINDOW_SECONDS = 300


def _get_client_ip() -> str:
    if request.headers.get("X-Forwarded-For"):
        return request.headers.get("X-Forwarded-For").split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"


def _is_login_rate_limited(ip: str) -> bool:
    now = time.time()
    recent = [t for t in _FAILED_LOGINS[ip] if now - t < _WINDOW_SECONDS]
    _FAILED_LOGINS[ip] = recent
    if len(recent) >= _MAX_LOGIN_FAILURES:
        if recent and (now - recent[-1] < _LOCKOUT_SECONDS):
            return True
    return False


def _record_failed_login(ip: str) -> None:
    _FAILED_LOGINS[ip].append(time.time())


def _clear_failed_logins(ip: str) -> None:
    _FAILED_LOGINS.pop(ip, None)


# ── Admin authentication & Authorization ─────────────────────────────────────

def _check_admin_auth():
    """
    Enforce admin authentication, CSRF validation on writes, and demo permissions.
    """
    exempt_endpoints = {"admin.login", "admin.demo_login", "admin.logout"}
    if request.endpoint in exempt_endpoints:
        return None

    # Defense-in-depth: Reject forged state-changing requests early with 403
    if request.method not in ("GET", "HEAD", "OPTIONS") and not verify_csrf():
        abort(403, description="CSRF token missing or invalid.")

    # Demo Mode enforcement: read-only access for all GET/HEAD/OPTIONS
    if session.get("is_demo"):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            logger.warning(
                "Demo account '%s' blocked from write action: %s %s",
                session.get("admin_user", "demo"), request.method, request.path
            )
            abort(403, description="Demo mode is read-only. Data modifications are disabled.")
        return None

    # Authenticated Administrator session
    if session.get("admin_logged_in"):
        return None

    # Basic Auth header (for backward compatibility and test suites)
    expected_password = current_app.config.get("ADMIN_PASSWORD", ADMIN_PASSWORD)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8", errors="replace")
            _user, _, supplied = decoded.partition(":")
            if expected_password and hmac.compare_digest(supplied, expected_password):
                return None  # authenticated via HTTP Basic Auth
        except Exception:
            pass

    # Bypass in test mode when not testing demo mode
    if current_app.config.get("TESTING"):
        return None

    mode = current_app.config.get("ADMIN_AUTH_MODE", ADMIN_AUTH_MODE)

    if mode == "disabled":
        abort(503)

    if mode == "password":
        # Legacy password mode challenges with HTTP 401 WWW-Authenticate
        from flask import make_response
        resp = make_response("Admin authentication required.", 401)
        resp.headers["WWW-Authenticate"] = 'Basic realm="CivicAI Admin"'
        abort(resp)

    if mode == "open":
        return None

    # Default "session" mode:
    # If unauthenticated non-safe request (POST/PUT/DELETE): reject with 403 Forbidden
    # (Note: unauthenticated requests with valid CSRF token but no admin session are redirected)
    # Redirect unauthenticated visitor to login page
    flash("Please log in or explore using the demo account.", "warning")
    next_url = request.full_path if request.query_string else request.path
    if not next_url or next_url.startswith("/admin/login") or next_url.startswith("/admin/logout") or next_url.startswith("/admin/demo"):
        next_url = url_for("admin.dashboard")
    return redirect(url_for("admin.login", next=next_url))


@admin_bp.before_request
def _admin_auth_before_request():
    return _check_admin_auth()


# ── Authentication & Demo Routes ──────────────────────────────────────────────

@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    Administrator portal login page and credential verification.
    """
    next_url = request.args.get("next") or request.form.get("next") or url_for("admin.dashboard")
    if not next_url.startswith("/") or next_url.startswith("//") or next_url.startswith("/admin/login") or next_url.startswith("/admin/logout"):
        next_url = url_for("admin.dashboard")

    # If already logged in as admin (non-demo), redirect directly
    if session.get("admin_logged_in") and not session.get("is_demo"):
        return redirect(next_url)

    if request.method == "POST":
        if not verify_csrf():
            flash("Security token missing or invalid. Please try again.", "error")
            return render_template("admin/login.html", next_url=next_url), 400

        ip = _get_client_ip()
        if _is_login_rate_limited(ip):
            flash("Too many failed login attempts. Please wait 60 seconds before trying again.", "error")
            return render_template("admin/login.html", next_url=next_url, username=request.form.get("username", "")), 429

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        expected_user = current_app.config.get("ADMIN_USERNAME", ADMIN_USERNAME)
        expected_pw   = current_app.config.get("ADMIN_PASSWORD", ADMIN_PASSWORD)

        if not expected_pw:
            _record_failed_login(ip)
            flash("Administrator login is not configured with a password in this environment. You can explore using the Demo Account below.", "error")
            return render_template("admin/login.html", next_url=next_url, username=username), 401

        if username == expected_user and hmac.compare_digest(password, expected_pw):
            _clear_failed_logins(ip)
            session["admin_logged_in"] = True
            session["is_demo"] = False
            session["admin_user"] = username
            flash(f"Welcome back, {username}! Administrator session active.", "success")
            return redirect(next_url)
        else:
            _record_failed_login(ip)
            flash("Invalid username or password. Please verify your credentials.", "error")
            return render_template("admin/login.html", next_url=next_url, username=username), 401

    return render_template("admin/login.html", next_url=next_url)


@admin_bp.route("/demo", methods=["GET", "POST"])
def demo_login():
    """
    Activate one-click read-only demo session without requiring credentials.
    """
    session["admin_logged_in"] = True
    session["is_demo"] = True
    session["admin_user"] = "Demo Reviewer"
    flash("Welcome to Demo Mode! You have read-only access to explore reports, maps, and analytics.", "info")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/logout", methods=["GET", "POST"])
def logout():
    """
    Terminate admin or demo session and redirect to login page.
    """
    session.pop("admin_logged_in", None)
    session.pop("is_demo", None)
    session.pop("admin_user", None)
    flash("You have been signed out.", "info")
    return redirect(url_for("admin.login"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_global_stats() -> dict:
    """
    Compute global summary statistics directly from the database.
    Always reflects total counts across ALL complaints — independent of
    the current page / filter so the stat cards are always accurate.
    """
    with db.db_cursor() as (conn, cur):
        cur.execute(
            """SELECT
                 COUNT(*)                                          AS total,
                 SUM(status = 'Submitted')                        AS submitted,
                 SUM(status = 'Under Review')                     AS under_review,
                 SUM(status = 'Assigned')                         AS assigned,
                 SUM(status = 'In Progress')                      AS in_progress,
                 SUM(status = 'Resolved')                         AS resolved,
                 SUM(status = 'Closed')                           AS closed,
                 SUM(status = 'Rejected')                         AS rejected,
                 SUM(priority_level = 'Critical')                 AS critical
               FROM complaints;"""
        )
        row = cur.fetchone()
        if row is None:
            return {k: 0 for k in ("total", "submitted", "under_review",
                                   "assigned", "in_progress", "resolved",
                                   "closed", "rejected", "critical")}
        return {
            "total":        row["total"]        or 0,
            "submitted":    row["submitted"]    or 0,
            "under_review": row["under_review"] or 0,
            "assigned":     row["assigned"]     or 0,
            "in_progress":  row["in_progress"]  or 0,
            "resolved":     row["resolved"]     or 0,
            "closed":       row["closed"]       or 0,
            "rejected":     row["rejected"]     or 0,
            "critical":     row["critical"]     or 0,
        }


def _get_department(department_id: int | None) -> sqlite3.Row | None:
    if not department_id:
        return None
    with db.db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM departments WHERE id = ?;", (department_id,))
        return cur.fetchone()


def _get_officer(officer_id: int | None) -> sqlite3.Row | None:
    if not officer_id:
        return None
    with db.db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM officers WHERE id = ?;", (officer_id,))
        return cur.fetchone()


def _get_status_history(complaint_id: str) -> list:
    with db.db_cursor() as (conn, cur):
        cur.execute(
            """SELECT * FROM status_history
               WHERE complaint_id = ?
               ORDER BY changed_at ASC;""",
            (complaint_id,),
        )
        return cur.fetchall()


def _get_action_notes(complaint_id: str) -> list:
    with db.db_cursor() as (conn, cur):
        cur.execute(
            """SELECT * FROM action_notes
               WHERE complaint_id = ?
               ORDER BY created_at ASC;""",
            (complaint_id,),
        )
        return cur.fetchall()


def _get_duplicate_links(complaint_id: str) -> list:
    with db.db_cursor() as (conn, cur):
        cur.execute(
            """SELECT * FROM duplicate_links
               WHERE complaint_id = ?
               ORDER BY similarity_score DESC;""",
            (complaint_id,),
        )
        return cur.fetchall()


# ── Routes ────────────────────────────────────────────────────────────────────

@admin_bp.route("/")
def dashboard():
    """
    Admin dashboard with server-side pagination, search, filter, and sort.

    Query parameters (all optional):
        q         – search substring (complaint_id, title, address)
        category  – exact category name
        status    – exact status name
        priority  – exact priority level
        sort      – column key (complaint_id | title | category | address |
                                status | priority | submitted)
        order     – asc | desc
        page      – 1-based page number (default 1)
    """
    # ── Read and sanitise query params ────────────────────────────────
    search   = request.args.get("q",        "").strip()
    category = request.args.get("category", "").strip()
    status   = request.args.get("status",   "").strip()
    priority = request.args.get("priority", "").strip()
    sort     = request.args.get("sort",     "submitted").strip()
    order    = request.args.get("order",    "desc").strip().lower()
    if order not in ("asc", "desc"):
        order = "desc"

    # ── Pagination ────────────────────────────────────────────────────
    page_size = DASHBOARD_PAGE_SIZE
    try:
        page = int(request.args.get("page", 1))
    except (ValueError, TypeError):
        page = 1

    total_matching = db.count_complaints(
        search=search, category=category,
        status=status, priority=priority,
    )
    total_pages = max(1, -(-total_matching // page_size))   # ceiling division
    page        = max(1, min(page, total_pages))            # clamp to valid range

    complaints = db.get_complaints_page(
        page=page, page_size=page_size,
        search=search, category=category,
        status=status, priority=priority,
        sort=sort, order=order,
    )

    # Global stats always reflect all complaints (not just current page/filter)
    stats = _get_global_stats()

    return render_template(
        "admin/dashboard.html",
        complaints=complaints,
        stats=stats,
        categories=COMPLAINT_CATEGORIES,
        statuses=COMPLAINT_STATUSES,
        priority_levels=PRIORITY_LEVELS,
        # Pagination context
        page=page,
        total_pages=total_pages,
        total_matching=total_matching,
        page_size=page_size,
        # Active filter context (for preserving in pagination links)
        active_q=search,
        active_category=category,
        active_status=status,
        active_priority=priority,
        active_sort=sort,
        active_order=order,
    )


@admin_bp.route("/complaint/<complaint_id>")
def complaint_detail(complaint_id: str):
    """Show full details for a single complaint."""
    complaint = db.get_complaint_by_id(complaint_id)
    if complaint is None:
        abort(404)

    department      = _get_department(complaint["department_id"])
    officer         = _get_officer(complaint["assigned_officer"])
    status_history  = _get_status_history(complaint_id)
    action_notes    = _get_action_notes(complaint_id)
    duplicate_links = _get_duplicate_links(complaint_id)

    # Data needed by the write forms (Phase 4B)
    all_departments = db.get_all_departments()
    # Build a flat officer list for the assignment dropdown
    all_officers = []
    for dept in all_departments:
        all_officers.extend(db.get_officers_by_department(dept["id"]))

    # Phase 5: Intelligent Department Recommendation & Clarity Analysis
    dept_recommendation = None
    clarity_feedback = None
    try:
        from ai.department_recommender import get_recommender
        recommender = get_recommender()
        dept_recommendation = recommender.recommend(
            category=complaint["category"],
            title=complaint["title"],
            description=complaint["description"],
            departments=[dict(d) for d in all_departments],
        )
    except Exception as exc:
        logger.warning("Could not calculate dept recommendation: %s", exc)

    try:
        from ai.clarity_analyzer import get_clarity_analyzer
        clarity_feedback = get_clarity_analyzer().analyze(
            description=complaint["description"],
            address=complaint["address"],
        )
    except Exception as exc:
        logger.warning("Could not calculate clarity feedback: %s", exc)

    return render_template(
        "admin/detail.html",
        complaint=complaint,
        department=department,
        officer=officer,
        status_history=status_history,
        action_notes=action_notes,
        duplicate_links=duplicate_links,
        dept_recommendation=dept_recommendation,
        clarity_feedback=clarity_feedback,
        # Write-form data
        statuses=COMPLAINT_STATUSES,
        departments=all_departments,
        all_officers=all_officers,
    )


# ── Admin write routes (Phase 4B / 4D) ───────────────────────────────────────

_NOTE_MAX_LEN = 1000   # maximum characters for an action note


@admin_bp.route("/complaint/<complaint_id>/update", methods=["POST"])
def complaint_update(complaint_id: str):
    """
    Update a complaint's status and/or department/officer assignment.

    Form fields (all optional, applied only when non-empty):
        new_status      – must be in COMPLAINT_STATUSES
        department_id   – integer FK; "0" or "" clears the assignment
        officer_id      – integer FK; "0" or "" clears the assignment
        action_note     – free text appended to status_history

    CSRF-protected: rejects requests without a valid session token.
    """
    if session.get("is_demo"):
        abort(403, description="Demo mode is read-only. Modifying complaint data is disabled.")

    if not verify_csrf():
        abort(403)

    complaint = db.get_complaint_by_id(complaint_id)
    if complaint is None:
        abort(404)

    errors = []

    new_status  = request.form.get("new_status",    "").strip()
    dept_raw    = request.form.get("department_id", "").strip()
    officer_raw = request.form.get("officer_id",    "").strip()
    action_note = request.form.get("action_note",   "").strip() or None

    # ── Validate new_status ─────────────────────────────────────────
    if new_status:
        if new_status not in COMPLAINT_STATUSES:
            errors.append(f"Invalid status: '{new_status}'.")

    # ── Validate department_id ──────────────────────────────────────
    department_id: int | None = None
    if dept_raw and dept_raw != "0":
        try:
            department_id = int(dept_raw)
        except ValueError:
            errors.append("Department ID must be a number.")
        else:
            # Verify FK exists
            departments = {d["id"] for d in db.get_all_departments()}
            if department_id not in departments:
                errors.append(f"Department {department_id} does not exist.")

    # ── Validate officer_id ─────────────────────────────────────────
    officer_id: int | None = None
    if officer_raw and officer_raw != "0":
        try:
            officer_id = int(officer_raw)
        except ValueError:
            errors.append("Officer ID must be a number.")
        else:
            if department_id is not None:
                valid_officers = {
                    o["id"] for o in db.get_officers_by_department(department_id)
                }
                if officer_id not in valid_officers:
                    errors.append(
                        f"Officer {officer_id} does not belong to department {department_id}."
                    )

    if errors:
        flash(" ".join(errors), "error")
        return redirect(url_for("admin.complaint_detail", complaint_id=complaint_id)), 422

    # ── Apply changes ────────────────────────────────────────────────
    if new_status:
        db.update_complaint_status(
            complaint_id=complaint_id,
            new_status=new_status,
            action_note=action_note,
        )

    if dept_raw or officer_raw:
        # Pass None when the raw value was empty or "0" (clear assignment)
        db.assign_complaint(
            complaint_id=complaint_id,
            department_id=department_id,
            officer_id=officer_id,
        )

    # ── Resolution handling ────────────────────────────────────────────────
    resolution_message = request.form.get("resolution_message", "").strip() or None
    resolution_image_path = None
    resolution_image = request.files.get("resolution_image")
    if resolution_image and resolution_image.filename:
        try:
            # Re‑use the same image‑validation helper used for citizen uploads
            from routes.submit import _save_image
            resolution_image_path = _save_image(resolution_image)
        except ValueError as exc:
            errors.append(str(exc))

    # If any errors appeared after processing resolution fields, abort before DB write
    if errors:
        # Clean up newly saved image if present
        if resolution_image_path:
            try:
                os.remove(os.path.join(UPLOAD_DIR, resolution_image_path))
            except Exception:
                pass
        flash(" ".join(errors), "error")
        return redirect(url_for("admin.complaint_detail", complaint_id=complaint_id)), 422

    if resolution_message is not None or resolution_image_path is not None:
        # Update only the columns that were supplied (keep existing values otherwise)
        with db.db_cursor() as (conn, cur):
            cur.execute(
                """UPDATE complaints
                   SET resolution_message = COALESCE(?, resolution_message),
                       resolution_image_path = COALESCE(?, resolution_image_path)
                   WHERE complaint_id = ?;""",
                (resolution_message, resolution_image_path, complaint_id),
            )

    flash("Complaint updated.", "success")
    return redirect(url_for("admin.complaint_detail", complaint_id=complaint_id))


@admin_bp.route("/complaint/<complaint_id>/add_note", methods=["POST"])
def complaint_add_note(complaint_id: str):
    """
    Append an action note to a complaint.

    Form fields:
        note  – required, 1–1000 characters

    CSRF-protected.
    """
    if session.get("is_demo"):
        abort(403, description="Demo mode is read-only. Adding action notes is disabled.")

    if not verify_csrf():
        abort(403)

    complaint = db.get_complaint_by_id(complaint_id)
    if complaint is None:
        abort(404)

    note = request.form.get("note", "").strip()

    if not note:
        flash("Note cannot be empty.", "error")
        return redirect(url_for("admin.complaint_detail", complaint_id=complaint_id)), 422

    if len(note) > _NOTE_MAX_LEN:
        flash(f"Note must be {_NOTE_MAX_LEN} characters or fewer.", "error")
        return redirect(url_for("admin.complaint_detail", complaint_id=complaint_id)), 422

    db.add_action_note(complaint_id=complaint_id, note=note)
    flash("Note added.", "success")
    return redirect(url_for("admin.complaint_detail", complaint_id=complaint_id))


# ── Hotspot map ───────────────────────────────────────────────────────────────

def _get_geo_complaints() -> list:
    """
    Return all complaints that have non-NULL latitude and longitude,
    along with the columns needed for hotspot detection and display.
    Read-only — never modifies any complaint record.
    """
    with db.db_cursor() as (conn, cur):
        cur.execute(
            """SELECT complaint_id, title, category, address, status,
                      latitude, longitude, priority_level, priority_score
               FROM complaints
               WHERE latitude IS NOT NULL
                 AND longitude IS NOT NULL
               ORDER BY created_at DESC;"""
        )
        return cur.fetchall()


@admin_bp.route("/hotspots")
def hotspots():
    """
    Admin hotspot map.
    Runs the HotspotDetector over all geo-located complaints and renders
    a Leaflet map with cluster markers.  Read-only — no DB writes.
    """
    geo_complaints = _get_geo_complaints()
    detector       = get_hotspot_detector()
    hotspot_list   = detector.detect([dict(c) for c in geo_complaints])

    # Convert NamedTuples to plain dicts so Jinja2 tojson serialises them
    # as JSON objects (not arrays), making the client-side code simple.
    hotspots_data = [
        {
            "center_lat":         h.center_lat,
            "center_lon":         h.center_lon,
            "complaint_ids":      h.complaint_ids,
            "count":              h.count,
            "dominant_category":  h.dominant_category,
            "radius_km":          h.radius_km,
            "critical_count":     h.critical_count,
            "high_count":         h.high_count,
            "avg_priority_score": h.avg_priority_score,
        }
        for h in hotspot_list
    ]

    return render_template(
        "admin/hotspots.html",
        hotspots=hotspot_list,          # NamedTuples for Jinja2 template iteration
        hotspots_json=hotspots_data,    # plain dicts for tojson → Leaflet JS
        total_geo=len(geo_complaints),
    )


# ── Action Brief (Phase 3E) ───────────────────────────────────────────────────

def _get_all_complaints_for_brief() -> list[dict]:
    """
    Return all complaint rows as plain dicts for the ActionBriefGenerator.
    Includes every column the generator needs: category, status, priority,
    address, department_id, etc.
    """
    with db.db_cursor() as (conn, cur):
        cur.execute(
            """SELECT complaint_id, title, category, address,
                      status, priority_level, priority_score,
                      department_id, assigned_officer,
                      latitude, longitude
               FROM complaints
               ORDER BY created_at DESC;"""
        )
        return [dict(row) for row in cur.fetchall()]


@admin_bp.route("/brief")
def action_brief():
    """
    Admin Action Brief page.
    Generates a situation brief from all current complaints on first visit.
    The page includes a "Refresh" button that POSTs to /brief/generate.
    Read-only — no DB writes.
    """
    from ai.action_brief import get_brief_generator
    complaints   = _get_all_complaints_for_brief()
    geo_comps    = _get_geo_complaints()
    detector     = get_hotspot_detector()
    hotspot_list = detector.detect([dict(c) for c in geo_comps])

    generator = get_brief_generator()
    brief     = generator.generate(complaints, hotspot_list)

    return render_template("admin/brief.html", brief=brief)


@admin_bp.route("/brief/generate", methods=["POST"])
def action_brief_generate():
    """
    Refresh the action brief.  Redirects back to the brief page.
    CSRF-protected so the POST cannot be forged.
    """
    if not verify_csrf():
        abort(403)
    flash("Action brief refreshed.", "success")
    return redirect(url_for("admin.action_brief"))


# ── Interactive Complaint Map (Phase 4D) ─────────────────────────────────────

@admin_bp.route("/map")
def map_view():
    """
    Admin interactive complaint map.
    Renders all complaints with real GPS coordinates using Leaflet and OpenStreetMap.
    Markers are color-coded by status and priority, with rich popups linking to details.
    """
    geo_complaints = _get_geo_complaints()
    detector = get_hotspot_detector()
    hotspot_list = detector.detect([dict(c) for c in geo_complaints])

    complaints_data = [
        {
            "complaint_id": c["complaint_id"],
            "title": c["title"],
            "category": c["category"],
            "address": c["address"] or "",
            "latitude": c["latitude"],
            "longitude": c["longitude"],
            "priority_level": c["priority_level"],
            "priority_score": c["priority_score"],
            "status": c["status"] if "status" in c.keys() else "Submitted",
        }
        for c in geo_complaints
    ]

    hotspots_data = [
        {
            "center_lat": h.center_lat,
            "center_lon": h.center_lon,
            "complaint_ids": h.complaint_ids,
            "count": h.count,
            "dominant_category": h.dominant_category,
            "radius_km": h.radius_km,
            "critical_count": h.critical_count,
            "high_count": h.high_count,
            "avg_priority_score": h.avg_priority_score,
        }
        for h in hotspot_list
    ]

    return render_template(
        "admin/map.html",
        complaints=geo_complaints,
        complaints_json=complaints_data,
        hotspots=hotspot_list,
        hotspots_json=hotspots_data,
        total_geo=len(geo_complaints),
        categories=COMPLAINT_CATEGORIES,
        statuses=COMPLAINT_STATUSES,
    )


# ── Analytics Dashboard (Phase 5.7 & 5.8) ────────────────────────────────────

@admin_bp.route("/analytics")
def analytics_view():
    """
    Advanced Admin Analytics Dashboard.
    Provides resolution rates, turnaround time, trends, and predictive issue insights.
    """
    metrics = db.get_analytics_metrics()
    all_complaints = _get_all_complaints_for_brief()

    from ai.predictive_insights import get_insights_engine
    insights = get_insights_engine().generate_insights(all_complaints)

    geo_comps = _get_geo_complaints()
    detector = get_hotspot_detector()
    hotspot_list = detector.detect([dict(c) for c in geo_comps])

    return render_template(
        "admin/analytics.html",
        metrics=metrics,
        insights=insights,
        hotspots=hotspot_list,
    )


# ── Reports & Data Export (Phase 5.10) ────────────────────────────────────────

@admin_bp.route("/reports")
def reports_view():
    """
    Admin Complaint Reports and Filtering.
    Enables multi-criteria query and analysis across categories, statuses, and dates.
    """
    category = request.args.get("category", "").strip()
    status = request.args.get("status", "").strip()
    priority = request.args.get("priority", "").strip()
    dept_raw = request.args.get("department_id", "").strip()
    department_id = int(dept_raw) if dept_raw and dept_raw.isdigit() else None
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    complaints = db.get_report_complaints(
        category=category,
        status=status,
        priority=priority,
        department_id=department_id,
        start_date=start_date,
        end_date=end_date,
    )
    all_departments = db.get_all_departments()

    total_count = len(complaints)
    resolved_count = sum(1 for c in complaints if c["status"] in ("Resolved", "Closed"))
    critical_count = sum(1 for c in complaints if c["priority_level"] == "Critical")

    return render_template(
        "admin/reports.html",
        complaints=complaints,
        total_count=total_count,
        resolved_count=resolved_count,
        critical_count=critical_count,
        categories=COMPLAINT_CATEGORIES,
        statuses=COMPLAINT_STATUSES,
        priority_levels=PRIORITY_LEVELS,
        departments=all_departments,
        active_category=category,
        active_status=status,
        active_priority=priority,
        active_dept=department_id,
        active_start=start_date,
        active_end=end_date,
    )


@admin_bp.route("/reports/export.csv")
def reports_export_csv():
    """
    Export filtered complaints dataset as CSV with formula-injection sanitization.
    """
    category = request.args.get("category", "").strip()
    status = request.args.get("status", "").strip()
    priority = request.args.get("priority", "").strip()
    dept_raw = request.args.get("department_id", "").strip()
    department_id = int(dept_raw) if dept_raw and dept_raw.isdigit() else None
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    complaints = db.get_report_complaints(
        category=category,
        status=status,
        priority=priority,
        department_id=department_id,
        start_date=start_date,
        end_date=end_date,
    )

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    headers = [
        "Complaint ID", "Title", "Category", "Status",
        "Priority Level", "Priority Score", "Location / Address",
        "Department", "Assigned Officer", "Submitted At", "Resolved At",
        "Resolution Note",
    ]
    writer.writerow(headers)

    def _sanitize_csv_cell(val) -> str:
        s = str(val or "")
        if s.startswith(("=", "+", "-", "@", "\t", "\r")):
            return "'" + s
        return s

    from dates import format_datetime, now_ist

    for c in complaints:
        writer.writerow([
            _sanitize_csv_cell(c["complaint_id"]),
            _sanitize_csv_cell(c["title"]),
            _sanitize_csv_cell(c["category"]),
            _sanitize_csv_cell(c["status"]),
            _sanitize_csv_cell(c["priority_level"]),
            c["priority_score"] if c["priority_score"] is not None else "",
            _sanitize_csv_cell(c["address"]),
            _sanitize_csv_cell(c["department_name"]),
            _sanitize_csv_cell(c["officer_name"]),
            _sanitize_csv_cell(format_datetime(c["created_at"], default="")),
            _sanitize_csv_cell(format_datetime(c["resolved_at"], default="") if c["resolved_at"] else ""),
            _sanitize_csv_cell(c["resolution_message"]),
        ])

    csv_data = output.getvalue()
    stamp = now_ist().strftime("%Y%m%d_%H%M%S")
    filename = f"urbanfix_complaints_{stamp}.csv"

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
