"""
database.py – CivicAI Database Layer
Handles connection, initialisation, table creation, and seeding of departments.
All queries use parameterised statements to prevent SQL injection.
"""

import os
import sqlite3
import logging
from contextlib import contextmanager

from config import DATABASE_PATH, DATABASE_DIR

logger = logging.getLogger(__name__)


# ── Connection ────────────────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    """
    Open and return a connection to the SQLite database.
    Foreign key enforcement is enabled on every connection.
    Row factory is set so rows behave like dicts.
    """
    os.makedirs(DATABASE_DIR, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    # Enable foreign key enforcement (SQLite requires this per connection)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def db_cursor():
    """
    Context manager that yields a (connection, cursor) pair.
    Commits on success, rolls back on error, always closes the connection.

    Usage:
        with db_cursor() as (conn, cur):
            cur.execute(...)
    """
    conn = get_connection()
    cur  = conn.cursor()
    try:
        yield conn, cur
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("Database error: %s", exc)
        raise
    finally:
        cur.close()
        conn.close()


def close_connection(conn: sqlite3.Connection) -> None:
    """Safely close a connection, suppressing errors if already closed."""
    try:
        if conn:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning("Error closing connection: %s", exc)


# ── Schema ────────────────────────────────────────────────────────────────────

_CREATE_DEPARTMENTS = """
CREATE TABLE IF NOT EXISTS departments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    department_name TEXT    NOT NULL UNIQUE,
    description     TEXT
);
"""

_CREATE_OFFICERS = """
CREATE TABLE IF NOT EXISTS officers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    officer_name  TEXT    NOT NULL,
    department_id INTEGER NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE RESTRICT
);
"""

_CREATE_COMPLAINTS = """
CREATE TABLE IF NOT EXISTS complaints (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id     TEXT    NOT NULL UNIQUE,
    title            TEXT    NOT NULL,
    description      TEXT    NOT NULL,
    category         TEXT    NOT NULL,
    ai_category      TEXT,
    ai_summary       TEXT,
    ai_confidence    REAL,
    ai_explanation   TEXT,
    ai_needs_review  INTEGER NOT NULL DEFAULT 0,
    image_path       TEXT,
    latitude         REAL,
    longitude        REAL,
    address          TEXT,
    priority_score   REAL    NOT NULL DEFAULT 0.0,
    priority_level   TEXT    NOT NULL DEFAULT 'Low',
    priority_reason  TEXT,
    status           TEXT    NOT NULL DEFAULT 'Submitted',
    department_id    INTEGER,
    assigned_officer INTEGER,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    resolved_at      TEXT,
    FOREIGN KEY (department_id)    REFERENCES departments(id) ON DELETE SET NULL,
    FOREIGN KEY (assigned_officer) REFERENCES officers(id)    ON DELETE SET NULL
);
"""

_CREATE_STATUS_HISTORY = """
CREATE TABLE IF NOT EXISTS status_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id TEXT    NOT NULL,
    old_status   TEXT,
    new_status   TEXT    NOT NULL,
    action_note  TEXT,
    changed_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (complaint_id) REFERENCES complaints(complaint_id) ON DELETE CASCADE
);
"""

_CREATE_DUPLICATE_LINKS = """
CREATE TABLE IF NOT EXISTS duplicate_links (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id         TEXT    NOT NULL,
    matched_complaint_id TEXT    NOT NULL,
    similarity_score     REAL    NOT NULL DEFAULT 0.0,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (complaint_id)         REFERENCES complaints(complaint_id) ON DELETE CASCADE,
    FOREIGN KEY (matched_complaint_id) REFERENCES complaints(complaint_id) ON DELETE CASCADE
);
"""

_CREATE_ACTION_NOTES = """
CREATE TABLE IF NOT EXISTS action_notes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id TEXT NOT NULL,
    note         TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (complaint_id) REFERENCES complaints(complaint_id) ON DELETE CASCADE
);
"""

_CREATE_NOTIFICATIONS = """
CREATE TABLE IF NOT EXISTS notifications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id TEXT    NOT NULL,
    title        TEXT    NOT NULL,
    message      TEXT    NOT NULL,
    is_read      INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (complaint_id) REFERENCES complaints(complaint_id) ON DELETE CASCADE
);
"""

# ── Indexes ───────────────────────────────────────────────────────────────────

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_complaints_status       ON complaints(status);",
    "CREATE INDEX IF NOT EXISTS idx_complaints_category     ON complaints(category);",
    "CREATE INDEX IF NOT EXISTS idx_complaints_priority     ON complaints(priority_level);",
    "CREATE INDEX IF NOT EXISTS idx_complaints_department   ON complaints(department_id);",
    "CREATE INDEX IF NOT EXISTS idx_complaints_created_at   ON complaints(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_complaints_location     ON complaints(latitude, longitude);",
    "CREATE INDEX IF NOT EXISTS idx_status_history_cid      ON status_history(complaint_id);",
    "CREATE INDEX IF NOT EXISTS idx_duplicate_links_cid     ON duplicate_links(complaint_id);",
    "CREATE INDEX IF NOT EXISTS idx_action_notes_cid        ON action_notes(complaint_id);",
    "CREATE INDEX IF NOT EXISTS idx_officers_department     ON officers(department_id);",
    "CREATE INDEX IF NOT EXISTS idx_notifications_cid       ON notifications(complaint_id);",
    "CREATE INDEX IF NOT EXISTS idx_notifications_read      ON notifications(is_read);",
]


# ── Initialisation ────────────────────────────────────────────────────────────

# Phase 3A/3B migration: new columns on complaints
_PHASE3_MIGRATIONS = [
    "ALTER TABLE complaints ADD COLUMN ai_confidence   REAL;",
    "ALTER TABLE complaints ADD COLUMN ai_explanation  TEXT;",
    "ALTER TABLE complaints ADD COLUMN ai_needs_review INTEGER NOT NULL DEFAULT 0;",
    "ALTER TABLE complaints ADD COLUMN resolution_message TEXT;",
    "ALTER TABLE complaints ADD COLUMN resolution_image_path TEXT;",
]

# Phase 5 migrations: AI suggestions and clarity feedback
_PHASE5_MIGRATIONS = [
    "ALTER TABLE complaints ADD COLUMN ai_suggested_dept TEXT;",
    "ALTER TABLE complaints ADD COLUMN ai_feedback TEXT;",
]


def _run_migrations() -> None:
    """
    Apply additive ALTER TABLE migrations idempotently.
    SQLite does not support IF NOT EXISTS for ADD COLUMN, so we catch
    the OperationalError that fires when the column already exists.
    """
    conn = get_connection()
    try:
        for ddl in _PHASE3_MIGRATIONS + _PHASE5_MIGRATIONS:
            try:
                conn.execute(ddl)
                conn.commit()
                col = ddl.split("ADD COLUMN")[1].strip().split()[0]
                logger.info("Migration applied: added column '%s'.", col)
            except sqlite3.OperationalError as exc:
                if "duplicate column name" in str(exc).lower():
                    pass   # already applied – idempotent
                else:
                    raise
    finally:
        conn.close()


def init_db() -> None:
    """
    Create all tables, indexes, and run schema migrations.
    Safe to call multiple times – uses IF NOT EXISTS everywhere.
    """
    tables = [
        _CREATE_DEPARTMENTS,
        _CREATE_OFFICERS,
        _CREATE_COMPLAINTS,
        _CREATE_STATUS_HISTORY,
        _CREATE_DUPLICATE_LINKS,
        _CREATE_ACTION_NOTES,
        _CREATE_NOTIFICATIONS,
    ]
    with db_cursor() as (conn, cur):
        for ddl in tables:
            cur.execute(ddl)
        for idx in _INDEXES:
            cur.execute(idx)
    _run_migrations()
    logger.info("Database initialised at %s", DATABASE_PATH)


# ── Department seed ───────────────────────────────────────────────────────────

INITIAL_DEPARTMENTS = [
    ("Public Works",          "Manages roads, bridges, and public infrastructure"),
    ("Water & Sanitation",    "Handles water supply, sewage, and drainage systems"),
    ("Waste Management",      "Responsible for garbage collection and disposal"),
    ("Electrical Department", "Manages streetlights, public electrical infrastructure"),
    ("Traffic & Safety",      "Manages public safety, traffic signals, and hazards"),
    ("Parks & Environment",   "Oversees parks, trees, and environmental complaints"),
]


def seed_departments() -> None:
    """
    Insert the standard civic departments if they do not already exist.
    Uses INSERT OR IGNORE to be idempotent.
    """
    with db_cursor() as (conn, cur):
        cur.executemany(
            "INSERT OR IGNORE INTO departments (department_name, description) VALUES (?, ?);",
            INITIAL_DEPARTMENTS,
        )
    logger.info("Departments seeded.")


# ── Convenience query helpers (used by routes in later phases) ───────────────

def get_complaint_by_id(complaint_id: str) -> sqlite3.Row | None:
    """Fetch a single complaint row by its human-readable complaint_id."""
    with db_cursor() as (conn, cur):
        cur.execute(
            "SELECT * FROM complaints WHERE complaint_id = ?;",
            (complaint_id,),
        )
        return cur.fetchone()


def insert_status_history(
    complaint_id: str,
    old_status: str | None,
    new_status: str,
    action_note: str | None = None,
) -> None:
    """Append a row to status_history whenever a complaint's status changes."""
    with db_cursor() as (conn, cur):
        cur.execute(
            """INSERT INTO status_history
               (complaint_id, old_status, new_status, action_note)
               VALUES (?, ?, ?, ?);""",
            (complaint_id, old_status, new_status, action_note),
        )


