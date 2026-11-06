"""
tests/test_admin_auth_and_demo.py – Unit & Regression Tests for Admin Login & Demo Mode

Verifies:
1. Admin login page rendering with URBANFIX branding, heading, inputs, show/hide toggle, and demo button.
2. Unauthenticated requests to /admin/* redirect to /admin/login in session mode.
3. Successful administrator authentication via username and password.
4. Rejection of invalid credentials with HTTP 401.
5. Rate limiting / brute-force protection after repeated failed logins.
6. One-click demo session activation without credentials.
7. Demo mode read-only permissions across dashboard, map, hotspots, and complaint detail.
8. Demo mode write protection: HTTP 403 Forbidden on status updates and action notes.
9. Full administrator write permissions for authenticated admins.
10. Safe logout functionality clearing session data.
"""

import re
import unittest
from flask import session

import database as db
from app import create_app
from routes.admin import _clear_failed_logins

_TEST_ADMIN_USER = "testadmin"
_TEST_ADMIN_PASS = "secure-test-pass-12345"


def _extract_csrf_token(html: str) -> str:
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    if m:
        return m.group(1)
    m = re.search(r'value="([^"]+)"\s+name="csrf_token"', html)
    return m.group(1) if m else ""


def _seed_test_complaint(cid="DEMO-TEST-001", title="Demo test pothole"):
    with db.db_cursor() as (conn, cur):
        cur.execute(
            """INSERT INTO complaints
               (complaint_id, title, description, category, status, priority_level, priority_score)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(complaint_id) DO UPDATE SET
                   status='Submitted',
                   title=excluded.title;""",
            (cid, title, "Test description for demo auth validation.", "Road Damage", "Submitted", "High", 70.0),
        )


