import os
import sys
import tempfile
import shutil
import unittest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as _config
import database as db

# Setup temporary DB and upload dir (same as test_routes)
_TEST_DIR = None
_UPLOAD_DIR = None


def setUpModule():
    global _TEST_DIR, _UPLOAD_DIR
    _TEST_DIR = tempfile.mkdtemp(prefix="civicai_track_test_")
    _UPLOAD_DIR = os.path.join(_TEST_DIR, "uploads")
    os.makedirs(_UPLOAD_DIR, exist_ok=True)

    test_db = os.path.join(_TEST_DIR, "test_civicai_track.db")

    # Redirect config
    _config.DATABASE_DIR = _TEST_DIR
    _config.DATABASE_PATH = test_db
    _config.UPLOAD_DIR = _UPLOAD_DIR

    # Redirect database module references
    db.DATABASE_DIR = _TEST_DIR
    db.DATABASE_PATH = test_db

    # Initialise DB
    db.init_db()
    db.seed_departments()

    # Patch submit blueprint's UPLOAD_DIR (imported at load time)
    import routes.submit as rs
    rs.UPLOAD_DIR = _UPLOAD_DIR


def tearDownModule():
    global _TEST_DIR
    if _TEST_DIR and os.path.exists(_TEST_DIR):
        shutil.rmtree(_TEST_DIR)


def _make_client():
    from app import create_app
    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    application.config["UPLOAD_DIR"] = _UPLOAD_DIR
    return application.test_client(), application

class TestComplaintTracking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()

    def _submit_complaint(self, **overrides):
        data = {
            "title": "Broken streetlight on Main St",
            "description": "The streetlight flickers and sometimes turns off completely.",
            "category": "Streetlight",
            "address": "Main St, Test City",
            "latitude": "",
            "longitude": "",
        }
        data.update(overrides)
        return self.client.post(
            "/submit/",
            data=data,
            follow_redirects=False,
            content_type="multipart/form-data",
        )

    def test_get_track_form(self):
        resp = self.client.get("/submit/track")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Track Your Complaint", resp.data)

    def test_valid_tracking_shows_details_and_history(self):
        # Submit a complaint first
        post_resp = self._submit_complaint()
        self.assertEqual(post_resp.status_code, 302)
        complaint_id = post_resp.headers["Location"].split("/submit/success/")[-1].rstrip("/")

        # Track it
        resp = self.client.post(
            "/submit/track",
            data={"complaint_id": complaint_id},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 200)
        # Complaint details present
        self.assertIn(complaint_id.encode(), resp.data)
        self.assertIn(b"Broken streetlight on Main St", resp.data)
        # Status history entry should be present (Submitted)
        self.assertIn(b"Submitted", resp.data)
        # Ensure no admin‑only fields leak
        self.assertNotIn(b"action_note", resp.data)
        self.assertNotIn(b"ai_explanation", resp.data)

    def test_invalid_id_shows_not_found(self):
        resp = self.client.post(
            "/submit/track",
            data={"complaint_id": "NONEXISTENT-1234"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 404)
        self.assertIn(b"not found", resp.data.lower())

if __name__ == "__main__":
    unittest.main()
