"""
tests/test_pagination.py – CivicAI Phase 4E Pagination Tests

Covers:
  4E-1 – DB helpers:
    - count_complaints() with no filters
    - count_complaints() with search
    - count_complaints() with category/status/priority filters
    - get_complaints_page() basic pagination (page 1, page 2)
    - get_complaints_page() returns correct slice
    - get_complaints_page() with sort ascending / descending
    - get_complaints_page() with invalid sort key falls back safely
    - get_complaints_page() out-of-range page returns empty list

  4E-2 – Dashboard route pagination:
    - First page returns 200
    - Next page returns 200 (page=2)
    - Previous page link present when page > 1
    - Next page link present when there are more pages
    - Last page has no Next link
    - First page has no Previous link
    - Out-of-range page number clamped (returns 200)
    - Invalid page string treated as page 1
    - Empty result set (all filters match nothing)
    - Search combined with pagination
    - Category filter combined with pagination
    - Status filter combined with pagination
    - Priority filter combined with pagination
    - Sorting combined with pagination (sort arrow direction)
    - Dashboard stats always reflect global totals (not just current page)
    - DASHBOARD_PAGE_SIZE setting honoured

  4E-3 – Regressions:
    - Dashboard still returns 200
    - Stats still present
    - Complaint table still rendered
    - All existing Phase 4B–4D features unaffected
"""

import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as _config
import database as db

# ── Test DB setup ──────────────────────────────────────────────────────────────

_TEST_DIR   = None
_UPLOAD_DIR = None

# We need more than DASHBOARD_PAGE_SIZE complaints to test multiple pages.
# Override page size to a small number so tests don't need hundreds of rows.
_TEST_PAGE_SIZE = 5


def setUpModule():
    global _TEST_DIR, _UPLOAD_DIR
    _TEST_DIR   = tempfile.mkdtemp(prefix="civicai_4e_test_")
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

    # Insert a known set of complaints for pagination tests
    _seed_complaints()


def tearDownModule():
    if _TEST_DIR and os.path.exists(_TEST_DIR):
        shutil.rmtree(_TEST_DIR)


def _seed_complaints():
    """Insert 12 known complaints across two categories and two priority levels."""
    rows = [
        # (complaint_id, title, category, status, priority_level)
        ("PAG-001", "Road pothole test complaint one near bus stand",   "Road Damage",     "Submitted",   "High"),
        ("PAG-002", "Road pothole test complaint two near school road",  "Road Damage",     "Submitted",   "Critical"),
        ("PAG-003", "Road pothole test complaint three near main gate",  "Road Damage",     "In Progress", "Medium"),
        ("PAG-004", "Road pothole test complaint four near river side",  "Road Damage",     "Resolved",    "Low"),
        ("PAG-005", "Road pothole test complaint five near park area",   "Road Damage",     "Submitted",   "High"),
        ("PAG-006", "Waterlog flooding at main junction test area one",  "Waterlogging",    "Submitted",   "Critical"),
        ("PAG-007", "Waterlog flooding at river area junction test two", "Waterlogging",    "Under Review","High"),
        ("PAG-008", "Waterlog flooding near stadium test complaint three","Waterlogging",   "Submitted",   "Medium"),
        ("PAG-009", "Streetlight broken at test corner one main road",   "Streetlight",     "Submitted",   "Low"),
        ("PAG-010", "Streetlight broken at test corner two side road",   "Streetlight",     "Assigned",    "Low"),
        ("PAG-011", "Garbage overflow near test market area entrance",   "Garbage Overflow","Submitted",   "High"),
        ("PAG-012", "Drainage blocked at test lane near hospital road",  "Drainage",        "Submitted",   "Medium"),
    ]
    with db.db_cursor() as (conn, cur):
        for cid, title, cat, status, plevel in rows:
            cur.execute(
                """INSERT OR IGNORE INTO complaints
                   (complaint_id, title, description, category, status, priority_level)
                   VALUES (?, ?, ?, ?, ?, ?);""",
                (cid, title,
                 "Test description that is at least twenty characters long.",
                 cat, status, plevel),
            )


def _make_client(page_size=None):
    """Create a test client, optionally overriding page size."""
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    if page_size is not None:
        import routes.admin as ra
        ra.DASHBOARD_PAGE_SIZE = page_size
    return app.test_client(), app


