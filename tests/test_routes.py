"""
tests/test_routes.py – CivicAI Phase 2 Route & Integration Tests

Tests:
  - Successful complaint submission (POST /submit/)
  - Missing required fields (title, description, category)
  - Invalid complaint data (bad lat/lon, oversized title)
  - Complaint retrieval (GET /admin/complaint/<id>)
  - Dashboard loads with all existing records intact
  - Dashboard filtering data embedded in page
  - Existing Phase 1 database records remain intact
  - 404 for unknown complaint
  - Success page shows correct complaint

Run with: python -m pytest tests/ -v
"""

import os
import sys
import io
import shutil
import tempfile
import unittest

# ── Path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as _config
import database as db

# ── Module-level temp DB + upload dir ─────────────────────────────────────────
_TEST_DIR  = None
_UPLOAD_DIR = None


def setUpModule():
    global _TEST_DIR, _UPLOAD_DIR
    _TEST_DIR   = tempfile.mkdtemp(prefix="civicai_routes_test_")
    _UPLOAD_DIR = os.path.join(_TEST_DIR, "uploads")
    os.makedirs(_UPLOAD_DIR, exist_ok=True)

    test_db = os.path.join(_TEST_DIR, "test_civicai.db")

    # Redirect config
    _config.DATABASE_DIR  = _TEST_DIR
    _config.DATABASE_PATH = test_db
    _config.UPLOAD_DIR    = _UPLOAD_DIR

    # Redirect database module references
    db.DATABASE_DIR  = _TEST_DIR
    db.DATABASE_PATH = test_db

    # Bootstrap the test database
    db.init_db()
    db.seed_departments()

    # Patch app-level UPLOAD_DIR too (imported into routes/submit.py at load time)
    import routes.submit as rs
    rs.UPLOAD_DIR = _UPLOAD_DIR


def tearDownModule():
    global _TEST_DIR
    if _TEST_DIR and os.path.exists(_TEST_DIR):
        shutil.rmtree(_TEST_DIR)


# ── App client fixture ────────────────────────────────────────────────────────

def _make_client():
    """Create a Flask test client pointing at the test database."""
    from app import create_app
    application = create_app()
    application.config["TESTING"]        = True
    application.config["WTF_CSRF_ENABLED"] = False
    # Override UPLOAD_DIR inside the app after creation
    application.config["UPLOAD_DIR"] = _UPLOAD_DIR
    return application.test_client(), application


# ── Helper ────────────────────────────────────────────────────────────────────

def _post_complaint(client, **overrides):
    """POST a valid complaint form, with optional field overrides."""
    data = {
        "title":       "Test pothole on demo street near marker",
        "description": "A large deep pothole that has appeared on the test street. "
                       "Vehicles are getting damaged and people are at risk.",
        "category":    "Road Damage",
        "address":     "Demo Street, Novapolis",
        "latitude":    "",
        "longitude":   "",
    }
    data.update(overrides)
    return client.post(
        "/submit/",
        data=data,
        follow_redirects=False,
        content_type="multipart/form-data",
    )


# ── Test suites ───────────────────────────────────────────────────────────────

