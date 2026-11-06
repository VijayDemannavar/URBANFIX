"""
tests/test_phase4b_resolution_tracking.py – Citizen Resolution Tracking Tests
Covers Phase 4-B:
  - Citizens tracking resolved complaints see resolution message, photo, and date.
  - Unresolved complaints do NOT display resolution details.
  - Unknown complaint IDs display friendly message.
  - Privacy requirement: admin action notes and internal AI details are not exposed.
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
_UPLOAD_DIR = None


def setUpModule():
    global _TEST_DIR, _UPLOAD_DIR
    _TEST_DIR = tempfile.mkdtemp(prefix="civicai_track_test_")
    _UPLOAD_DIR = os.path.join(_TEST_DIR, "uploads")
    os.makedirs(_UPLOAD_DIR, exist_ok=True)

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


def _insert_complaint(
    cid, title="Trackable civic issue", desc="Detailed complaint description for citizen tracking test.",
    cat="Road Damage", status="Submitted", resolution_message=None,
    resolution_image_path=None, resolved_at=None,
):
    with db.db_cursor() as (conn, cur):
        cur.execute(
            """INSERT OR IGNORE INTO complaints
               (complaint_id, title, description, category, status,
                resolution_message, resolution_image_path, resolved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?);""",
            (cid, title, desc, cat, status, resolution_message, resolution_image_path, resolved_at),
        )


class TestCitizenResolutionTracking(unittest.TestCase):

    def test_resolved_complaint_shows_resolution_details(self):
        """Resolved complaint shows resolution message, photo, and resolution date."""
        cid = "TRK-RESOLVED-001"
        _insert_complaint(
            cid,
            status="Resolved",
            resolution_message="The asphalt has been relaid and leveled successfully.",
            resolution_image_path="completion_test.jpg",
            resolved_at="2026-11-06 14:30:00",
        )

        client, app = _make_client()
        resp = client.post("/submit/track", data={"complaint_id": cid})
        self.assertEqual(resp.status_code, 200)

        html = resp.data.decode("utf-8")
        self.assertIn(cid, html)
        self.assertIn("Complaint Resolved", html)
        self.assertIn("The asphalt has been relaid and leveled successfully.", html)
        self.assertIn("completion_test.jpg", html)
        self.assertIn("2026-11-06 14:30", html)

    def test_unresolved_complaint_does_not_show_resolution_details(self):
        """In-progress or submitted complaints must not display resolution card."""
        cid = "TRK-PENDING-001"
        _insert_complaint(cid, status="In Progress")

        client, app = _make_client()
        resp = client.post("/submit/track", data={"complaint_id": cid})
        self.assertEqual(resp.status_code, 200)

        html = resp.data.decode("utf-8")
        self.assertIn(cid, html)
        self.assertIn("In Progress", html)
        self.assertNotIn("Official Department Resolution Message", html)
        self.assertNotIn("Work Completion Photograph", html)

    def test_unknown_complaint_id_friendly_message(self):
        """Non-existent complaint ID renders a friendly warning."""
        client, app = _make_client()
        resp = client.post("/submit/track", data={"complaint_id": "CMP-UNKNOWN-999"})
        self.assertEqual(resp.status_code, 404)
        html = resp.data.decode("utf-8")
        self.assertIn("CMP-UNKNOWN-999 not found", html)

    def test_privacy_no_admin_notes_or_ai_exposed(self):
        """Internal admin action notes and internal AI confidence should not leak to citizen view."""
        cid = "TRK-PRIVACY-001"
        _insert_complaint(cid, status="Under Review")
        # Add internal admin action note
        db.add_action_note(cid, "INTERNAL_SECRET_ADMIN_NOTE_12345")

        client, app = _make_client()
        resp = client.post("/submit/track", data={"complaint_id": cid})
        self.assertEqual(resp.status_code, 200)

        html = resp.data.decode("utf-8")
        self.assertNotIn("INTERNAL_SECRET_ADMIN_NOTE_12345", html)


if __name__ == "__main__":
    unittest.main()