def get_all_departments() -> list[sqlite3.Row]:
    """Return all department rows."""
    with db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM departments ORDER BY department_name;")
        return cur.fetchall()


def get_officers_by_department(department_id: int) -> list[sqlite3.Row]:
    """Return officers belonging to a department."""
    with db_cursor() as (conn, cur):
        cur.execute(
            "SELECT * FROM officers WHERE department_id = ? ORDER BY officer_name;",
            (department_id,),
        )
        return cur.fetchall()


def save_ai_results(
    complaint_id: str,
    ai_category: str,
    ai_confidence: float,
    ai_explanation: str,
    ai_needs_review: bool,
    priority_score: int | None = None,
    priority_level: str | None = None,
    priority_reason: str | None = None,
) -> None:
    """
    Write AI categorisation and priority results back to the complaints row.
    Never overwrites the citizen-selected 'category' column.

    Priority fields are optional; if omitted the existing DB values are kept.
    """
    with db_cursor() as (conn, cur):
        if priority_score is not None:
            cur.execute(
                """UPDATE complaints
                   SET ai_category      = ?,
                       ai_confidence    = ?,
                       ai_explanation   = ?,
                       ai_needs_review  = ?,
                       priority_score   = ?,
                       priority_level   = ?,
                       priority_reason  = ?,
                       updated_at       = datetime('now')
                   WHERE complaint_id   = ?;""",
                (ai_category, ai_confidence, ai_explanation,
                 1 if ai_needs_review else 0,
                 priority_score, priority_level, priority_reason,
                 complaint_id),
            )
        else:
            cur.execute(
                """UPDATE complaints
                   SET ai_category      = ?,
                       ai_confidence    = ?,
                       ai_explanation   = ?,
                       ai_needs_review  = ?,
                       updated_at       = datetime('now')
                   WHERE complaint_id   = ?;""",
                (ai_category, ai_confidence, ai_explanation,
                 1 if ai_needs_review else 0, complaint_id),
            )