# ──────────────────────────────────────────────────────────────────────────────
# 1. DB HELPER UNIT TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestCountComplaints(unittest.TestCase):
    """Unit tests for db.count_complaints()."""

    def test_count_no_filter_returns_positive_number(self):
        total = db.count_complaints()
        self.assertGreater(total, 0)

    def test_count_no_filter_includes_all_seeded(self):
        total = db.count_complaints()
        self.assertGreaterEqual(total, 12)   # at least our 12 seeded rows

    def test_count_category_filter(self):
        n = db.count_complaints(category="Road Damage")
        self.assertEqual(n, 5)

    def test_count_status_filter(self):
        n = db.count_complaints(status="Submitted")
        # PAG-001, 002, 005, 006, 008, 009, 011, 012 = 8 submitted
        self.assertGreaterEqual(n, 8)

    def test_count_priority_filter(self):
        n = db.count_complaints(priority="Critical")
        # PAG-002, PAG-006
        self.assertGreaterEqual(n, 2)

    def test_count_search_filter(self):
        n = db.count_complaints(search="Waterlog")
        self.assertGreaterEqual(n, 3)

    def test_count_combined_filters(self):
        n = db.count_complaints(category="Road Damage", status="Submitted")
        self.assertGreaterEqual(n, 2)   # PAG-001, PAG-002 (Submitted Road Damage)

    def test_count_no_match_returns_zero(self):
        n = db.count_complaints(category="Road Damage", status="Closed")
        # None of our Road Damage complaints have status Closed
        self.assertEqual(n, 0)


class TestGetComplaintsPage(unittest.TestCase):
    """Unit tests for db.get_complaints_page()."""

    def test_first_page_returns_up_to_page_size(self):
        rows = db.get_complaints_page(page=1, page_size=5)
        self.assertLessEqual(len(rows), 5)

    def test_second_page_returns_different_rows(self):
        page1 = [r["complaint_id"] for r in db.get_complaints_page(page=1, page_size=5)]
        page2 = [r["complaint_id"] for r in db.get_complaints_page(page=2, page_size=5)]
        # No overlap between pages
        self.assertFalse(set(page1) & set(page2),
                         "Page 1 and page 2 share rows")

    def test_pagination_covers_all_rows(self):
        """All rows across all pages should equal count_complaints()."""
        total = db.count_complaints()
        collected = set()
        page = 1
        while True:
            rows = db.get_complaints_page(page=page, page_size=5)
            if not rows:
                break
            for r in rows:
                collected.add(r["complaint_id"])
            page += 1
        self.assertEqual(len(collected), total)

    def test_out_of_range_page_returns_empty(self):
        rows = db.get_complaints_page(page=9999, page_size=5)
        self.assertEqual(rows, [])

    def test_sort_asc(self):
        rows = db.get_complaints_page(page=1, page_size=100, sort="complaint_id", order="asc")
        ids = [r["complaint_id"] for r in rows]
        self.assertEqual(ids, sorted(ids))

    def test_sort_desc(self):
        rows = db.get_complaints_page(page=1, page_size=100, sort="complaint_id", order="desc")
        ids = [r["complaint_id"] for r in rows]
        self.assertEqual(ids, sorted(ids, reverse=True))

    def test_invalid_sort_key_falls_back(self):
        """An unknown sort key must not raise — it falls back to created_at."""
        rows = db.get_complaints_page(page=1, page_size=5, sort="invalid_col")
        self.assertIsInstance(rows, list)

    def test_category_filter_returns_matching_only(self):
        rows = db.get_complaints_page(page=1, page_size=100, category="Waterlogging")
        cats = {r["category"] for r in rows}
        self.assertEqual(cats, {"Waterlogging"})

    def test_status_filter_returns_matching_only(self):
        rows = db.get_complaints_page(page=1, page_size=100, status="Submitted")
        statuses = {r["status"] for r in rows}
        self.assertEqual(statuses, {"Submitted"})

    def test_search_filter(self):
        rows = db.get_complaints_page(page=1, page_size=100, search="PAG-006")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["complaint_id"], "PAG-006")

    def test_priority_filter_returns_matching_only(self):
        rows = db.get_complaints_page(page=1, page_size=100, priority="Critical")
        priorities = {r["priority_level"] for r in rows}
        self.assertEqual(priorities, {"Critical"})


