"""
tests/test_security.py – CivicAI Phase 4D Security Tests

Covers:
  4D-1 – Citizen CSRF protection:
    - Valid CSRF token accepted on submit POST
    - Invalid CSRF token rejected (403)
    - Missing CSRF token rejected (403)

  4D-2 – Admin write-route CSRF:
    - Valid token accepted on /update
    - Invalid token rejected on /update
    - Valid token accepted on /add_note
    - Invalid token rejected on /add_note

  4D-3 – Admin authentication modes:
    - "open" mode: all admin routes accessible without credentials
    - "password" mode: correct credentials admitted (200)
    - "password" mode: wrong password rejected (401)
    - "password" mode: missing Authorization header rejected (401)
    - "password" mode: WWW-Authenticate header present on 401
    - "disabled" mode: all admin routes return 503

  4D-4 – Startup validation:
    - "password" mode without a password raises RuntimeError
    - Unknown mode raises RuntimeError
    - "open" mode with no password is fine
    - "disabled" mode is fine
    - TESTING flag skips validation entirely

  Regressions:
    - All existing dashboard / detail / hotspot routes still work in open mode
    - Submit route still works with TESTING=True (bypasses CSRF)
"""

import base64
import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as _config
import database as db

# ── Shared test DB setup ───────────────────────────────────────────────────────

_TEST_DIR   = None
_UPLOAD_DIR = None


def setUpModule():
    global _TEST_DIR, _UPLOAD_DIR
    _TEST_DIR   = tempfile.mkdtemp(prefix="civicai_sec_test_")
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_app(testing=True, auth_mode="open", password=""):
    """
    Create a test Flask application.

    When ``testing=True`` all CSRF and auth guards are bypassed, matching the
    behaviour of every other test file.  Set ``testing=False`` to exercise the
    real enforcement paths.
    """
    from app import create_app
    app = create_app(admin_auth_mode=auth_mode, admin_password=password)
    app.config["TESTING"] = testing
    return app


def _insert(cid, title, desc=None, cat="Road Damage"):
    desc = desc or "Test description that is at least twenty characters long."
    with db.db_cursor() as (conn, cur):
        cur.execute(
            """INSERT OR IGNORE INTO complaints
               (complaint_id, title, description, category)
               VALUES (?, ?, ?, ?);""",
            (cid, title, desc, cat),
        )


def _basic_auth_header(password: str, username: str = "admin") -> str:
    """Return a valid HTTP Basic Auth header value."""
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {credentials}"


# ──────────────────────────────────────────────────────────────────────────────
# 1. CITIZEN CSRF PROTECTION (4D-1)
# ──────────────────────────────────────────────────────────────────────────────