def save_duplicate_link(
    complaint_id: str,
    matched_complaint_id: str,
    similarity_score: float,
) -> None:
    """
    Insert a duplicate link between two complaints (idempotent).
    Uses INSERT OR IGNORE so re-running AI never duplicates rows.
    """
    with db_cursor() as (conn, cur):
        cur.execute(
            """INSERT OR IGNORE INTO duplicate_links
               (complaint_id, matched_complaint_id, similarity_score)
               SELECT ?, ?, ?
               WHERE NOT EXISTS (
                   SELECT 1 FROM duplicate_links
                   WHERE complaint_id = ? AND matched_complaint_id = ?
               );""",
            (complaint_id, matched_complaint_id, similarity_score,
             complaint_id, matched_complaint_id),
        )


def update_complaint_status(
    complaint_id: str,
    new_status: str,
    action_note: str | None = None,
) -> None:
    """
    Update a complaint's status and record the transition in status_history.
    Sets resolved_at when new_status is 'Resolved' or 'Closed'.
    Never overwrites resolved_at once it is already set.
    """
    with db_cursor() as (conn, cur):
        cur.execute(
            "SELECT status, resolved_at FROM complaints WHERE complaint_id = ?;",
            (complaint_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Complaint not found: {complaint_id}")
        old_status   = row["status"]
        resolved_at  = row["resolved_at"]

        # Set resolved_at only when first reaching a terminal status
        if new_status in ("Resolved", "Closed") and resolved_at is None:
            cur.execute(
                """UPDATE complaints
                   SET status      = ?,
                       resolved_at = datetime('now'),
                       updated_at  = datetime('now')
                   WHERE complaint_id = ?;""",
                (new_status, complaint_id),
            )
        else:
            cur.execute(
                """UPDATE complaints
                   SET status     = ?,
                       updated_at = datetime('now')
                   WHERE complaint_id = ?;""",
                (new_status, complaint_id),
            )

        cur.execute(
            """INSERT INTO status_history
               (complaint_id, old_status, new_status, action_note)
               VALUES (?, ?, ?, ?);""",
            (complaint_id, old_status, new_status, action_note),
        )

        # In-App Notification trigger on status change
        if old_status != new_status:
            try:
                cur.execute(
                    """INSERT INTO notifications (complaint_id, title, message)
                       VALUES (?, ?, ?);""",
                    (
                        complaint_id,
                        f"Status Updated: {new_status}",
                        f"Complaint {complaint_id} status changed from '{old_status}' to '{new_status}'."
                        + (f" Note: {action_note}" if action_note else ""),
                    ),
                )
            except Exception as notif_exc:
                logger.warning("Could not create notification for %s: %s", complaint_id, notif_exc)
    logger.info("Status updated: %s → %s", complaint_id, new_status)


def assign_complaint(
    complaint_id: str,
    department_id: int | None,
    officer_id: int | None,
) -> None:
    """
    Assign (or unassign) a department and officer to a complaint.
    Accepts None to clear an assignment.
    """
    with db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id FROM complaints WHERE complaint_id = ?;",
            (complaint_id,),
        )
        if cur.fetchone() is None:
            raise ValueError(f"Complaint not found: {complaint_id}")

        cur.execute(
            """UPDATE complaints
               SET department_id    = ?,
                   assigned_officer = ?,
                   updated_at       = datetime('now')
               WHERE complaint_id   = ?;""",
            (department_id, officer_id, complaint_id),
        )
    logger.info("Assigned: %s → dept=%s officer=%s", complaint_id, department_id, officer_id)


def add_action_note(complaint_id: str, note: str) -> None:
    """
    Append an action note to a complaint.
    Raises ValueError if the complaint does not exist.
    """
    with db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id FROM complaints WHERE complaint_id = ?;",
            (complaint_id,),
        )
        if cur.fetchone() is None:
            raise ValueError(f"Complaint not found: {complaint_id}")

        cur.execute(
            "INSERT INTO action_notes (complaint_id, note) VALUES (?, ?);",
            (complaint_id, note),
        )
    logger.info("Action note added to %s.", complaint_id)