class TestComplaintSubmission(unittest.TestCase):
    """Test the complaint submission form and route."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()

    def test_get_form_returns_200(self):
        """GET /submit/ should return 200 with the form."""
        resp = self.client.get("/submit/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Report a Civic Issue", resp.data)
        self.assertIn(b"complaint-form", resp.data)

    def test_successful_submission_redirects(self):
        """Valid POST should redirect to success page (302)."""
        resp = _post_complaint(self.client)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/submit/success/", resp.headers["Location"])

    def test_successful_submission_stores_in_db(self):
        """After valid submission, complaint should be in the database."""
        resp = _post_complaint(self.client)
        location = resp.headers["Location"]
        # Extract complaint ID from redirect URL
        complaint_id = location.split("/submit/success/")[-1].rstrip("/")

        row = db.get_complaint_by_id(complaint_id)
        self.assertIsNotNone(row, "Complaint not found in DB after submission")
        self.assertEqual(row["title"], "Test pothole on demo street near marker")
        self.assertEqual(row["category"], "Road Damage")
        self.assertEqual(row["status"], "Submitted")

    def test_success_page_shows_complaint_id(self):
        """The success page should display the complaint ID."""
        resp = _post_complaint(self.client)
        complaint_id = resp.headers["Location"].split("/submit/success/")[-1].rstrip("/")

        success_resp = self.client.get(f"/submit/success/{complaint_id}")
        self.assertEqual(success_resp.status_code, 200)
        self.assertIn(complaint_id.encode(), success_resp.data)
        self.assertIn(b"Your complaint has been submitted", success_resp.data)

    def test_submission_with_lat_lon(self):
        """Complaint with valid coordinates should be saved correctly."""
        resp = _post_complaint(
            self.client,
            title="Road crack near Lotus Colony main entrance area",
            latitude="12.9716",
            longitude="77.5946",
        )
        self.assertEqual(resp.status_code, 302)
        complaint_id = resp.headers["Location"].split("/submit/success/")[-1].rstrip("/")
        row = db.get_complaint_by_id(complaint_id)
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row["latitude"],  12.9716, places=4)
        self.assertAlmostEqual(row["longitude"], 77.5946, places=4)

    def test_status_history_created_on_submission(self):
        """Submission should create an initial status_history entry."""
        resp = _post_complaint(self.client)
        complaint_id = resp.headers["Location"].split("/submit/success/")[-1].rstrip("/")

        with db.db_cursor() as (conn, cur):
            cur.execute(
                "SELECT * FROM status_history WHERE complaint_id = ?;",
                (complaint_id,),
            )
            rows = cur.fetchall()

        self.assertGreater(len(rows), 0, "No status history created")
        self.assertEqual(rows[0]["new_status"], "Submitted")


class TestMissingRequiredFields(unittest.TestCase):
    """Test that missing required fields return 422 with error messages."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()

    def _assert_error(self, resp, expected_fragment: bytes):
        self.assertEqual(resp.status_code, 422,
                         f"Expected 422, got {resp.status_code}")
        self.assertIn(expected_fragment, resp.data,
                      f"Expected error '{expected_fragment}' not in response")

    def test_missing_title(self):
        resp = _post_complaint(self.client, title="")
        self._assert_error(resp, b"title is required")

    def test_missing_description(self):
        resp = _post_complaint(self.client, description="")
        self._assert_error(resp, b"Description is required")

    def test_missing_category(self):
        resp = _post_complaint(self.client, category="")
        self._assert_error(resp, b"Please select a category")

    def test_all_missing(self):
        resp = _post_complaint(self.client, title="", description="", category="")
        self.assertEqual(resp.status_code, 422)
        # Multiple errors should be shown
        self.assertIn(b"Please fix the following errors", resp.data)


class TestInvalidComplaintData(unittest.TestCase):
    """Test validation of invalid field values."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()

    def test_title_too_short(self):
        """Title under 10 chars should fail."""
        resp = _post_complaint(self.client, title="Short")
        self.assertEqual(resp.status_code, 422)
        self.assertIn(b"at least 10 characters", resp.data)

    def test_description_too_short(self):
        """Description under 20 chars should fail."""
        resp = _post_complaint(self.client, description="Too short.")
        self.assertEqual(resp.status_code, 422)
        self.assertIn(b"at least 20 characters", resp.data)

    def test_invalid_category(self):
        """A category not in the allowed list should fail."""
        resp = _post_complaint(self.client, category="HackerInput")
        self.assertEqual(resp.status_code, 422)
        self.assertIn(b"Invalid category", resp.data)

    def test_invalid_latitude(self):
        """Latitude out of range (-90..90) should fail."""
        resp = _post_complaint(self.client, latitude="999")
        self.assertEqual(resp.status_code, 422)
        self.assertIn(b"Latitude must be between", resp.data)

    def test_invalid_longitude(self):
        """Longitude out of range (-180..180) should fail."""
        resp = _post_complaint(self.client, longitude="-999")
        self.assertEqual(resp.status_code, 422)
        self.assertIn(b"Longitude must be between", resp.data)

    def test_non_numeric_latitude(self):
        """Non-numeric latitude should fail."""
        resp = _post_complaint(self.client, latitude="abc")
        self.assertEqual(resp.status_code, 422)
        self.assertIn(b"valid number", resp.data)

    def test_invalid_image_type(self):
        """Uploading a .txt file should fail with an image type error."""
        fake_file = (io.BytesIO(b"not an image"), "malicious.txt")
        resp = self.client.post(
            "/submit/",
            data={
                "title":       "Road damage near school entrance area side",
                "description": "Large pothole causing vehicles to swerve dangerously on the road.",
                "category":    "Road Damage",
                "image":       fake_file,
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 422)
        self.assertIn(b"Invalid file type", resp.data)

    def test_oversized_image(self):
        """Image over 5 MB should fail."""
        big_data = b"x" * (6 * 1024 * 1024)  # 6 MB
        fake_file = (io.BytesIO(big_data), "big.jpg")
        resp = self.client.post(
            "/submit/",
            data={
                "title":       "Road damage near school entrance area side",
                "description": "Large pothole causing vehicles to swerve dangerously on the road.",
                "category":    "Road Damage",
                "image":       fake_file,
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 422)
        self.assertIn(b"Image too large", resp.data)


class TestComplaintRetrieval(unittest.TestCase):
    """Test the admin complaint detail route."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()
        # Insert a known complaint for retrieval tests
        with db.db_cursor() as (conn, cur):
            cur.execute(
                """INSERT OR IGNORE INTO complaints
                   (complaint_id, title, description, category, address)
                   VALUES (?, ?, ?, ?, ?);""",
                (
                    "RETRIEVAL-TEST-001",
                    "Waterlogging at retrieval test junction",
                    "Standing water blocking entire road at junction.",
                    "Waterlogging",
                    "Test Street, Novapolis",
                ),
            )

    def test_detail_page_returns_200(self):
        resp = self.client.get("/admin/complaint/RETRIEVAL-TEST-001")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Waterlogging at retrieval test junction", resp.data)

    def test_detail_shows_complaint_id(self):
        resp = self.client.get("/admin/complaint/RETRIEVAL-TEST-001")
        self.assertIn(b"RETRIEVAL-TEST-001", resp.data)

    def test_detail_shows_category(self):
        resp = self.client.get("/admin/complaint/RETRIEVAL-TEST-001")
        self.assertIn(b"Waterlogging", resp.data)

    def test_detail_unknown_id_returns_404(self):
        resp = self.client.get("/admin/complaint/NO-SUCH-ID-99999")
        self.assertEqual(resp.status_code, 404)


