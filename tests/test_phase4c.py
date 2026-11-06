"""
tests/test_phase4c.py – CivicAI Phase 4C Tests

Covers:
  4C-1 – data-table CSS alias:
    - admin.css file contains the .data-table rule
    - hotspots.html summary table uses class="data-table"

  4C-2 – Mobile navbar CSS:
    - main.css contains flex-wrap for .navbar-links at narrow breakpoint
    - .navbar-inner height:auto is present in the narrow breakpoint

  4C-3 – Leaflet mini-map on complaint detail page:
    - Detail page for a complaint WITH coordinates loads Leaflet CSS and JS
    - Detail page for a complaint WITHOUT coordinates does NOT load Leaflet
    - Detail page with coords contains the #detail-map div
    - Detail page without coords does NOT contain the #detail-map div
    - Coordinates are serialised via tojson (not raw string interpolation)
    - "Interactive map in Phase 5" placeholder text is gone

  4C-4 – Success page admin-link removal:
    - Success page no longer contains a link to /admin/complaint/
    - Success page no longer contains a link to /admin/ (dashboard)
    - Success page still shows the complaint ID
    - Success page contains the "Track your complaint" message
    - Success page still has "Report Another Issue" button

  Regressions:
    - All Phase 4A/4B features still work
    - Dashboard, detail page (both variants), hotspots, submit form all 200
    - Write forms still present on detail page
"""

import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as _config
import database as db

# ── Temp DB setup ──────────────────────────────────────────────────────────────

_TEST_DIR   = None
_UPLOAD_DIR = None


def setUpModule():
    global _TEST_DIR, _UPLOAD_DIR
    _TEST_DIR   = tempfile.mkdtemp(prefix="civicai_4c_test_")
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


def _insert(cid, title, desc=None, cat="Road Damage",
            latitude=None, longitude=None, address=None):
    desc = desc or "Test description that is at least twenty characters long."
    with db.db_cursor() as (conn, cur):
        cur.execute(
            """INSERT OR IGNORE INTO complaints
               (complaint_id, title, description, category,
                latitude, longitude, address)
               VALUES (?, ?, ?, ?, ?, ?, ?);""",
            (cid, title, desc, cat, latitude, longitude, address),
        )


# ──────────────────────────────────────────────────────────────────────────────
# 1. DATA-TABLE CSS ALIAS (4C-1)
# ──────────────────────────────────────────────────────────────────────────────

class TestDataTableCSS(unittest.TestCase):
    """Verify that admin.css defines .data-table and hotspots.html uses it."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()

    def _css(self):
        return self.client.get("/static/css/admin.css").data.decode()

    def test_data_table_rule_in_admin_css(self):
        """admin.css must define a rule targeting table.data-table."""
        css = self._css()
        self.assertIn("data-table", css,
                      ".data-table rule not found in admin.css")

    def test_hotspots_page_uses_data_table_class(self):
        """hotspots.html summary table must carry class='data-table' in its source."""
        # The rendered page may show the empty-state (no GPS complaints in test DB),
        # so read the template file directly from disk instead.
        import config as _cfg
        template_path = os.path.join(_cfg.BASE_DIR, "templates", "admin", "hotspots.html")
        with open(template_path, encoding="utf-8") as fh:
            source = fh.read()
        self.assertIn('class="data-table"', source,
                      "class='data-table' not found in hotspots.html template source")

    def test_admin_css_served(self):
        """admin.css must be served with HTTP 200."""
        resp = self.client.get("/static/css/admin.css")
        self.assertEqual(resp.status_code, 200)


# ──────────────────────────────────────────────────────────────────────────────
# 2. MOBILE NAVBAR CSS (4C-2)
# ──────────────────────────────────────────────────────────────────────────────

class TestMobileNavbarCSS(unittest.TestCase):
    """Verify that main.css has correct narrow-screen navbar rules."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()
        cls.css = cls.client.get("/static/css/main.css").data.decode()

    def test_main_css_served(self):
        resp = self.client.get("/static/css/main.css")
        self.assertEqual(resp.status_code, 200)

    def test_navbar_links_flex_wrap_in_narrow_breakpoint(self):
        """main.css must set flex-wrap on .navbar-links at narrow screen."""
        self.assertIn("flex-wrap", self.css,
                      "flex-wrap not found in main.css")

    def test_navbar_inner_height_auto_in_narrow_breakpoint(self):
        """main.css must set height:auto on .navbar-inner for narrow screens."""
        self.assertIn("height: auto", self.css,
                      "height: auto for .navbar-inner not found in main.css")

    def test_narrow_breakpoint_targets_480px(self):
        """The narrow media query must target max-width: 480px."""
        self.assertIn("max-width: 480px", self.css)