# ── Dashboard pagination helpers (Phase 4E) ──────────────────────────────────

# Allowed sort columns (maps URL param → SQL column name)
_SORT_COLUMNS = {
    "complaint_id":  "complaint_id",
    "title":         "title",
    "category":      "category",
    "address":       "address",
    "status":        "status",
    "priority":      "priority_score",
    "submitted":     "created_at",
}
_DEFAULT_SORT  = "created_at"
_DEFAULT_ORDER = "desc"


def _build_complaints_where(
    search: str = "",
    category: str = "",
    status: str = "",
    priority: str = "",
) -> tuple[str, list]:
    """
    Build the WHERE clause and parameter list for complaint list queries.

    Parameters are user-supplied filter values (all optional, empty = no filter).
    Returns (where_sql, params) where where_sql starts with 'WHERE' or is empty.
    """
    conditions: list[str] = []
    params: list = []

    if search:
        like = f"%{search}%"
        conditions.append(
            "(complaint_id LIKE ? OR title LIKE ? OR address LIKE ?)"
        )
        params.extend([like, like, like])

    if category:
        conditions.append("category = ?")
        params.append(category)

    if status:
        conditions.append("status = ?")
        params.append(status)

    if priority:
        conditions.append("priority_level = ?")
        params.append(priority)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return where, params


