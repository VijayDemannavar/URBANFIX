"""
tests/test_admin_resolution.py – Phase 4-A Admin Resolution System Tests

Covers:
  1. Saving a resolution message and verifying the database value.
  2. Uploading a valid completion photo and verifying the stored file.
  3. Rejecting an invalid image upload (wrong extension).
  4. Normal status updates still working alongside resolution fields.
  5. Existing resolution data preserved when no replacement is submitted.
  6. Authorization (admin disabled mode) and CSRF protection.

All tests use a fresh temp database seeded per module.
"""

import io
import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as _config
import database as db

# ── Temp DB setup (same pattern as test_admin_writes.py) ──────────────────────

_TEST_DIR   = None
_UPLOAD_DIR = None


def setUpModule():
    global _TEST_DIR, _UPLOAD_DIR
    _TEST_DIR   = tempfile.mkdtemp(prefix="civicai_res_test_")
    _UPLOAD_DIR = os.path.join(_TEST_DIR, "uploads")
    os.makedirs(_UPLOAD_DIR, exist_ok=True)

    test_db = os.path.join(_TEST_DIR, "test_civicai.db")
    _config.DATABASE_DIR  = _TEST_DIR
    _config.DATABASE_PATH = test_db
    db.DATABASE_DIR  = _TEST_DIR
    db.DATABASE_PATH = test_db

    db.init_db()
    db.seed_departments()

    import routes.submit as rs
    rs.UPLOAD_DIR = _UPLOAD_DIR


def tearDownModule():
    if _TEST_DIR and os.path.exists(_TEST_DIR):
        shutil.rmtree(_TEST_DIR)


def _make_client(testing=True):
    from app import create_app
    app = create_app()
    app.config["TESTING"] = testing
    return app.test_client(), app


def _insert(cid, title="Resolution test complaint title",
            desc="Test description that is at least twenty characters long.",
            cat="Road Damage", status="Submitted",
            resolution_message=None, resolution_image_path=None):
    """Insert a complaint, optionally with existing resolution data."""
    with db.db_cursor() as (conn, cur):
        cur.execute(
            """INSERT OR IGNORE INTO complaints
               (complaint_id, title, description, category, status,
                priority_level, priority_score,
                resolution_message, resolution_image_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);""",
            (cid, title, desc, cat, status, "Low", 10.0,
             resolution_message, resolution_image_path),
        )


def _get_complaint(cid):
    return db.get_complaint_by_id(cid)


def _make_valid_image(filename="photo.jpg"):
    """Create a minimal valid JPEG file in memory."""
    # Minimal JPEG: SOI + APP0 + EOI
    jpeg_bytes = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01"
        b"\x00\x01\x00\x00\xff\xd9"
    )
    return io.BytesIO(jpeg_bytes), filename


def _make_invalid_file(filename="virus.exe"):
    """Create a file with a disallowed extension."""
    return io.BytesIO(b"MZ\x90\x00"), filename