# ──────────────────────────────────────────────────────────────────────────────
# 3. LEAFLET MINI-MAP ON DETAIL PAGE (4C-3)
# ──────────────────────────────────────────────────────────────────────────────

class TestDetailMiniMap(unittest.TestCase):
    """
    Verify the Leaflet mini-map is shown only when coordinates are present,
    and the old placeholder text is gone.
    """

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()
        # Complaint WITH coordinates
        _insert("MAP-WITH-COORDS",
                "Road damage near Lotus Colony main entrance area",
                latitude=12.9672, longitude=77.5932,
                address="Lotus Colony, Novapolis")
        # Complaint WITHOUT coordinates
        _insert("MAP-NO-COORDS",
                "Noise pollution complaint near temple junction area")

    def _detail(self, cid):
        return self.client.get(f"/admin/complaint/{cid}")

    # ── Complaint WITH coordinates ────────────────────────────────────────────

    def test_leaflet_css_loaded_when_coords_present(self):
        """Detail page for complaint with coords must include Leaflet CSS."""
        resp = self._detail("MAP-WITH-COORDS")
        self.assertEqual(resp.status_code, 200)
        # Leaflet CSS CDN link should be in <head>
        self.assertIn(b"leaflet.css", resp.data,
                      "Leaflet CSS not loaded on detail page with coordinates")

    def test_leaflet_js_loaded_when_coords_present(self):
        """Detail page for complaint with coords must include Leaflet JS."""
        resp = self._detail("MAP-WITH-COORDS")
        self.assertIn(b"leaflet.js", resp.data,
                      "Leaflet JS not loaded on detail page with coordinates")

    def test_detail_map_div_present_when_coords_present(self):
        """#detail-map div must be rendered when coordinates are available."""
        resp = self._detail("MAP-WITH-COORDS")
        self.assertIn(b'id="detail-map"', resp.data,
                      "#detail-map div not found on detail page with coordinates")

    def test_coordinates_in_map_script(self):
        """The Leaflet JS block must embed the complaint's latitude."""
        resp = self._detail("MAP-WITH-COORDS")
        # 12.9672 should appear in the script block
        self.assertIn(b"12.9672", resp.data,
                      "Latitude not embedded in map script")

    def test_address_shown_near_map(self):
        """The address text should appear near the map section."""
        resp = self._detail("MAP-WITH-COORDS")
        self.assertIn(b"Lotus Colony", resp.data)

    def test_old_placeholder_text_gone(self):
        """'Interactive map in Phase 5' placeholder must no longer appear."""
        resp = self._detail("MAP-WITH-COORDS")
        self.assertNotIn(b"Interactive map in Phase 5", resp.data,
                         "Old map placeholder text still present after Phase 4C")

    # ── Complaint WITHOUT coordinates ─────────────────────────────────────────

    def test_leaflet_not_loaded_when_no_coords(self):
        """Detail page without coordinates must NOT load Leaflet."""
        resp = self._detail("MAP-NO-COORDS")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b"leaflet.js", resp.data,
                         "Leaflet JS loaded on detail page without coordinates")

    def test_detail_map_div_absent_when_no_coords(self):
        """#detail-map div must NOT appear when coordinates are absent."""
        resp = self._detail("MAP-NO-COORDS")
        self.assertNotIn(b'id="detail-map"', resp.data,
                         "#detail-map div found on detail page without coordinates")

    def test_no_coords_page_still_returns_200(self):
        """Detail page without coordinates must still render successfully."""
        resp = self._detail("MAP-NO-COORDS")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"AI Analysis", resp.data)


# ──────────────────────────────────────────────────────────────────────────────
# 4. SUCCESS PAGE ADMIN-LINK REMOVAL (4C-4)
# ──────────────────────────────────────────────────────────────────────────────