def count_complaints(
    search: str = "",
    category: str = "",
    status: str = "",
    priority: str = "",
) -> int:
    """
    Return the total number of complaints matching the given filters.
    Used by the dashboard to compute total pages without loading all rows.
    """
    where, params = _build_complaints_where(search, category, status, priority)
    sql = f"SELECT COUNT(*) FROM complaints {where};"
    with db_cursor() as (conn, cur):
        cur.execute(sql, params)
        row = cur.fetchone()
        return row[0] if row else 0


def get_complaints_page(
    page: int = 1,
    page_size: int = 100,
    search: str = "",
    category: str = "",
    status: str = "",
    priority: str = "",
    sort: str = _DEFAULT_SORT,
    order: str = _DEFAULT_ORDER,
) -> list[sqlite3.Row]:
    """
    Return a single page of complaint rows, applying filters, sort, and pagination.

    Parameters
    ----------
    page:       1-based page number (clamped to valid range by caller)
    page_size:  rows per page
    search:     substring search on complaint_id, title, address
    category:   exact match on category column
    status:     exact match on status column
    priority:   exact match on priority_level column
    sort:       column identifier (must be a key in _SORT_COLUMNS)
    order:      'asc' or 'desc'
    """
    # Sanitise sort / order to prevent SQL injection
    sort_col = _SORT_COLUMNS.get(sort, _DEFAULT_SORT)
    order_dir = "ASC" if str(order).lower() == "asc" else "DESC"

    where, params = _build_complaints_where(search, category, status, priority)
    offset = (page - 1) * page_size

    sql = f"""
        SELECT complaint_id, title, category, address,
               status, priority_level, priority_score,
               ai_category, ai_confidence, ai_needs_review,
               created_at, department_id, assigned_officer
        FROM complaints
        {where}
        ORDER BY {sort_col} {order_dir}
        LIMIT ? OFFSET ?;
    """
    params.extend([page_size, offset])

    with db_cursor() as (conn, cur):
        cur.execute(sql, params)
        return cur.fetchall()


# ── Notifications & Civic Platform Helpers (Phase 4C & Phase 5) ─────────────