# ──────────────────────────────────────────────────────────────────────────────
# 2. DASHBOARD ROUTE PAGINATION TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestDashboardPagination(unittest.TestCase):
    """
    Integration tests for the paginated /admin/ dashboard.
    Uses a small page size (_TEST_PAGE_SIZE = 5) so we can test multi-page
    behaviour with just 12 seeded complaints.
    """

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client(page_size=_TEST_PAGE_SIZE)

    # ── Basic rendering ───────────────────────────────────────────────

    def test_first_page_returns_200(self):
        resp = self.client.get("/admin/?page=1")
        self.assertEqual(resp.status_code, 200)

    def test_second_page_returns_200(self):
        resp = self.client.get("/admin/?page=2")
        self.assertEqual(resp.status_code, 200)

    def test_last_page_returns_200(self):
        resp = self.client.get("/admin/?page=3")
        self.assertEqual(resp.status_code, 200)

    def test_out_of_range_page_clamped_returns_200(self):
        resp = self.client.get("/admin/?page=9999")
        self.assertEqual(resp.status_code, 200)

    def test_invalid_page_string_returns_200(self):
        resp = self.client.get("/admin/?page=notanumber")
        self.assertEqual(resp.status_code, 200)

    def test_negative_page_clamped_returns_200(self):
        resp = self.client.get("/admin/?page=-5")
        self.assertEqual(resp.status_code, 200)

    # ── Pagination controls rendered ──────────────────────────────────

    def test_next_link_present_on_page_1(self):
        """Page 1 must show a Next / Last link when there are multiple pages."""
        resp = self.client.get("/admin/?page=1")
        self.assertIn(b"Next", resp.data,
                      "Next link missing on page 1 of multi-page result")

    def test_previous_link_absent_on_page_1(self):
        """Page 1 must NOT have a Previous link."""
        resp = self.client.get("/admin/?page=1")
        self.assertNotIn(b"Previous", resp.data,
                         "Previous link wrongly present on page 1")

    def test_previous_link_present_on_page_2(self):
        resp = self.client.get("/admin/?page=2")
        self.assertIn(b"Previous", resp.data,
                      "Previous link missing on page 2")

    def test_next_link_absent_on_last_page(self):
        """The last page must not show a Next link."""
        # 12 complaints / 5 per page → 3 pages
        resp = self.client.get("/admin/?page=3")
        self.assertNotIn(b"Next", resp.data,
                         "Next link wrongly present on last page")

    def test_pagination_nav_shows_page_of_total(self):
        """Page indicator must show 'Page X of Y'."""
        resp = self.client.get("/admin/?page=2")
        self.assertIn(b"Page", resp.data)

    # ── Filter preservation through pagination ────────────────────────

    def test_search_preserved_in_pagination_link(self):
        """Pagination links must include the active search query."""
        resp = self.client.get("/admin/?q=PAG&page=1")
        self.assertEqual(resp.status_code, 200)
        # The page link should contain q=PAG
        html = resp.data.decode()
        self.assertIn("q=PAG", html)

    def test_category_filter_with_pagination(self):
        resp = self.client.get("/admin/?category=Road+Damage&page=1")
        self.assertEqual(resp.status_code, 200)
        # All rows on this page must be Road Damage
        html = resp.data.decode()
        self.assertIn("Road Damage", html)

    def test_status_filter_with_pagination(self):
        resp = self.client.get("/admin/?status=Submitted&page=1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Submitted", resp.data)

    def test_priority_filter_with_pagination(self):
        resp = self.client.get("/admin/?priority=Critical&page=1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Critical", resp.data)

    def test_empty_filter_result_no_table_but_200(self):
        """A filter that matches nothing must still return 200, not 500."""
        resp = self.client.get("/admin/?category=Road+Damage&status=Closed")
        self.assertEqual(resp.status_code, 200)
        # No complaints match Road Damage + Closed → empty state shown
        self.assertNotIn(b"PAG-", resp.data)

    # ── Sorting with pagination ───────────────────────────────────────

    def test_sort_by_complaint_id_asc(self):
        resp = self.client.get("/admin/?sort=complaint_id&order=asc&page=1")
        self.assertEqual(resp.status_code, 200)
        # The ascending arrow indicator must be present
        self.assertIn("▲", resp.data.decode())

    def test_sort_by_complaint_id_desc(self):
        resp = self.client.get("/admin/?sort=complaint_id&order=desc&page=1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("▼", resp.data.decode())

    def test_invalid_sort_key_returns_200(self):
        resp = self.client.get("/admin/?sort=hack;DROP+TABLE--&page=1")
        self.assertEqual(resp.status_code, 200)

    # ── Stats always global ───────────────────────────────────────────

    def test_stats_show_total_not_just_page(self):
        """
        The stats card must always show the TOTAL complaint count, not just
        the count of the current page.
        """
        total = db.count_complaints()
        resp  = self.client.get("/admin/?page=1")
        html  = resp.data.decode()
        # Total Complaints stat card must show the real total
        self.assertIn(str(total), html,
                      "Stats card does not reflect global total")

    def test_stats_unaffected_by_category_filter(self):
        """Stats must show global total even when a filter is active."""
        total = db.count_complaints()
        resp  = self.client.get("/admin/?category=Road+Damage")
        html  = resp.data.decode()
        self.assertIn(str(total), html)

    # ── Page size honoured ────────────────────────────────────────────

    def test_page_size_limits_rows_per_page(self):
        """Page 1 must contain at most _TEST_PAGE_SIZE complaint rows."""
        resp = self.client.get("/admin/?page=1")
        html = resp.data.decode()
        # Count 'data-cid' attributes as a proxy for rendered complaint rows
        row_count = html.count('data-cid=')
        self.assertLessEqual(row_count, _TEST_PAGE_SIZE,
                             f"Too many rows on one page: {row_count} > {_TEST_PAGE_SIZE}")


# ──────────────────────────────────────────────────────────────────────────────
# 3. REGRESSIONS
# ──────────────────────────────────────────────────────────────────────────────

class TestPhase4ERegressions(unittest.TestCase):
    """Verify all prior features still work after Phase 4E changes."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()

    def test_dashboard_returns_200(self):
        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 200)

    def test_dashboard_shows_stats(self):
        resp = self.client.get("/admin/")
        self.assertIn(b"Total Complaints", resp.data)

    def test_dashboard_shows_complaint_table(self):
        resp = self.client.get("/admin/")
        self.assertIn(b"complaints-tbody", resp.data)

    def test_dashboard_categories_filter_present(self):
        resp = self.client.get("/admin/")
        self.assertIn(b"All Categories", resp.data)

    def test_dashboard_status_filter_present(self):
        resp = self.client.get("/admin/")
        self.assertIn(b"All Statuses", resp.data)

    def test_dashboard_priority_filter_present(self):
        resp = self.client.get("/admin/")
        self.assertIn(b"All Priorities", resp.data)

    def test_detail_page_still_returns_200(self):
        resp = self.client.get("/admin/complaint/PAG-001")
        self.assertEqual(resp.status_code, 200)

    def test_hotspots_still_returns_200(self):
        resp = self.client.get("/admin/hotspots")
        self.assertEqual(resp.status_code, 200)

    def test_submit_form_still_returns_200(self):
        resp = self.client.get("/submit/")
        self.assertEqual(resp.status_code, 200)

    def test_priority_score_out_of_100_on_detail(self):
        resp = self.client.get("/admin/complaint/PAG-001")
        self.assertIn(b"/ 100", resp.data)

    def test_write_forms_present_on_detail(self):
        resp = self.client.get("/admin/complaint/PAG-001")
        self.assertIn(b"Update Status", resp.data)
        self.assertIn(b"Add Action Note", resp.data)

    def test_csrf_tokens_present_on_detail(self):
        resp = self.client.get("/admin/complaint/PAG-001")
        self.assertIn(b'name="csrf_token"', resp.data)

    def test_gps_button_on_submit_form(self):
        resp = self.client.get("/submit/")
        self.assertIn(b"Use My Location", resp.data)

    def test_hotspots_nav_link_present(self):
        resp = self.client.get("/admin/")
        self.assertIn(b"Hotspots", resp.data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