# ──────────────────────────────────────────────────────────────────────────────
# TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestAdminResolution(unittest.TestCase):
    """Admin resolution system – message, photo, preservation, auth."""

    def test_save_resolution_message(self):
        """Submitting a resolution message stores it in the database."""
        cid = "RES-MSG-001"
        _insert(cid, status="In Progress")

        client, app = _make_client()
        with app.app_context():
            resp = client.post(
                f"/admin/complaint/{cid}/update",
                data={
                    "csrf_token": "bypass",
                    "resolution_message": "Pothole filled with asphalt.",
                },
                follow_redirects=False,
            )
            self.assertIn(resp.status_code, (302, 303))

            row = _get_complaint(cid)
            self.assertIsNotNone(row)
            self.assertEqual(row["resolution_message"], "Pothole filled with asphalt.")

    def test_upload_valid_completion_photo(self):
        """Uploading a valid JPEG stores the file and records its path."""
        cid = "RES-IMG-001"
        _insert(cid, status="In Progress")

        img_stream, img_name = _make_valid_image("completion.jpg")
        client, app = _make_client()
        with app.app_context():
            resp = client.post(
                f"/admin/complaint/{cid}/update",
                data={
                    "csrf_token": "bypass",
                    "resolution_image": (img_stream, img_name),
                },
                content_type="multipart/form-data",
                follow_redirects=False,
            )
            self.assertIn(resp.status_code, (302, 303))

            row = _get_complaint(cid)
            self.assertIsNotNone(row)
            self.assertIsNotNone(row["resolution_image_path"])
            # Verify the file actually exists on disk
            saved_path = os.path.join(_UPLOAD_DIR, row["resolution_image_path"])
            self.assertTrue(
                os.path.isfile(saved_path),
                f"Expected file at {saved_path}"
            )

    def test_reject_invalid_image_upload(self):
        """An invalid file extension is rejected; no DB change occurs."""
        cid = "RES-BAD-001"
        _insert(cid, status="In Progress")

        bad_stream, bad_name = _make_invalid_file("hack.exe")
        client, app = _make_client()
        with app.app_context():
            resp = client.post(
                f"/admin/complaint/{cid}/update",
                data={
                    "csrf_token": "bypass",
                    "resolution_image": (bad_stream, bad_name),
                },
                content_type="multipart/form-data",
                follow_redirects=False,
            )
            # Should return 422 (validation error) or redirect with flash
            # The route returns (redirect, 422) on validation error
            self.assertIn(resp.status_code, (302, 422))

            row = _get_complaint(cid)
            self.assertIsNone(row["resolution_image_path"])

    def test_normal_status_update_still_works(self):
        """A plain status update without resolution fields still works."""
        cid = "RES-STAT-001"
        _insert(cid, status="Submitted")

        client, app = _make_client()
        with app.app_context():
            resp = client.post(
                f"/admin/complaint/{cid}/update",
                data={
                    "csrf_token": "bypass",
                    "new_status": "In Progress",
                },
                follow_redirects=False,
            )
            self.assertIn(resp.status_code, (302, 303))

            row = _get_complaint(cid)
            self.assertEqual(row["status"], "In Progress")
            # Resolution fields should still be None
            self.assertIsNone(row["resolution_message"])
            self.assertIsNone(row["resolution_image_path"])

    def test_preserve_existing_resolution_when_no_replacement(self):
        """Existing resolution data is kept when update sends no new values."""
        cid = "RES-KEEP-001"
        _insert(
            cid,
            status="In Progress",
            resolution_message="Original fix note.",
            resolution_image_path="existing_photo.jpg",
        )

        client, app = _make_client()
        with app.app_context():
            # Submit a status update with no resolution fields at all
            resp = client.post(
                f"/admin/complaint/{cid}/update",
                data={
                    "csrf_token": "bypass",
                    "new_status": "Resolved",
                },
                follow_redirects=False,
            )
            self.assertIn(resp.status_code, (302, 303))

            row = _get_complaint(cid)
            self.assertEqual(row["status"], "Resolved")
            # Existing resolution data must be preserved
            self.assertEqual(row["resolution_message"], "Original fix note.")
            self.assertEqual(row["resolution_image_path"], "existing_photo.jpg")

    def test_csrf_protection_blocks_without_token(self):
        """Requests without a valid CSRF token are rejected (non-TESTING app)."""
        cid = "RES-CSRF-001"
        _insert(cid, status="In Progress")

        # Create a non-TESTING app so CSRF is enforced
        client, app = _make_client(testing=False)
        with app.app_context():
            resp = client.post(
                f"/admin/complaint/{cid}/update",
                data={
                    "resolution_message": "Should be blocked.",
                },
                follow_redirects=False,
            )
            # Should be 401 (admin auth) or 403 (CSRF) in non-TESTING mode
            self.assertIn(resp.status_code, (401, 403))

            # DB must not be modified
            row = _get_complaint(cid)
            self.assertIsNone(row["resolution_message"])


if __name__ == "__main__":
    unittest.main()