def create_notification(complaint_id: str, title: str, message: str) -> int | None:
    """Insert an in-app notification for a complaint, preventing rapid duplicates."""
    with db_cursor() as (conn, cur):
        cur.execute(
            """SELECT id FROM notifications
               WHERE complaint_id = ? AND title = ? AND created_at >= datetime('now', '-5 minutes');""",
            (complaint_id, title),
        )
        if cur.fetchone():
            return None
        cur.execute(
            "INSERT INTO notifications (complaint_id, title, message) VALUES (?, ?, ?);",
            (complaint_id, title, message),
        )
        return cur.lastrowid


def get_notifications_by_complaint(complaint_id: str) -> list[sqlite3.Row]:
    """Get all notifications for a given complaint, sorted newest first."""
    with db_cursor() as (conn, cur):
        cur.execute(
            "SELECT * FROM notifications WHERE complaint_id = ? ORDER BY created_at DESC;",
            (complaint_id,),
        )
        return cur.fetchall()


def get_notifications_for_complaints(complaint_ids: list[str]) -> list[sqlite3.Row]:
    """Fetch notifications for a list of complaints (e.g., from citizen session)."""
    if not complaint_ids:
        return []
    placeholders = ",".join("?" for _ in complaint_ids)
    with db_cursor() as (conn, cur):
        cur.execute(
            f"SELECT * FROM notifications WHERE complaint_id IN ({placeholders}) ORDER BY created_at DESC;",
            complaint_ids,
        )
        return cur.fetchall()


def get_unread_notification_count(complaint_ids: list[str] | None = None) -> int:
    """Return count of unread notifications, optionally filtered to citizen's complaint IDs."""
    if complaint_ids is not None and not complaint_ids:
        return 0
    with db_cursor() as (conn, cur):
        if complaint_ids:
            placeholders = ",".join("?" for _ in complaint_ids)
            cur.execute(
                f"SELECT COUNT(*) FROM notifications WHERE is_read = 0 AND complaint_id IN ({placeholders});",
                complaint_ids,
            )
        else:
            cur.execute("SELECT COUNT(*) FROM notifications WHERE is_read = 0;")
        row = cur.fetchone()
        return row[0] if row else 0


def get_notification_by_id(notification_id: int) -> sqlite3.Row | None:
    """Fetch a single notification by its primary key ID."""
    with db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM notifications WHERE id = ?;", (notification_id,))
        return cur.fetchone()


def mark_notification_as_read(
    notification_id: int,
    complaint_ids: list[str] | None = None,
) -> bool:
    """
    Mark a specific notification as read, optionally validating that it belongs
    to one of the allowed complaint_ids.
    If complaint_ids is an empty list, returns False immediately without modifying anything.
    """
    if complaint_ids is not None and not complaint_ids:
        return False
    with db_cursor() as (conn, cur):
        if complaint_ids is not None:
            placeholders = ",".join("?" for _ in complaint_ids)
            cur.execute(
                f"UPDATE notifications SET is_read = 1 WHERE id = ? AND complaint_id IN ({placeholders});",
                [notification_id, *complaint_ids],
            )
        else:
            cur.execute("UPDATE notifications SET is_read = 1 WHERE id = ?;", (notification_id,))
        return cur.rowcount > 0


def mark_all_notifications_read(complaint_ids: list[str] | None = None) -> int:
    """
    Mark all matching unread notifications as read.
    If complaint_ids is an empty list, returns 0 without touching any rows.
    If complaint_ids is None, marks all notifications in the system (maintenance use only).
    """
    if complaint_ids is not None and not complaint_ids:
        return 0
    with db_cursor() as (conn, cur):
        if complaint_ids:
            placeholders = ",".join("?" for _ in complaint_ids)
            cur.execute(
                f"UPDATE notifications SET is_read = 1 WHERE is_read = 0 AND complaint_id IN ({placeholders});",
                complaint_ids,
            )
        else:
            cur.execute("UPDATE notifications SET is_read = 1 WHERE is_read = 0;")
        return cur.rowcount