class TestAdminAuthAndDemo(unittest.TestCase):
    """Test suite for Admin Login and One-Click Demo Mode."""

    def setUp(self):
        # Create app in session auth mode with TESTING=False to exercise real auth hooks
        self.app = create_app(
            admin_auth_mode="session",
            admin_password=_TEST_ADMIN_PASS,
            admin_username=_TEST_ADMIN_USER,
        )
        self.app.config["TESTING"] = False
        self.client = self.app.test_client()
        _clear_failed_logins("127.0.0.1")
        _seed_test_complaint()

    def tearDown(self):
        _clear_failed_logins("127.0.0.1")

    # ── 1. Login Page Rendering ───────────────────────────────────────────────

    def test_login_page_renders_cleanly(self):
        """GET /admin/login must return 200 with required form fields and demo button."""
        resp = self.client.get("/admin/login")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode()
        self.assertIn("Admin Portal Login", html)
        self.assertIn("URBANFIX", html)
        self.assertIn('name="username"', html)
        self.assertIn('name="password"', html)
        self.assertIn("Show", html)  # show/hide toggle
        self.assertIn("Sign In as Administrator", html)
        self.assertIn("Explore Demo", html)
        self.assertIn('action="/admin/demo"', html)

    # ── 2. Unauthenticated Redirects ──────────────────────────────────────────

    def test_unauthenticated_admin_redirects_to_login(self):
        """Unauthenticated access to /admin/ must redirect to /admin/login."""
        resp = self.client.get("/admin/", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login", resp.headers["Location"])

    def test_unauthenticated_map_redirects_to_login(self):
        """Unauthenticated access to /admin/map must redirect to /admin/login with next param."""
        resp = self.client.get("/admin/map", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login", resp.headers["Location"])
        self.assertIn("next=", resp.headers["Location"])

    def test_unauthenticated_detail_redirects_to_login(self):
        """Unauthenticated access to complaint detail must redirect to /admin/login."""
        resp = self.client.get("/admin/complaint/DEMO-TEST-001", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login", resp.headers["Location"])

    # ── 3. Administrator Login ────────────────────────────────────────────────

    def test_admin_login_success(self):
        """Valid credentials must establish admin session and redirect to dashboard."""
        with self.client as c:
            # Fetch CSRF token from login form
            get_resp = c.get("/admin/login")
            token = _extract_csrf_token(get_resp.data.decode())

            post_resp = c.post(
                "/admin/login",
                data={
                    "csrf_token": token,
                    "username": _TEST_ADMIN_USER,
                    "password": _TEST_ADMIN_PASS,
                },
                follow_redirects=False,
            )
            self.assertEqual(post_resp.status_code, 302)
            self.assertEqual(session.get("admin_logged_in"), True)
            self.assertEqual(session.get("is_demo"), False)
            self.assertEqual(session.get("admin_user"), _TEST_ADMIN_USER)

            # Follow redirect to dashboard
            dash_resp = c.get("/admin/")
            self.assertEqual(dash_resp.status_code, 200)

    def test_admin_login_invalid_password_rejected(self):
        """Invalid password must return HTTP 401 and not grant access."""
        with self.client as c:
            get_resp = c.get("/admin/login")
            token = _extract_csrf_token(get_resp.data.decode())

            post_resp = c.post(
                "/admin/login",
                data={
                    "csrf_token": token,
                    "username": _TEST_ADMIN_USER,
                    "password": "wrong-password",
                },
            )
            self.assertEqual(post_resp.status_code, 401)
            self.assertIn("Invalid username or password", post_resp.data.decode())
            self.assertFalse(session.get("admin_logged_in"))

    def test_admin_login_invalid_username_rejected(self):
        """Invalid username must return HTTP 401."""
        with self.client as c:
            get_resp = c.get("/admin/login")
            token = _extract_csrf_token(get_resp.data.decode())

            post_resp = c.post(
                "/admin/login",
                data={
                    "csrf_token": token,
                    "username": "unknown_admin",
                    "password": _TEST_ADMIN_PASS,
                },
            )
            self.assertEqual(post_resp.status_code, 401)
            self.assertFalse(session.get("admin_logged_in"))

    def test_admin_login_rate_limiting(self):
        """Repeated failed login attempts must trigger rate limiting (HTTP 429)."""
        with self.client as c:
            get_resp = c.get("/admin/login")
            token = _extract_csrf_token(get_resp.data.decode())

            # Attempt 5 wrong logins
            for _ in range(5):
                c.post(
                    "/admin/login",
                    data={
                        "csrf_token": token,
                        "username": _TEST_ADMIN_USER,
                        "password": "wrong-password",
                    },
                )

            # 6th attempt should be rate limited
            rate_limited_resp = c.post(
                "/admin/login",
                data={
                    "csrf_token": token,
                    "username": _TEST_ADMIN_USER,
                    "password": "wrong-password",
                },
            )
            self.assertEqual(rate_limited_resp.status_code, 429)
            self.assertIn("Too many failed login attempts", rate_limited_resp.data.decode())

    # ── 4. One-Click Demo Mode ────────────────────────────────────────────────

    def test_one_click_demo_account_creation(self):
        """POST /admin/demo creates a demo session without credentials."""
        with self.client as c:
            resp = c.post("/admin/demo", follow_redirects=False)
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(session.get("admin_logged_in"), True)
            self.assertEqual(session.get("is_demo"), True)

    def test_demo_user_can_read_all_admin_views(self):
        """Demo user has read-only access to dashboard, map, hotspots, and detail."""
        with self.client as c:
            c.post("/admin/demo")  # activate demo

            # 1. Dashboard
            r_dash = c.get("/admin/")
            self.assertEqual(r_dash.status_code, 200)
            self.assertIn("DEMO MODE", r_dash.data.decode())

            # 2. Map
            r_map = c.get("/admin/map")
            self.assertEqual(r_map.status_code, 200)

            # 3. Hotspots
            r_hot = c.get("/admin/hotspots")
            self.assertEqual(r_hot.status_code, 200)

            # 4. Detail
            r_det = c.get("/admin/complaint/DEMO-TEST-001")
            self.assertEqual(r_det.status_code, 200)
            self.assertIn("DEMO MODE", r_det.data.decode())

    def test_demo_user_status_update_rejected_with_403(self):
        """Demo user attempting to update complaint status must be rejected with 403 Forbidden."""
        with self.client as c:
            c.post("/admin/demo")  # activate demo
            det_resp = c.get("/admin/complaint/DEMO-TEST-001")
            token = _extract_csrf_token(det_resp.data.decode())

            # Attempt status change
            post_resp = c.post(
                "/admin/complaint/DEMO-TEST-001/update",
                data={
                    "csrf_token": token,
                    "new_status": "In Progress",
                },
            )
            self.assertEqual(post_resp.status_code, 403)

            # Verify complaint was NOT modified in the database
            row = db.get_complaint_by_id("DEMO-TEST-001")
            self.assertEqual(row["status"], "Submitted")

    def test_demo_user_add_note_rejected_with_403(self):
        """Demo user attempting to add action note must be rejected with 403 Forbidden."""
        with self.client as c:
            c.post("/admin/demo")  # activate demo
            det_resp = c.get("/admin/complaint/DEMO-TEST-001")
            token = _extract_csrf_token(det_resp.data.decode())

            post_resp = c.post(
                "/admin/complaint/DEMO-TEST-001/add_note",
                data={
                    "csrf_token": token,
                    "note": "Malicious attempt by demo user",
                },
            )
            self.assertEqual(post_resp.status_code, 403)

    # ── 5. Full Admin Writes ──────────────────────────────────────────────────

    def test_admin_user_can_update_complaint(self):
        """Authenticated administrator can update complaint status."""
        with self.client as c:
            # Login as admin
            get_resp = c.get("/admin/login")
            token = _extract_csrf_token(get_resp.data.decode())
            c.post(
                "/admin/login",
                data={
                    "csrf_token": token,
                    "username": _TEST_ADMIN_USER,
                    "password": _TEST_ADMIN_PASS,
                },
            )

            # Update status
            det_resp = c.get("/admin/complaint/DEMO-TEST-001")
            det_token = _extract_csrf_token(det_resp.data.decode())
            update_resp = c.post(
                "/admin/complaint/DEMO-TEST-001/update",
                data={
                    "csrf_token": det_token,
                    "new_status": "In Progress",
                },
                follow_redirects=False,
            )
            self.assertEqual(update_resp.status_code, 302)

            # Verify DB updated
            row = db.get_complaint_by_id("DEMO-TEST-001")
            self.assertEqual(row["status"], "In Progress")

    # ── 6. Logout ─────────────────────────────────────────────────────────────

    def test_logout_ends_admin_session(self):
        """Logout clears admin session and returns to login page."""
        with self.client as c:
            get_resp = c.get("/admin/login")
            token = _extract_csrf_token(get_resp.data.decode())
            c.post(
                "/admin/login",
                data={
                    "csrf_token": token,
                    "username": _TEST_ADMIN_USER,
                    "password": _TEST_ADMIN_PASS,
                },
            )
            self.assertTrue(session.get("admin_logged_in"))

            logout_resp = c.get("/admin/logout", follow_redirects=False)
            self.assertEqual(logout_resp.status_code, 302)
            self.assertIn("/admin/login", logout_resp.headers["Location"])
            self.assertFalse(session.get("admin_logged_in"))

    def test_logout_ends_demo_session(self):
        """Logout clears demo session."""
        with self.client as c:
            c.post("/admin/demo")
            self.assertTrue(session.get("is_demo"))

            logout_resp = c.get("/admin/logout", follow_redirects=False)
            self.assertEqual(logout_resp.status_code, 302)
            self.assertFalse(session.get("is_demo"))