class TestCitizenCSRF(unittest.TestCase):
    """
    Verify CSRF protection on the citizen complaint submission POST.

    These tests use TESTING=False to exercise the real enforcement path.
    A valid CSRF token is obtained from the GET form response.
    """

    @classmethod
    def setUpClass(cls):
        cls.app    = _make_app(testing=False, auth_mode="open")
        cls.client = cls.app.test_client()
        # Ensure the session is live before we try to POST
        cls.client.get("/submit/")

    def _valid_post(self, extra=None):
        """Submit a valid complaint with a fresh CSRF token."""
        # Fetch a fresh form to get a valid session + token
        with self.app.test_client() as c:
            get_resp = c.get("/submit/")
            self.assertEqual(get_resp.status_code, 200)
            # Extract token from rendered HTML
            html  = get_resp.data.decode()
            token = _extract_csrf_token(html)
            data  = {
                "title":       "Pothole on main road near bus stand entrance area",
                "description": "A very large pothole has caused several accidents already.",
                "category":    "Road Damage",
                "address":     "Bus Stand Road, Novapolis",
                "latitude":    "",
                "longitude":   "",
                "csrf_token":  token,
            }
            if extra:
                data.update(extra)
            return c.post(
                "/submit/",
                data=data,
                content_type="multipart/form-data",
                follow_redirects=False,
            )

    def test_valid_csrf_token_accepted(self):
        """Submit with a correct CSRF token must succeed (302 redirect)."""
        resp = self._valid_post()
        self.assertIn(resp.status_code, (302, 200),
                      f"Valid CSRF submit failed with {resp.status_code}")
        # A 422 would mean form validation error, not a CSRF failure
        self.assertNotEqual(resp.status_code, 403, "Valid CSRF token wrongly rejected")

    def test_invalid_csrf_token_rejected(self):
        """Submit with a wrong CSRF token must return 403."""
        with self.app.test_client() as c:
            c.get("/submit/")  # establish session
            resp = c.post(
                "/submit/",
                data={
                    "title":       "Pothole near park entrance area test road",
                    "description": "A very large pothole has caused several accidents.",
                    "category":    "Road Damage",
                    "csrf_token":  "this-is-not-the-right-token",
                },
                content_type="multipart/form-data",
            )
        self.assertEqual(resp.status_code, 403,
                         "Invalid CSRF token not rejected with 403")

    def test_missing_csrf_token_rejected(self):
        """Submit without a CSRF token field must return 403."""
        with self.app.test_client() as c:
            c.get("/submit/")  # establish session
            resp = c.post(
                "/submit/",
                data={
                    "title":       "Pothole near park entrance area test road",
                    "description": "A very large pothole has caused several accidents.",
                    "category":    "Road Damage",
                    # csrf_token deliberately omitted
                },
                content_type="multipart/form-data",
            )
        self.assertEqual(resp.status_code, 403,
                         "Missing CSRF token not rejected with 403")

    def test_csrf_bypass_in_testing_mode(self):
        """TESTING=True must bypass CSRF so existing test suites pass."""
        app = _make_app(testing=True, auth_mode="open")
        with app.test_client() as c:
            resp = c.post(
                "/submit/",
                data={
                    "title":       "Pothole near park entrance area test road",
                    "description": "A very large pothole has caused several accidents.",
                    "category":    "Road Damage",
                    # No csrf_token
                },
                content_type="multipart/form-data",
                follow_redirects=False,
            )
        # Should redirect (302) or re-render form (422) but NOT 403
        self.assertNotEqual(resp.status_code, 403,
                            "CSRF check incorrectly fires when TESTING=True")


# ──────────────────────────────────────────────────────────────────────────────
# 2. ADMIN WRITE-ROUTE CSRF (4D-2)
# ──────────────────────────────────────────────────────────────────────────────

class TestAdminWriteCSRF(unittest.TestCase):
    """
    Verify CSRF protection on admin POST routes /update and /add_note.

    Uses TESTING=False so the real guard fires.
    """

    @classmethod
    def setUpClass(cls):
        cls.app    = _make_app(testing=False, auth_mode="open")
        cls.client = cls.app.test_client()
        _insert("SEC-CSRF-001", "CSRF test complaint for admin write route check")

    def _post_update(self, token):
        return self.client.post(
            "/admin/complaint/SEC-CSRF-001/update",
            data={"new_status": "Under Review", "csrf_token": token},
            content_type="multipart/form-data",
        )

    def _post_add_note(self, token):
        return self.client.post(
            "/admin/complaint/SEC-CSRF-001/add_note",
            data={"note": "Test note content.", "csrf_token": token},
            content_type="multipart/form-data",
        )

    # ── /update ──────────────────────────────────────────────────────

    def test_update_invalid_token_rejected(self):
        """POST /update with wrong token must return 403."""
        resp = self._post_update("bad-token-value")
        self.assertEqual(resp.status_code, 403)

    def test_update_missing_token_rejected(self):
        """POST /update with no token field must return 403."""
        with self.app.test_client() as c:
            c.get("/admin/")  # establish session
            resp = c.post(
                "/admin/complaint/SEC-CSRF-001/update",
                data={"new_status": "Under Review"},
                content_type="multipart/form-data",
            )
        self.assertEqual(resp.status_code, 403)

    def test_update_valid_token_accepted(self):
        """POST /update with a correct token must not return 403."""
        with self.app.test_client() as c:
            # Get a real session token from the detail page
            c.get("/admin/complaint/SEC-CSRF-001")
            # Now get the dashboard to extract token from HTML
            html  = c.get("/admin/").data.decode()
            token = _extract_csrf_token(html)
            if not token:
                # token may be in the detail page
                html  = c.get("/admin/complaint/SEC-CSRF-001").data.decode()
                token = _extract_csrf_token(html)
            resp = c.post(
                "/admin/complaint/SEC-CSRF-001/update",
                data={"new_status": "Under Review", "csrf_token": token},
                content_type="multipart/form-data",
            )
        self.assertNotEqual(resp.status_code, 403,
                            "Valid CSRF token wrongly rejected on /update")

    # ── /add_note ─────────────────────────────────────────────────────

    def test_add_note_invalid_token_rejected(self):
        """POST /add_note with wrong token must return 403."""
        resp = self._post_add_note("bad-token-value")
        self.assertEqual(resp.status_code, 403)

    def test_add_note_missing_token_rejected(self):
        """POST /add_note with no token field must return 403."""
        with self.app.test_client() as c:
            c.get("/admin/")
            resp = c.post(
                "/admin/complaint/SEC-CSRF-001/add_note",
                data={"note": "Test note content."},
                content_type="multipart/form-data",
            )
        self.assertEqual(resp.status_code, 403)

    def test_add_note_valid_token_accepted(self):
        """POST /add_note with a correct token must not return 403."""
        with self.app.test_client() as c:
            html  = c.get("/admin/complaint/SEC-CSRF-001").data.decode()
            token = _extract_csrf_token(html)
            resp = c.post(
                "/admin/complaint/SEC-CSRF-001/add_note",
                data={"note": "Test note content.", "csrf_token": token},
                content_type="multipart/form-data",
            )
        self.assertNotEqual(resp.status_code, 403,
                            "Valid CSRF token wrongly rejected on /add_note")