def get_platform_stats() -> dict:
    """
    Return high-level civic platform summary statistics for the homepage.
    Always reflects real DB values, handles empty DB safely.
    """
    with db_cursor() as (conn, cur):
        cur.execute(
            """SELECT
                 COUNT(*) AS total,
                 SUM(status IN ('Resolved', 'Closed')) AS resolved,
                 SUM(status IN ('Submitted', 'Under Review')) AS pending,
                 SUM(status IN ('Assigned', 'In Progress')) AS in_progress,
                 COUNT(DISTINCT category) AS active_categories
               FROM complaints;"""
        )
        row = cur.fetchone()
        if not row:
            return {"total": 0, "resolved": 0, "pending": 0, "in_progress": 0, "active_categories": 0}
        return {
            "total": row["total"] or 0,
            "resolved": row["resolved"] or 0,
            "pending": row["pending"] or 0,
            "in_progress": row["in_progress"] or 0,
            "active_categories": row["active_categories"] or 0,
        }


def get_analytics_metrics() -> dict:
    """
    Calculate comprehensive analytics and resolution insights for admin dashboard.
    All computed from live database records.
    """
    with db_cursor() as (conn, cur):
        # Basic status & priority counts
        cur.execute(
            """SELECT
                 COUNT(*) AS total,
                 SUM(status = 'Submitted') AS submitted,
                 SUM(status = 'Under Review') AS under_review,
                 SUM(status = 'Assigned') AS assigned,
                 SUM(status = 'In Progress') AS in_progress,
                 SUM(status = 'Resolved') AS resolved,
                 SUM(status = 'Closed') AS closed,
                 SUM(status = 'Rejected') AS rejected,
                 SUM(priority_level = 'Critical') AS critical,
                 SUM(priority_level = 'High') AS high,
                 SUM(priority_level = 'Medium') AS medium,
                 SUM(priority_level = 'Low') AS low
               FROM complaints;"""
        )
        row = cur.fetchone()
        total = (row["total"] or 0) if row else 0
        resolved_total = ((row["resolved"] or 0) + (row["closed"] or 0)) if row else 0
        res_rate = round((resolved_total / total * 100), 1) if total > 0 else 0.0

        # Average resolution time in days (julianday difference)
        cur.execute(
            """SELECT AVG(julianday(resolved_at) - julianday(created_at))
               FROM complaints
               WHERE resolved_at IS NOT NULL AND status IN ('Resolved', 'Closed');"""
        )
        avg_res_row = cur.fetchone()
        avg_res_days = round(avg_res_row[0], 1) if (avg_res_row and avg_res_row[0] is not None) else 0.0

        # Category distribution
        cur.execute(
            """SELECT category, COUNT(*) as cnt
               FROM complaints
               GROUP BY category
               ORDER BY cnt DESC;"""
        )
        category_dist = [{"category": r["category"], "count": r["cnt"]} for r in cur.fetchall()]

        # Monthly trends
        cur.execute(
            """SELECT substr(created_at, 1, 7) AS month, COUNT(*) as cnt,
                      SUM(status IN ('Resolved', 'Closed')) as resolved_cnt
               FROM complaints
               GROUP BY month
               ORDER BY month ASC;"""
        )
        monthly_trends = [{"month": r["month"], "count": r["cnt"], "resolved": r["resolved_cnt"] or 0} for r in cur.fetchall()]

        # Department distribution
        cur.execute(
            """SELECT COALESCE(d.department_name, 'Unassigned') as dept_name,
                      COUNT(c.id) as total_assigned,
                      SUM(c.status NOT IN ('Resolved', 'Closed', 'Rejected')) as unresolved
               FROM complaints c
               LEFT JOIN departments d ON c.department_id = d.id
               GROUP BY dept_name
               ORDER BY total_assigned DESC;"""
        )
        dept_dist = [{"department": r["dept_name"], "total": r["total_assigned"], "unresolved": r["unresolved"] or 0} for r in cur.fetchall()]

        # Long unresolved complaints (> 7 days or oldest pending)
        cur.execute(
            """SELECT complaint_id, title, category, status, priority_level, created_at
               FROM complaints
               WHERE status NOT IN ('Resolved', 'Closed', 'Rejected')
               ORDER BY created_at ASC
               LIMIT 10;"""
        )
        unresolved_long = [dict(r) for r in cur.fetchall()]

        # Critical attention complaints
        cur.execute(
            """SELECT complaint_id, title, category, status, priority_level, priority_score, created_at
               FROM complaints
               WHERE priority_level = 'Critical' AND status NOT IN ('Resolved', 'Closed')
               ORDER BY priority_score DESC, created_at ASC
               LIMIT 10;"""
        )
        critical_urgent = [dict(r) for r in cur.fetchall()]

        return {
            "total": total,
            "submitted": (row["submitted"] or 0) if row else 0,
            "under_review": (row["under_review"] or 0) if row else 0,
            "assigned": (row["assigned"] or 0) if row else 0,
            "in_progress": (row["in_progress"] or 0) if row else 0,
            "resolved": (row["resolved"] or 0) if row else 0,
            "closed": (row["closed"] or 0) if row else 0,
            "rejected": (row["rejected"] or 0) if row else 0,
            "critical": (row["critical"] or 0) if row else 0,
            "high": (row["high"] or 0) if row else 0,
            "medium": (row["medium"] or 0) if row else 0,
            "low": (row["low"] or 0) if row else 0,
            "resolution_rate": res_rate,
            "avg_resolution_days": avg_res_days,
            "category_distribution": category_dist,
            "monthly_trends": monthly_trends,
            "department_distribution": dept_dist,
            "unresolved_long": unresolved_long,
            "critical_urgent": critical_urgent,
        }


