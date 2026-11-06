"""
tests/test_database.py – CivicAI Phase 1 Database Tests
Run with: python -m pytest tests/ -v
         OR: python tests/test_database.py
"""

import os
import sys
import sqlite3
import unittest
import tempfile
import shutil

# Ensure the project root is on the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as _config
import database as db   # imported once; we redirect its path references below

_TEST_DIR = None


def setUpModule():
    """
    Redirect database.py to an isolated temporary database.
    We patch both the config module attributes AND the module-level
    constants that database.py imported from config at load time.
    """
    global _TEST_DIR
    _TEST_DIR = tempfile.mkdtemp(prefix="civicai_test_")
    test_db = os.path.join(_TEST_DIR, "test_civicai.db")

    # Patch config (for any future dynamic lookups)
    _config.DATABASE_DIR  = _TEST_DIR
    _config.DATABASE_PATH = test_db

    # Patch database module's own references (captured at import time)
    db.DATABASE_DIR  = _TEST_DIR
    db.DATABASE_PATH = test_db


def tearDownModule():
    """Remove the temporary directory after all tests."""
    global _TEST_DIR
    if _TEST_DIR and os.path.exists(_TEST_DIR):
        shutil.rmtree(_TEST_DIR)


class TestDatabaseConnection(unittest.TestCase):
    """Test that we can open and close a database connection."""

    def test_get_connection_returns_connection(self):
        """get_connection() should return a sqlite3.Connection object."""
        conn = db.get_connection()
        self.assertIsInstance(conn, sqlite3.Connection)
        conn.close()

    def test_row_factory_is_set(self):
        """Rows should behave like dicts (sqlite3.Row factory)."""
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1 AS value;")
        row = cur.fetchone()
        self.assertEqual(row["value"], 1)
        conn.close()

    def test_foreign_keys_enabled(self):
        """PRAGMA foreign_keys should be ON (returns 1)."""
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys;")
        result = cur.fetchone()
        self.assertEqual(result[0], 1, "Foreign key enforcement must be ON")
        conn.close()

    def test_close_connection_safe(self):
        """close_connection() should not raise when called on an open or closed conn."""
        conn = db.get_connection()
        db.close_connection(conn)   # first close – should not raise
        db.close_connection(conn)   # second close – should not raise


class TestTableCreation(unittest.TestCase):
    """Test that init_db() creates all six expected tables."""

    EXPECTED_TABLES = {
        "departments",
        "officers",
        "complaints",
        "status_history",
        "duplicate_links",
        "action_notes",
    }

    @classmethod
    def setUpClass(cls):
        db.init_db()

    def _get_table_names(self):
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        names = {row["name"] for row in cur.fetchall()}
        conn.close()
        return names

    def test_all_tables_exist(self):
        tables = self._get_table_names()
        for t in self.EXPECTED_TABLES:
            with self.subTest(table=t):
                self.assertIn(t, tables, f"Table '{t}' was not created")

    def test_complaints_columns(self):
        """complaints table must have the required columns."""
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(complaints);")
        cols = {row["name"] for row in cur.fetchall()}
        conn.close()
        required = {
            "id", "complaint_id", "title", "description", "category",
            "ai_category", "ai_summary", "image_path", "latitude", "longitude",
            "address", "priority_score", "priority_level", "priority_reason",
            "status", "department_id", "assigned_officer",
            "created_at", "updated_at", "resolved_at",
        }
        missing = required - cols
        self.assertEqual(missing, set(), f"Missing columns in complaints: {missing}")

    def test_indexes_created(self):
        """At least the status index on complaints should exist."""
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='complaints';"
        )
        indexes = {row["name"] for row in cur.fetchall()}
        conn.close()
        self.assertIn(
            "idx_complaints_status", indexes,
            "Expected index idx_complaints_status not found",
        )


class TestForeignKeyEnforcement(unittest.TestCase):
    """Test that SQLite rejects FK violations when enforcement is ON."""

    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_insert_complaint_invalid_department_raises(self):
        """Inserting a complaint with a non-existent department_id must raise."""
        conn = db.get_connection()
        cur = conn.cursor()
        with self.assertRaises(sqlite3.IntegrityError):
            cur.execute(
                """INSERT INTO complaints
                   (complaint_id, title, description, category, department_id)
                   VALUES ('FK-TEST-001', 'FK test', 'FK violation test', 'Other', 99999);"""
            )
            conn.commit()
        conn.close()


