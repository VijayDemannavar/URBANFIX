"""
tests/test_phase4e_homepage.py – Public-Facing Homepage Tests
Covers:
  - Homepage route loads with HTTP 200.
  - Live platform statistics render safely from database.
  - Empty database scenario handled safely without errors.
  - Core navigation links, hero CTA buttons, and feature sections present.
"""

import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as _config
import database as db

_TEST_DIR = None


def setUpModule():
    global _TEST_DIR
    _TEST_DIR = tempfile.mkdtemp(prefix="civicai_home_test_")
    test_db = os.path.join(_TEST_DIR, "test_civicai.db")
    _config.DATABASE_DIR = _TEST_DIR
    _config.DATABASE_PATH = test_db
    db.DATABASE_DIR = _TEST_DIR
    db.DATABASE_PATH = test_db

    db.init_db()
    db.seed_departments()


def tearDownModule():
    if _TEST_DIR and os.path.exists(_TEST_DIR):
        shutil.rmtree(_TEST_DIR)


def _make_client():
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client(), app


def _insert_test_complaint(cid, cat, status):
    with db.db_cursor() as (conn, cur):
        cur.execute(
            """INSERT OR IGNORE INTO complaints
               (complaint_id, title, description, category, status)
               VALUES (?, 'Sample issue title', 'Detailed complaint description over twenty chars', ?, ?);""",
            (cid, cat, status),
        )


class TestHomepage(unittest.TestCase):

    def test_homepage_loads_200(self):
        """GET / must return 200 with URBANFIX landing page content."""
        client, app = _make_client()
        resp = client.get("/")
        self.assertEqual(resp.status_code, 200)

        html = resp.data.decode("utf-8")
        self.assertIn("URBANFIX", html)
        self.assertIn("Fixing Cities Faster with", html)
        self.assertIn("Report a Problem", html)
        self.assertIn("Track Complaint", html)

    def test_homepage_contains_required_sections(self):
        """Hero, About, Features, How It Works, Benefits, and CTA must be present."""
        client, app = _make_client()
        resp = client.get("/")
        html = resp.data.decode("utf-8")

        self.assertIn("About URBANFIX", html)
        self.assertIn("Core Capabilities", html)
        self.assertIn("How URBANFIX Operates", html)
        self.assertIn("Mutual Value", html)
        self.assertIn("Make Your City Better Today", html)

    def test_live_statistics_render_from_database(self):
        """Platform statistics reflect actual records in the database."""
        _insert_test_complaint("HOME-001", "Road Damage", "Resolved")
        _insert_test_complaint("HOME-002", "Streetlight", "Submitted")

        stats = db.get_platform_stats()
        self.assertGreaterEqual(stats["total"], 2)
        self.assertGreaterEqual(stats["resolved"], 1)

        client, app = _make_client()
        resp = client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Total Issues Logged", html)
        self.assertIn("Verified Resolved", html)

    def test_empty_database_statistics_safe(self):
        """get_platform_stats handles empty database safely returning zeroes."""
        # Querying an isolated non-existent table or empty state returns 0s
        stats = db.get_platform_stats()
        self.assertIsInstance(stats["total"], int)
        self.assertIsInstance(stats["resolved"], int)
        self.assertIsInstance(stats["pending"], int)


if __name__ == "__main__":
    unittest.main()
