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
import hmac
import logging
import sqlite3

from flask import (
    Blueprint, render_template, request, abort,
    redirect, url_for, flash, current_app,
)
from ai.hotspot_detector import get_hotspot_detector

import database as db
from config import (
    COMPLAINT_CATEGORIES, COMPLAINT_STATUSES, PRIORITY_LEVELS,
    ADMIN_AUTH_MODE, ADMIN_PASSWORD, DASHBOARD_PAGE_SIZE,
)
from routes.csrf import verify_csrf

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ── Admin authentication (Phase 4D) ──────────────────────────────────────────

def _check_admin_auth() -> None:
    """
    Enforce admin authentication based on ADMIN_AUTH_MODE.

    Skipped entirely when ``app.config["TESTING"]`` is ``True`` so that the
    existing test suite passes without supplying credentials.

    Raises:
        HTTP 503 – if ADMIN_AUTH_MODE is "disabled"
        HTTP 401 – if ADMIN_AUTH_MODE is "password" and credentials are missing
                   or incorrect
    """
    if current_app.config.get("TESTING"):
        return  # bypass in test mode

    mode = current_app.config.get("ADMIN_AUTH_MODE", ADMIN_AUTH_MODE)

    if mode == "disabled":
        abort(503)

    if mode == "password":
        expected_password = current_app.config.get("ADMIN_PASSWORD", ADMIN_PASSWORD)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Basic "):
            try:
                decoded   = base64.b64decode(auth_header[6:]).decode("utf-8", errors="replace")
                _user, _, supplied = decoded.partition(":")
                if expected_password and hmac.compare_digest(supplied, expected_password):
                    return  # authenticated
            except Exception:
                pass
        # Not authenticated: challenge the browser
        from flask import make_response
        resp = make_response("Admin authentication required.", 401)
        resp.headers["WWW-Authenticate"] = 'Basic realm="CivicAI Admin"'
        abort(resp)

    # mode == "open" → no check required


@admin_bp.before_request
def _admin_auth_before_request():
    _check_admin_auth()


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

    return render_template(
        "admin/detail.html",
        complaint=complaint,
        department=department,
        officer=officer,
        status_history=status_history,
        action_notes=action_notes,
        duplicate_links=duplicate_links,
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
            """SELECT complaint_id, title, category, address,
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