class TestComplaintInsertion(unittest.TestCase):
    """Test basic CRUD operations on the complaints table."""

    @classmethod
    def setUpClass(cls):
        db.init_db()
        db.seed_departments()
        # Look up a real department id
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM departments LIMIT 1;")
        row = cur.fetchone()
        conn.close()
        cls.dept_id = row["id"] if row else None

    def test_insert_and_fetch_complaint(self):
        """A complaint inserted via parameterised SQL must be retrievable."""
        cid = "TEST-CMP-0001"
        with db.db_cursor() as (conn, cur):
            cur.execute(
                """INSERT OR IGNORE INTO complaints
                   (complaint_id, title, description, category, department_id)
                   VALUES (?, ?, ?, ?, ?);""",
                (cid, "Test road pothole", "Large pothole on test street.", "Road Damage", self.dept_id),
            )
        row = db.get_complaint_by_id(cid)
        self.assertIsNotNone(row, "Inserted complaint not found")
        self.assertEqual(row["title"], "Test road pothole")
        self.assertEqual(row["status"], "Submitted")

    def test_complaint_defaults(self):
        """priority_score and status defaults must be applied on insertion."""
        cid = "TEST-CMP-0002"
        with db.db_cursor() as (conn, cur):
            cur.execute(
                """INSERT OR IGNORE INTO complaints
                   (complaint_id, title, description, category)
                   VALUES (?, ?, ?, ?);""",
                (cid, "Default test", "Testing default values.", "Other"),
            )
        row = db.get_complaint_by_id(cid)
        self.assertIsNotNone(row)
        self.assertEqual(row["priority_score"], 0.0)
        self.assertEqual(row["priority_level"], "Low")
        self.assertEqual(row["status"], "Submitted")


class TestUniqueComplaintID(unittest.TestCase):
    """Test that duplicate complaint_ids are rejected."""

    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_duplicate_complaint_id_raises(self):
        """Inserting the same complaint_id twice must raise IntegrityError."""
        cid = "UNIQUE-TEST-0001"
        sql = """INSERT INTO complaints
                 (complaint_id, title, description, category)
                 VALUES (?, ?, ?, ?);"""
        with db.db_cursor() as (conn, cur):
            cur.execute(sql, (cid, "First entry", "First.", "Other"))

        with self.assertRaises(sqlite3.IntegrityError):
            with db.db_cursor() as (conn, cur):
                cur.execute(sql, (cid, "Second entry", "Second.", "Other"))


class TestStatusHistoryInsertion(unittest.TestCase):
    """Test inserting status history records."""

    @classmethod
    def setUpClass(cls):
        db.init_db()
        cid = "SH-TEST-0001"
        with db.db_cursor() as (conn, cur):
            cur.execute(
                """INSERT OR IGNORE INTO complaints
                   (complaint_id, title, description, category)
                   VALUES (?, ?, ?, ?);""",
                (cid, "Status history test complaint", "Testing status history.", "Other"),
            )
        cls.cid = cid

    def test_insert_status_history(self):
        """insert_status_history() must persist a row fetchable by complaint_id."""
        db.insert_status_history(
            self.cid,
            old_status="Submitted",
            new_status="Under Review",
            action_note="Escalated for review",
        )
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM status_history WHERE complaint_id = ? ORDER BY id DESC LIMIT 1;",
            (self.cid,),
        )
        row = cur.fetchone()
        conn.close()
        self.assertIsNotNone(row, "Status history row not found")
        self.assertEqual(row["new_status"], "Under Review")
        self.assertEqual(row["old_status"], "Submitted")

    def test_status_history_fk_invalid_complaint(self):
        """Inserting status history for a non-existent complaint_id must raise."""
        conn = db.get_connection()
        cur = conn.cursor()
        with self.assertRaises(sqlite3.IntegrityError):
            cur.execute(
                """INSERT INTO status_history (complaint_id, new_status)
                   VALUES ('NON-EXISTENT-99', 'Under Review');"""
            )
            conn.commit()
        conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