# ──────────────────────────────────────────────────────────────────────────────
# 3. ADMIN AUTHENTICATION — OPEN MODE (4D-3)
# ──────────────────────────────────────────────────────────────────────────────

class TestAdminAuthOpen(unittest.TestCase):
    """Verify that 'open' mode allows all admin routes without credentials."""

    @classmethod
    def setUpClass(cls):
        cls.app    = _make_app(testing=False, auth_mode="open")
        cls.client = cls.app.test_client()
        _insert("SEC-OPEN-001", "Open auth test complaint for admin dashboard route")

    def test_dashboard_accessible_without_credentials(self):
        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 200)

    def test_detail_accessible_without_credentials(self):
        resp = self.client.get("/admin/complaint/SEC-OPEN-001")
        self.assertEqual(resp.status_code, 200)

    def test_hotspots_accessible_without_credentials(self):
        resp = self.client.get("/admin/hotspots")
        self.assertEqual(resp.status_code, 200)


# ──────────────────────────────────────────────────────────────────────────────
# 4. ADMIN AUTHENTICATION — PASSWORD MODE (4D-3)
# ──────────────────────────────────────────────────────────────────────────────

_TEST_PASSWORD = "s3cr3t-test-pass"


class TestAdminAuthPassword(unittest.TestCase):
    """Verify HTTP Basic Auth enforcement in 'password' mode."""

    @classmethod
    def setUpClass(cls):
        cls.app    = _make_app(testing=False, auth_mode="password",
                               password=_TEST_PASSWORD)
        cls.client = cls.app.test_client()
        _insert("SEC-PW-001", "Password auth test complaint for admin dashboard route")

    def _get(self, path, password=None, username="admin"):
        headers = {}
        if password is not None:
            headers["Authorization"] = _basic_auth_header(password, username)
        return self.client.get(path, headers=headers)

    # ── Correct credentials ───────────────────────────────────────────

    def test_dashboard_correct_password_admitted(self):
        resp = self._get("/admin/", password=_TEST_PASSWORD)
        self.assertEqual(resp.status_code, 200)

    def test_detail_correct_password_admitted(self):
        resp = self._get("/admin/complaint/SEC-PW-001", password=_TEST_PASSWORD)
        self.assertEqual(resp.status_code, 200)

    def test_hotspots_correct_password_admitted(self):
        resp = self._get("/admin/hotspots", password=_TEST_PASSWORD)
        self.assertEqual(resp.status_code, 200)

    # ── Wrong credentials ─────────────────────────────────────────────

    def test_dashboard_wrong_password_rejected(self):
        resp = self._get("/admin/", password="wrong-password")
        self.assertEqual(resp.status_code, 401)

    def test_detail_wrong_password_rejected(self):
        resp = self._get("/admin/complaint/SEC-PW-001", password="wrong-password")
        self.assertEqual(resp.status_code, 401)

    # ── Missing credentials ───────────────────────────────────────────

    def test_dashboard_no_credentials_rejected(self):
        resp = self._get("/admin/")
        self.assertEqual(resp.status_code, 401)

    def test_dashboard_no_credentials_has_www_authenticate(self):
        """401 response must include WWW-Authenticate header."""
        resp = self._get("/admin/")
        self.assertIn("WWW-Authenticate", resp.headers,
                      "WWW-Authenticate header missing from 401 response")
        self.assertIn("Basic", resp.headers["WWW-Authenticate"])

    # ── Non-admin routes unaffected ───────────────────────────────────

    def test_submit_form_unaffected_by_admin_auth(self):
        """Citizen submit form must be accessible regardless of admin auth mode."""
        resp = self.client.get("/submit/")
        self.assertEqual(resp.status_code, 200)

    def test_home_page_unaffected_by_admin_auth(self):
        """Home page must load regardless of admin auth mode."""
        resp = self.client.get("/", follow_redirects=False)
        self.assertEqual(resp.status_code, 200)


