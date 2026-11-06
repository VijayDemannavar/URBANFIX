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
]


# ── Initialisation ────────────────────────────────────────────────────────────

# Phase 3A/3B migration: new columns on complaints
_PHASE3_MIGRATIONS = [
    "ALTER TABLE complaints ADD COLUMN ai_confidence   REAL;",
    "ALTER TABLE complaints ADD COLUMN ai_explanation  TEXT;",
    "ALTER TABLE complaints ADD COLUMN ai_needs_review INTEGER NOT NULL DEFAULT 0;",
]


def _run_migrations() -> None:
    """
    Apply additive ALTER TABLE migrations idempotently.
    SQLite does not support IF NOT EXISTS for ADD COLUMN, so we catch
    the OperationalError that fires when the column already exists.
    """
    conn = get_connection()
    try:
        for ddl in _PHASE3_MIGRATIONS:
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


# ── Entry point (quick sanity check) ─────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    seed_departments()
    print(f"Database ready at: {DATABASE_PATH}")
