"""
tests/test_phase4a.py – CivicAI Phase 4A Tests

Covers:
  Priority score display fix:
    - Detail page renders score as X / 100 (not X / 10)
    - Both a non-zero score and the default zero-score case

  GPS "Use My Location" button:
    - Button element present in the submission form
    - Button carries id="use-location"
    - Geolocation-status span is present
    - main.js contains the initGeolocate function
    - Button is type="button" (does not submit the form)

All tests are HTTP-level using the Flask test client with a temp database.
No real GPS calls are made; geolocation is a browser-only API.
"""

import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as _config
import database as db

# ── Temp DB setup (same pattern as other test modules) ────────────────────────

_TEST_DIR   = None
_UPLOAD_DIR = None


def setUpModule():
    global _TEST_DIR, _UPLOAD_DIR
    _TEST_DIR   = tempfile.mkdtemp(prefix="civicai_4a_test_")
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


def _make_client():
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client(), app


def _insert_complaint(cid, title, desc, cat="Road Damage",
                      priority_score=0.0, priority_level="Low",
                      latitude=None, longitude=None):
    """Insert a complaint row directly for testing."""
    with db.db_cursor() as (conn, cur):
        cur.execute(
            """INSERT OR IGNORE INTO complaints
               (complaint_id, title, description, category,
                priority_score, priority_level, latitude, longitude)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?);""",
            (cid, title, desc, cat,
             priority_score, priority_level, latitude, longitude),
        )


# ──────────────────────────────────────────────────────────────────────────────
# 1. PRIORITY SCORE DISPLAY TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestPriorityScoreDisplay(unittest.TestCase):
    """
    Verify the detail page renders priority_score as X / 100
    (not X / 10 as it was before Phase 4A).
    """

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()
        # High-priority complaint with a meaningful score
        _insert_complaint(
            "4A-PRIO-75", "Sinkhole on Highway 4 blocking traffic flow",
            "A large sinkhole has opened on the main highway near the flyover.",
            "Public Safety", priority_score=75.0, priority_level="Critical",
        )
        # Low-priority complaint with default score
        _insert_complaint(
            "4A-PRIO-00", "Broken park bench near fountain area test",
            "Two benches in the park have cracked legs and need replacement.",
            "Other", priority_score=0.0, priority_level="Low",
        )

    def _detail(self, cid):
        return self.client.get(f"/admin/complaint/{cid}")

    # ── / 100 scale ───────────────────────────────────────────────────────────

    def test_priority_score_shows_out_of_100(self):
        """Detail page must display score as '75 / 100', not '75 / 10'."""
        resp = self._detail("4A-PRIO-75")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"/ 100", resp.data,
                      "Priority score scale '/ 100' not found in detail page")

    def test_priority_score_does_not_show_out_of_10(self):
        """Priority Score meta-item must end with '/ 100', not '/ 10'."""
        resp = self._detail("4A-PRIO-75")
        html = resp.data.decode()
        import re
        match = re.search(
            r'<label>Priority Score</label>\s*<span>([^<]+)</span>',
            html, re.IGNORECASE,
        )
        self.assertIsNotNone(match, "Priority Score span not found in detail page")
        score_text = match.group(1).strip()
        # Ensure the scale is exactly '/ 100' — not '/ 10' with nothing after
        self.assertTrue(
            score_text.endswith("/ 100"),
            f"Priority score text '{score_text}' does not end with '/ 100'",
        )
        # Extra: the scale number must be exactly 100, not 10
        self.assertFalse(
            re.search(r'/ 10\b(?!0)', score_text),
            f"Priority score text '{score_text}' contains old '/ 10' scale",
        )

    def test_priority_score_value_75_displayed(self):
        """Score of 75 must appear as '75' on the detail page."""
        resp = self._detail("4A-PRIO-75")
        self.assertIn(b"75", resp.data)

    def test_priority_score_zero_displayed(self):
        """Default score of 0 must render without error."""
        resp = self._detail("4A-PRIO-00")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"/ 100", resp.data)

    def test_priority_score_integer_format(self):
        """Score must render without decimal point (e.g. '75', not '75.0')."""
        resp = self._detail("4A-PRIO-75")
        html = resp.data.decode()
        # '75.0 / 100' would indicate the old %.1f format — must not appear
        self.assertNotIn("75.0", html,
                         "Score rendered with decimal point — use %.0f format")