# ──────────────────────────────────────────────────────────────────────────────
# 5. ADMIN AUTHENTICATION — DISABLED MODE (4D-3)
# ──────────────────────────────────────────────────────────────────────────────

class TestAdminAuthDisabled(unittest.TestCase):
    """Verify that 'disabled' mode returns 503 for all admin routes."""

    @classmethod
    def setUpClass(cls):
        cls.app    = _make_app(testing=False, auth_mode="disabled")
        cls.client = cls.app.test_client()

    def test_dashboard_returns_503(self):
        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 503)

    def test_detail_returns_503(self):
        resp = self.client.get("/admin/complaint/ANYTHING")
        self.assertEqual(resp.status_code, 503)

    def test_hotspots_returns_503(self):
        resp = self.client.get("/admin/hotspots")
        self.assertEqual(resp.status_code, 503)

    def test_submit_form_unaffected(self):
        """Disabled admin must not block the citizen form."""
        resp = self.client.get("/submit/")
        self.assertEqual(resp.status_code, 200)


# ──────────────────────────────────────────────────────────────────────────────
# 6. STARTUP VALIDATION (4D-4)
# ──────────────────────────────────────────────────────────────────────────────

class TestStartupValidation(unittest.TestCase):
    """
    Verify that _validate_admin_auth_config raises RuntimeError for unsafe
    or incomplete configuration.
    """

    def _validate(self, mode, password=""):
        from app import _validate_admin_auth_config
        _validate_admin_auth_config(mode, password)

    def test_password_mode_without_password_raises(self):
        """'password' mode must raise if env var is empty."""
        with self.assertRaises(RuntimeError) as ctx:
            self._validate("password", "")
        self.assertIn("CIVICAI_ADMIN_PASSWORD", str(ctx.exception))

    def test_unknown_mode_raises(self):
        """An unrecognised auth mode must raise RuntimeError."""
        with self.assertRaises(RuntimeError) as ctx:
            self._validate("magic")
        self.assertIn("magic", str(ctx.exception))

    def test_open_mode_no_password_is_valid(self):
        """'open' mode without a password must NOT raise."""
        self._validate("open", "")   # should not raise

    def test_disabled_mode_is_valid(self):
        """'disabled' mode must not raise regardless of password."""
        self._validate("disabled", "")

    def test_password_mode_with_password_is_valid(self):
        """'password' mode with a non-empty password must not raise."""
        self._validate("password", "my-secret")

    def test_testing_flag_skips_request_time_guards(self):
        """
        TESTING=True bypasses CSRF and auth *at request time*, not at factory time.
        Factory-time validation always runs so misconfigurations are caught early.
        A test app should use a valid config and set TESTING=True afterward.
        """
        from app import create_app
        # Valid factory config (open mode — no password needed)
        app = create_app(admin_auth_mode="open", admin_password="")
        app.config["TESTING"] = True
        # Verify TESTING flag is in effect and requests bypass auth guards
        with app.test_client() as c:
            resp = c.get("/admin/")
        self.assertEqual(resp.status_code, 200,
                         "TESTING=True should allow /admin/ without credentials")

    def test_create_app_password_mode_without_password_raises(self):
        """create_app itself must raise for 'password' mode with empty password."""
        from app import create_app
        with self.assertRaises(RuntimeError):
            create_app(admin_auth_mode="password", admin_password="")