class TestDashboard(unittest.TestCase):
    """Test the admin dashboard route."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()
        # Insert a few complaints for filter data
        complaints_to_insert = [
            ("DASH-001", "Broken streetlight near park entrance area",
             "The streetlight at the park entrance has been broken for two weeks.",
             "Streetlight", "Submitted"),
            ("DASH-002", "Garbage not collected near market area",
             "Garbage bins overflowing near the main market for three days.",
             "Garbage Overflow", "In Progress"),
            ("DASH-003", "Road pothole causing vehicle damage on main road",
             "Large pothole on the main road causing damage to vehicles daily.",
             "Road Damage", "Resolved"),
        ]
        with db.db_cursor() as (conn, cur):
            for cid, title, desc, cat, status in complaints_to_insert:
                cur.execute(
                    """INSERT OR IGNORE INTO complaints
                       (complaint_id, title, description, category, status)
                       VALUES (?, ?, ?, ?, ?);""",
                    (cid, title, desc, cat, status),
                )

    def test_dashboard_returns_200(self):
        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Admin Dashboard", resp.data)

    def test_dashboard_shows_complaint_table(self):
        resp = self.client.get("/admin/")
        # Table rows contain data-cid attributes
        self.assertIn(b"data-cid=", resp.data)

    def test_dashboard_shows_categories_in_filter(self):
        """The filter dropdown should list available categories."""
        resp = self.client.get("/admin/")
        self.assertIn(b"Road Damage", resp.data)
        self.assertIn(b"Waterlogging", resp.data)
        self.assertIn(b"Garbage Overflow", resp.data)

    def test_dashboard_shows_status_filter(self):
        """Status filter options should be present."""
        resp = self.client.get("/admin/")
        self.assertIn(b"Submitted", resp.data)
        self.assertIn(b"In Progress", resp.data)
        self.assertIn(b"Resolved", resp.data)

    def test_dashboard_complaint_ids_present(self):
        """Complaint IDs inserted in setUpClass should appear in the table."""
        resp = self.client.get("/admin/")
        self.assertIn(b"DASH-001", resp.data)
        self.assertIn(b"DASH-002", resp.data)
        self.assertIn(b"DASH-003", resp.data)

    def test_dashboard_stats_shown(self):
        """Stats section should be present."""
        resp = self.client.get("/admin/")
        self.assertIn(b"Total Complaints", resp.data)
        self.assertIn(b"Critical Priority", resp.data)



class TestPriorityFilter(unittest.TestCase):
    """
    Test the Priority dropdown filter on the admin dashboard.

    The filter is client-side (JS), so we verify that:
      1. The priority dropdown renders with all four options.
      2. Each row in the HTML table carries a data-priority attribute
         matching the complaint's priority_level value.
      3. Combined category + status + priority data attributes are
         all present together on a single row so the JS can apply
         all three simultaneously without conflict.
    """

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()
        # Insert complaints covering every priority level
        records = [
            ("PRIO-CRITICAL-001", "Exposed live wire near school gate entrance area",
             "An exposed live electrical wire is hanging from a broken pole.",
             "Public Safety", "Critical", "Submitted"),
            ("PRIO-HIGH-001",     "Large pothole on main arterial road junction area",
             "A large pothole has developed on the main arterial road.",
             "Road Damage",    "High",     "Under Review"),
            ("PRIO-MEDIUM-001",   "Garbage bin overflowing at central bus terminal stop",
             "The garbage bin at the central bus terminal has not been cleared.",
             "Garbage Overflow","Medium",  "In Progress"),
            ("PRIO-LOW-001",     "Broken park bench near fountain area central park",
             "Two benches near the fountain in the park have cracked legs.",
             "Other",          "Low",      "Resolved"),
            # Extra Critical complaint with a different category for combined tests
            ("PRIO-CRITICAL-002", "Sinkhole blocking entire highway near flyover zone",
             "A sinkhole has opened on the highway blocking all traffic lanes.",
             "Road Damage",    "Critical", "Assigned"),
        ]
        with db.db_cursor() as (conn, cur):
            for cid, title, desc, cat, prio, status in records:
                cur.execute(
                    """INSERT OR IGNORE INTO complaints
                       (complaint_id, title, description, category,
                        priority_level, status)
                       VALUES (?, ?, ?, ?, ?, ?);""",
                    (cid, title, desc, cat, prio, status),
                )

    # ── Priority dropdown renders ──────────────────────────────────────

    def test_priority_dropdown_present(self):
        """The filter-priority select element must be in the page."""
        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'id="filter-priority"', resp.data)

    def test_priority_dropdown_has_all_options(self):
        """Dropdown must contain All Priorities, Critical, High, Medium, Low."""
        resp = self.client.get("/admin/")
        for label in [b"All Priorities", b"Critical", b"High", b"Medium", b"Low"]:
            self.assertIn(label, resp.data,
                          f"Missing option: {label!r}")

    # ── data-priority attribute on rows ───────────────────────────────

    def test_critical_row_has_data_priority(self):
        """A Critical complaint row must carry data-priority='Critical'."""
        resp = self.client.get("/admin/")
        self.assertIn(b'data-priority="Critical"', resp.data)

    def test_high_row_has_data_priority(self):
        """A High complaint row must carry data-priority='High'."""
        resp = self.client.get("/admin/")
        self.assertIn(b'data-priority="High"', resp.data)

    def test_medium_row_has_data_priority(self):
        """A Medium complaint row must carry data-priority='Medium'."""
        resp = self.client.get("/admin/")
        self.assertIn(b'data-priority="Medium"', resp.data)

    def test_low_row_has_data_priority(self):
        """A Low complaint row must carry data-priority='Low'."""
        resp = self.client.get("/admin/")
        self.assertIn(b'data-priority="Low"', resp.data)

    # ── JS filter attributes completeness ─────────────────────────────

    def test_rows_have_all_four_filter_attributes(self):
        """
        Every data row must carry data-cid, data-text, data-cat,
        data-status, AND data-priority so the JS can filter on all axes.
        """
        resp = self.client.get("/admin/")
        html = resp.data.decode()
        # Find all table rows that have data-cid
        import re
        row_pattern = re.compile(
            r'<tr\s[^>]*data-cid="[^"]*"[^>]*>', re.IGNORECASE
        )
        rows = row_pattern.findall(html)
        self.assertGreater(len(rows), 0, "No data rows found in table")

        for row_tag in rows:
            for attr in ("data-cid", "data-text", "data-cat",
                         "data-status", "data-priority"):
                self.assertIn(
                    attr, row_tag,
                    f"Row is missing attribute '{attr}': {row_tag[:120]}"
                )

    # ── Combined filter data attributes co-exist on same row ──────────

    def test_combined_filter_attributes_on_critical_road_damage_row(self):
        """
        PRIO-CRITICAL-002 is Road Damage + Critical + Assigned.
        Its <tr> must carry all three filter attributes with those exact values
        so that selecting Category=Road Damage AND Priority=Critical AND
        Status=Assigned would leave exactly that row visible.
        """
        resp = self.client.get("/admin/")
        html = resp.data.decode()
        import re
        # Find the specific tr tag for PRIO-CRITICAL-002
        pattern = re.compile(
            r'<tr\s[^>]*data-cid="PRIO-CRITICAL-002"[^>]*>', re.IGNORECASE
        )
        match = pattern.search(html)
        self.assertIsNotNone(match,
            "Row for PRIO-CRITICAL-002 not found in dashboard HTML")

        row_tag = match.group(0)
        self.assertIn('data-cat="Road Damage"',  row_tag,
                      "data-cat mismatch on PRIO-CRITICAL-002 row")
        self.assertIn('data-priority="Critical"', row_tag,
                      "data-priority mismatch on PRIO-CRITICAL-002 row")
        self.assertIn('data-status="Assigned"',   row_tag,
                      "data-status mismatch on PRIO-CRITICAL-002 row")

    def test_combined_filter_category_and_priority_independent(self):
        """
        A Road Damage + High row and a Garbage Overflow + Medium row
        both exist. Verifies each carries independent values so
        priority filtering doesn't bleed across categories.
        """
        resp = self.client.get("/admin/")
        html = resp.data.decode()
        import re

        # Road Damage + High row (PRIO-HIGH-001)
        rd_pattern = re.compile(
            r'<tr\s[^>]*data-cid="PRIO-HIGH-001"[^>]*>', re.IGNORECASE
        )
        rd_match = rd_pattern.search(html)
        self.assertIsNotNone(rd_match, "PRIO-HIGH-001 row not found")
        rd_tag = rd_match.group(0)
        self.assertIn('data-cat="Road Damage"', rd_tag)
        self.assertIn('data-priority="High"',   rd_tag)

        # Garbage Overflow + Medium row (PRIO-MEDIUM-001)
        go_pattern = re.compile(
            r'<tr\s[^>]*data-cid="PRIO-MEDIUM-001"[^>]*>', re.IGNORECASE
        )
        go_match = go_pattern.search(html)
        self.assertIsNotNone(go_match, "PRIO-MEDIUM-001 row not found")
        go_tag = go_match.group(0)
        self.assertIn('data-cat="Garbage Overflow"', go_tag)
        self.assertIn('data-priority="Medium"',       go_tag)



class TestExistingDataIntegrity(unittest.TestCase):
    """
    Verify that Phase 2 does not corrupt existing Phase 1 data.
    Uses the PRODUCTION database (not the test temp DB) to count records.
    """

    def _prod_count(self, table: str) -> int:
        """Count rows in production DB by temporarily restoring prod paths."""
        import config as cfg
        import importlib

        # Save test DB path
        saved_dir  = db.DATABASE_DIR
        saved_path = db.DATABASE_PATH

        # Point to real production DB
        from config import BASE_DIR
        prod_db = os.path.join(BASE_DIR, "database", "civicai.db")
        db.DATABASE_DIR  = os.path.join(BASE_DIR, "database")
        db.DATABASE_PATH = prod_db

        try:
            with db.db_cursor() as (conn, cur):
                cur.execute(f"SELECT COUNT(*) FROM {table};")
                return cur.fetchone()[0]
        finally:
            db.DATABASE_DIR  = saved_dir
            db.DATABASE_PATH = saved_path

    def test_prod_departments_intact(self):
        """Production DB must still have all 6 departments."""
        count = self._prod_count("departments")
        self.assertGreaterEqual(count, 6, f"Expected ≥6 departments, got {count}")

    def test_prod_officers_intact(self):
        """Production DB must still have all 12 officers."""
        count = self._prod_count("officers")
        self.assertGreaterEqual(count, 12, f"Expected ≥12 officers, got {count}")

    def test_prod_complaints_intact(self):
        """Production DB must still have the 44+ seeded complaints."""
        count = self._prod_count("complaints")
        self.assertGreaterEqual(count, 44, f"Expected ≥44 complaints, got {count}")

    def test_prod_duplicate_links_intact(self):
        """Production DB must have at least 5 duplicate link pairs."""
        count = self._prod_count("duplicate_links")
        self.assertGreaterEqual(count, 5, f"Expected ≥5 duplicate links, got {count}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