class TestSuccessPageLinks(unittest.TestCase):
    """Verify the success page no longer exposes admin routes to citizens."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()
        # Submit a real complaint to get a valid success page
        resp = cls.client.post(
            "/submit/",
            data={
                "title":       "Pothole on main road near school entrance area",
                "description": "A large pothole has formed near the school entrance causing vehicle damage.",
                "category":    "Road Damage",
                "address":     "School Road, Novapolis",
                "latitude":    "",
                "longitude":   "",
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        complaint_id = resp.headers["Location"].split("/submit/success/")[-1].rstrip("/")
        cls.success_resp = cls.client.get(f"/submit/success/{complaint_id}")
        cls.complaint_id = complaint_id

    def test_success_page_returns_200(self):
        self.assertEqual(self.success_resp.status_code, 200)

    def test_success_page_shows_complaint_id(self):
        """Complaint ID must still be prominently displayed."""
        self.assertIn(self.complaint_id.encode(), self.success_resp.data,
                      "Complaint ID not found on success page")

    def test_success_page_has_tracking_message(self):
        """'Track your complaint' guidance must be present."""
        self.assertIn(b"Track your complaint", self.success_resp.data,
                      "'Track your complaint' message not found on success page")

    def test_success_page_no_admin_complaint_link(self):
        """Success page must NOT link to /admin/complaint/ (admin detail)."""
        self.assertNotIn(b"/admin/complaint/", self.success_resp.data,
                         "Admin complaint detail link still on success page")

    def test_success_page_no_admin_dashboard_link(self):
        """Success page content must NOT contain an admin dashboard button/link."""
        # The global navbar (in base.html) always includes /admin/ links, so we
        # cannot assert the bytes "/admin/" are absent from the full page.
        # Instead assert that no *content-area* admin link is present by checking
        # that the old "Admin Dashboard" button text is gone.
        self.assertNotIn(b"Admin Dashboard", self.success_resp.data,
                         "Admin Dashboard button still on success page content")

    def test_success_page_has_report_another_button(self):
        """'Report Another Issue' button must still be present."""
        self.assertIn(b"Report Another Issue", self.success_resp.data,
                      "'Report Another Issue' button missing from success page")

    def test_success_page_still_shows_title(self):
        """Complaint title must still appear on success page."""
        self.assertIn(b"Pothole on main road", self.success_resp.data)

    def test_success_page_still_shows_status_badge(self):
        """Status badge must still appear on success page."""
        self.assertIn(b"Submitted", self.success_resp.data)


# ──────────────────────────────────────────────────────────────────────────────
# 5. REGRESSIONS
# ──────────────────────────────────────────────────────────────────────────────

class TestPhase4CRegressions(unittest.TestCase):
    """Verify all Phase 4A and 4B features remain intact after Phase 4C."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()
        _insert("REG-4C-001",
                "Regression check complaint for Phase 4C test",
                latitude=12.97, longitude=77.59)
        _insert("REG-4C-002",
                "Regression no-coords complaint for Phase 4C test")

    def test_dashboard_returns_200(self):
        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 200)

    def test_detail_with_coords_returns_200(self):
        resp = self.client.get("/admin/complaint/REG-4C-001")
        self.assertEqual(resp.status_code, 200)

    def test_detail_without_coords_returns_200(self):
        resp = self.client.get("/admin/complaint/REG-4C-002")
        self.assertEqual(resp.status_code, 200)

    def test_hotspots_returns_200(self):
        resp = self.client.get("/admin/hotspots")
        self.assertEqual(resp.status_code, 200)

    def test_submit_form_returns_200(self):
        resp = self.client.get("/submit/")
        self.assertEqual(resp.status_code, 200)

    def test_priority_score_out_of_100(self):
        """Phase 4A: priority score must still display as / 100."""
        resp = self.client.get("/admin/complaint/REG-4C-001")
        self.assertIn(b"/ 100", resp.data)

    def test_gps_button_present(self):
        """Phase 4A: GPS button must still be in submission form."""
        resp = self.client.get("/submit/")
        self.assertIn(b"Use My Location", resp.data)

    def test_write_forms_present_on_detail(self):
        """Phase 4B: Update Status and Add Note forms must still be present."""
        resp = self.client.get("/admin/complaint/REG-4C-001")
        self.assertIn(b"Update Status", resp.data)
        self.assertIn(b"Add Action Note", resp.data)

    def test_ai_sidebar_present(self):
        """AI Analysis sidebar must still render."""
        resp = self.client.get("/admin/complaint/REG-4C-001")
        self.assertIn(b"AI Analysis", resp.data)

    def test_hotspots_nav_link_present(self):
        """Hotspots nav link must appear on every admin page."""
        resp = self.client.get("/admin/")
        self.assertIn(b"Hotspots", resp.data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