# ──────────────────────────────────────────────────────────────────────────────
# 7. REGRESSION — existing functionality unaffected (4D)
# ──────────────────────────────────────────────────────────────────────────────

class TestPhase4DRegressions(unittest.TestCase):
    """
    Verify all existing features still work after Phase 4D changes.
    Uses TESTING=True (standard) so all guards are bypassed as before.
    """

    @classmethod
    def setUpClass(cls):
        app = _make_app(testing=True, auth_mode="open")
        cls.client = app.test_client()
        _insert("SEC-REG-001", "Regression check complaint for Phase 4D testing run")

    def test_dashboard_returns_200(self):
        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 200)

    def test_detail_returns_200(self):
        resp = self.client.get("/admin/complaint/SEC-REG-001")
        self.assertEqual(resp.status_code, 200)

    def test_hotspots_returns_200(self):
        resp = self.client.get("/admin/hotspots")
        self.assertEqual(resp.status_code, 200)

    def test_submit_form_returns_200(self):
        resp = self.client.get("/submit/")
        self.assertEqual(resp.status_code, 200)

    def test_submit_post_accepted_in_testing_mode(self):
        """Without CSRF token, submit must still work in TESTING=True mode."""
        resp = self.client.post(
            "/submit/",
            data={
                "title":       "Road pothole near entrance of school compound area",
                "description": "A very large pothole has formed near the school.",
                "category":    "Road Damage",
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertNotEqual(resp.status_code, 403)
        self.assertIn(resp.status_code, (302, 200))

    def test_admin_write_update_works_in_testing_mode(self):
        resp = self.client.post(
            "/admin/complaint/SEC-REG-001/update",
            data={"new_status": "Under Review"},
            content_type="multipart/form-data",
        )
        self.assertNotEqual(resp.status_code, 403)

    def test_admin_write_note_works_in_testing_mode(self):
        resp = self.client.post(
            "/admin/complaint/SEC-REG-001/add_note",
            data={"note": "Regression note content."},
            content_type="multipart/form-data",
        )
        self.assertNotEqual(resp.status_code, 403)

    def test_priority_score_out_of_100(self):
        resp = self.client.get("/admin/complaint/SEC-REG-001")
        self.assertIn(b"/ 100", resp.data)

    def test_gps_button_present(self):
        resp = self.client.get("/submit/")
        self.assertIn(b"Use My Location", resp.data)

    def test_csrf_token_in_submit_form(self):
        """CSRF hidden input must be present in the submit form."""
        resp = self.client.get("/submit/")
        self.assertIn(b'name="csrf_token"', resp.data)

    def test_csrf_token_in_admin_detail_forms(self):
        """CSRF hidden inputs must be present on the admin detail page."""
        resp = self.client.get("/admin/complaint/SEC-REG-001")
        self.assertIn(b'name="csrf_token"', resp.data)


# ──────────────────────────────────────────────────────────────────────────────
# Utility
# ──────────────────────────────────────────────────────────────────────────────

def _extract_csrf_token(html: str) -> str:
    """
    Extract the CSRF token value from a rendered HTML page.
    Looks for: <input type="hidden" name="csrf_token" value="...">
    Returns an empty string if not found.
    """
    import re
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    if m:
        return m.group(1)
    # Also try the reverse attribute order
    m = re.search(r'value="([^"]+)"\s+name="csrf_token"', html)
    return m.group(1) if m else ""


if __name__ == "__main__":
    unittest.main(verbosity=2)