def get_report_complaints(
    category: str = "",
    status: str = "",
    priority: str = "",
    department_id: int | None = None,
    start_date: str = "",
    end_date: str = "",
) -> list[sqlite3.Row]:
    """Retrieve filtered complaint records for reporting and CSV export."""
    conditions = []
    params: list = []
    if category:
        conditions.append("c.category = ?")
        params.append(category)
    if status:
        conditions.append("c.status = ?")
        params.append(status)
    if priority:
        conditions.append("c.priority_level = ?")
        params.append(priority)
    if department_id:
        conditions.append("c.department_id = ?")
        params.append(department_id)
    if start_date:
        conditions.append("c.created_at >= ?")
        params.append(start_date + " 00:00:00")
    if end_date:
        conditions.append("c.created_at <= ?")
        params.append(end_date + " 23:59:59")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"""
        SELECT c.complaint_id, c.title, c.category, c.status,
               c.priority_level, c.priority_score, c.address,
               c.created_at, c.updated_at, c.resolved_at,
               c.resolution_message,
               COALESCE(d.department_name, 'Unassigned') as department_name,
               COALESCE(o.officer_name, 'Unassigned') as officer_name
        FROM complaints c
        LEFT JOIN departments d ON c.department_id = d.id
        LEFT JOIN officers o ON c.assigned_officer = o.id
        {where}
        ORDER BY c.created_at DESC;
    """
    with db_cursor() as (conn, cur):
        cur.execute(sql, params)
        return cur.fetchall()


def save_ai_recommendations(complaint_id: str, suggested_dept: str, feedback: str) -> None:
    """Save AI department suggestion and description clarity feedback."""
    with db_cursor() as (conn, cur):
        cur.execute(
            """UPDATE complaints
               SET ai_suggested_dept = ?,
                   ai_feedback = ?
               WHERE complaint_id = ?;""",
            (suggested_dept, feedback, complaint_id),
        )


# ── Entry point (quick sanity check) ─────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    seed_departments()
    print(f"Database ready at: {DATABASE_PATH}")