# ──────────────────────────────────────────────────────────────────────────────
# 2. GPS "USE MY LOCATION" BUTTON TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestGPSButton(unittest.TestCase):
    """
    Verify the complaint submission form contains the GPS auto-capture button
    and that main.js contains the initGeolocate implementation.

    Actual geolocation calls are browser-only and are not tested here.
    """

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()
        cls.form_resp = cls.client.get("/submit/")

    def test_form_returns_200(self):
        """Submission form must still return 200 after Phase 4A changes."""
        self.assertEqual(self.form_resp.status_code, 200)

    def test_gps_button_present(self):
        """Form must contain the 'Use My Location' button."""
        self.assertIn(b"Use My Location", self.form_resp.data,
                      "'Use My Location' text not found in form")

    def test_gps_button_has_id(self):
        """GPS button must carry id='use-location' for JS binding."""
        self.assertIn(b'id="use-location"', self.form_resp.data,
                      "id='use-location' not found on GPS button")

    def test_gps_button_type_is_button(self):
        """Button must be type='button' so it never triggers form submission."""
        html = self.form_resp.data.decode()
        # Must contain type="button" on the use-location element
        # (prevent accidental form submit if Enter is pressed)
        import re
        pattern = re.compile(
            r'<button[^>]+id="use-location"[^>]*>', re.IGNORECASE
        )
        match = pattern.search(html)
        self.assertIsNotNone(match, "use-location button element not found")
        self.assertIn('type="button"', match.group(0),
                      "GPS button must be type='button', not type='submit'")

    def test_gps_status_span_present(self):
        """Status feedback span (id='geo-status') must be present in the form."""
        self.assertIn(b'id="geo-status"', self.form_resp.data,
                      "id='geo-status' span not found in form")

    def test_form_still_has_latitude_field(self):
        """Latitude input must still be present after adding the GPS button."""
        self.assertIn(b'id="latitude"', self.form_resp.data)

    def test_form_still_has_longitude_field(self):
        """Longitude input must still be present after adding the GPS button."""
        self.assertIn(b'id="longitude"', self.form_resp.data)

    def test_main_js_contains_init_geolocate(self):
        """main.js must define initGeolocate for the button to work."""
        resp = self.client.get("/static/js/main.js")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"initGeolocate", resp.data,
                      "initGeolocate function not found in main.js")

    def test_main_js_contains_geolocation_api_call(self):
        """main.js must call navigator.geolocation.getCurrentPosition."""
        resp = self.client.get("/static/js/main.js")
        self.assertIn(b"getCurrentPosition", resp.data,
                      "getCurrentPosition not found in main.js")

    def test_main_js_handles_geolocation_error(self):
        """main.js must contain an error handler for denied/unavailable GPS."""
        resp = self.client.get("/static/js/main.js")
        # Error handler references the three Geolocation error codes
        self.assertIn(b"Location access denied", resp.data,
                      "GPS error handling message not found in main.js")

    def test_gps_button_does_not_break_form_submission(self):
        """Submitting the form with GPS button present must still work (302)."""
        resp = self.client.post(
            "/submit/",
            data={
                "title":       "Pothole on road near school entrance area",
                "description": "A large deep pothole near the school entrance is causing vehicle damage.",
                "category":    "Road Damage",
                "address":     "School Road, Novapolis",
                "latitude":    "",
                "longitude":   "",
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302,
                         "Form submission broken after GPS button addition")


# ──────────────────────────────────────────────────────────────────────────────
# 3. REGRESSION: EXISTING FEATURES UNAFFECTED
# ──────────────────────────────────────────────────────────────────────────────

class TestPhase4ARegressions(unittest.TestCase):
    """
    Confirm that Phase 4A changes do not break any previously working feature.
    """

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()
        _insert_complaint(
            "4A-REG-001",
            "Garbage overflow at market entrance area test",
            "Garbage bins overflowing at the main market entrance.",
            "Garbage Overflow", priority_score=25.0, priority_level="Medium",
        )

    def test_admin_dashboard_still_returns_200(self):
        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 200)

    def test_admin_dashboard_still_shows_stats(self):
        resp = self.client.get("/admin/")
        self.assertIn(b"Total Complaints", resp.data)
        self.assertIn(b"Critical Priority", resp.data)

    def test_detail_page_still_returns_200(self):
        resp = self.client.get("/admin/complaint/4A-REG-001")
        self.assertEqual(resp.status_code, 200)

    def test_detail_page_still_shows_ai_sidebar(self):
        resp = self.client.get("/admin/complaint/4A-REG-001")
        self.assertIn(b"AI Analysis", resp.data)

    def test_detail_page_still_shows_priority_level_badge(self):
        resp = self.client.get("/admin/complaint/4A-REG-001")
        self.assertIn(b"Medium", resp.data)

    def test_hotspots_route_still_returns_200(self):
        resp = self.client.get("/admin/hotspots")
        self.assertEqual(resp.status_code, 200)

    def test_submit_form_still_validates_required_fields(self):
        """Phase 4A changes must not break server-side form validation."""
        resp = self.client.post(
            "/submit/",
            data={"title": "", "description": "", "category": ""},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 422)
        self.assertIn(b"Please fix the following errors", resp.data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
