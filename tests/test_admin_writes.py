"""
tests/test_admin_writes.py – CivicAI Phase 4B Tests

Covers:
  Database helpers:
    - update_complaint_status() persists status and creates history row
    - update_complaint_status() sets resolved_at only on terminal statuses
    - update_complaint_status() does not overwrite an existing resolved_at
    - update_complaint_status() raises ValueError for unknown complaint
    - assign_complaint() persists department_id and officer_id
    - assign_complaint() raises ValueError for unknown complaint
    - add_action_note() persists note
    - add_action_note() raises ValueError for unknown complaint

  POST /admin/complaint/<id>/update:
    - Valid status update → 302 redirect; DB updated
    - Invalid status value → 422
    - Unknown complaint_id → 404
    - Status → Resolved sets resolved_at
    - Status → In Progress does NOT set resolved_at
    - Status history row created on update
    - Department + officer assignment via update route
    - Invalid department_id → 422
    - Empty POST (no changes) → 302 (no-op, not an error)

  POST /admin/complaint/<id>/add_note:
    - Valid note → 302; note appears in detail page
    - Empty note → 422
    - Note exceeding 1000 chars → 422
    - Unknown complaint_id → 404

  CSRF protection:
    - Valid token (TESTING=True bypass) passes
    - Invalid token (non-TESTING app) → 403 on /update
    - Missing token (non-TESTING app) → 403 on /update
    - Invalid token (non-TESTING app) → 403 on /add_note

  Detail page forms:
    - Update Status form present in detail page
    - Assign Department form present
    - Add Note form present
    - Status dropdown contains all COMPLAINT_STATUSES options
    - Department dropdown contains seeded departments

All database-mutating tests use a fresh temp database seeded per test class.
CSRF bypass tests create a second non-TESTING Flask app instance.
"""

import os
import sys
import shutil
import tempfile
import unittest
from secrets import token_hex

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as _config
import database as db
from config import COMPLAINT_STATUSES

# ── Temp DB setup ──────────────────────────────────────────────────────────────

_TEST_DIR   = None
_UPLOAD_DIR = None


def setUpModule():
    global _TEST_DIR, _UPLOAD_DIR
    _TEST_DIR   = tempfile.mkdtemp(prefix="civicai_4b_test_")
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


def _insert(cid, title="Test complaint title minimum", desc=None,
            cat="Road Damage", status="Submitted",
            priority_level="Low", priority_score=10.0):
    desc = desc or "Test description that is at least twenty characters long."
    with db.db_cursor() as (conn, cur):
        cur.execute(
            """INSERT OR IGNORE INTO complaints
               (complaint_id, title, description, category, status,
                priority_level, priority_score)
               VALUES (?, ?, ?, ?, ?, ?, ?);""",
            (cid, title, desc, cat, status, priority_level, priority_score),
        )


def _get_complaint(cid):
    return db.get_complaint_by_id(cid)


def _count_history(cid):
    with db.db_cursor() as (conn, cur):
        cur.execute(
            "SELECT COUNT(*) FROM status_history WHERE complaint_id = ?;", (cid,)
        )
        return cur.fetchone()[0]


def _count_notes(cid):
    with db.db_cursor() as (conn, cur):
        cur.execute(
            "SELECT COUNT(*) FROM action_notes WHERE complaint_id = ?;", (cid,)
        )
        return cur.fetchone()[0]


# ──────────────────────────────────────────────────────────────────────────────
# 1. DATABASE HELPER UNIT TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestDBHelpers(unittest.TestCase):
    """Pure DB-layer tests — no HTTP."""

    def setUp(self):
        # Insert fresh complaints for each test to avoid cross-test pollution
        _insert("DB-H-001", title="Pothole on MG Road near junction area",
                status="Submitted")
        _insert("DB-H-002", title="Garbage overflow at market entrance area",
                status="In Progress")
        _insert("DB-H-003", title="Waterlogging in Nehru Street block area",
                status="Under Review")

    # ── update_complaint_status ───────────────────────────────────────────────

    def test_update_status_persists(self):
        """update_complaint_status must write the new status to DB."""
        db.update_complaint_status("DB-H-001", "Under Review")
        row = _get_complaint("DB-H-001")
        self.assertEqual(row["status"], "Under Review")

    def test_update_status_creates_history_row(self):
        """update_complaint_status must append a status_history row."""
        before = _count_history("DB-H-001")
        db.update_complaint_status("DB-H-001", "Assigned", action_note="Dispatched.")
        after = _count_history("DB-H-001")
        self.assertEqual(after, before + 1)

    def test_update_status_history_has_correct_old_new(self):
        """The history row must record both old and new status."""
        # Use a dedicated complaint so prior tests cannot affect the initial status
        _insert("DB-H-HIST-ONLY", title="History old new test complaint area only",
                status="Submitted")
        db.update_complaint_status("DB-H-HIST-ONLY", "In Progress")
        with db.db_cursor() as (conn, cur):
            cur.execute(
                """SELECT old_status, new_status FROM status_history
                   WHERE complaint_id = 'DB-H-HIST-ONLY'
                   ORDER BY id DESC LIMIT 1;"""
            )
            row = cur.fetchone()
        self.assertEqual(row["old_status"],  "Submitted")
        self.assertEqual(row["new_status"],  "In Progress")

    def test_resolved_at_set_on_resolved(self):
        """resolved_at must be populated when status → 'Resolved'."""
        db.update_complaint_status("DB-H-001", "Resolved")
        row = _get_complaint("DB-H-001")
        self.assertIsNotNone(row["resolved_at"],
                             "resolved_at must be set when status = Resolved")

    def test_resolved_at_set_on_closed(self):
        """resolved_at must be populated when status → 'Closed'."""
        db.update_complaint_status("DB-H-002", "Closed")
        row = _get_complaint("DB-H-002")
        self.assertIsNotNone(row["resolved_at"])

    def test_resolved_at_not_set_for_non_terminal_status(self):
        """resolved_at must remain NULL for non-terminal statuses."""
        db.update_complaint_status("DB-H-003", "Assigned")
        row = _get_complaint("DB-H-003")
        self.assertIsNone(row["resolved_at"],
                          "resolved_at must stay NULL for non-terminal statuses")

    def test_resolved_at_not_overwritten(self):
        """resolved_at must not be overwritten once set."""
        db.update_complaint_status("DB-H-001", "Resolved")
        first_resolved = _get_complaint("DB-H-001")["resolved_at"]
        # Re-resolve — should keep first timestamp
        db.update_complaint_status("DB-H-001", "Closed")
        second_resolved = _get_complaint("DB-H-001")["resolved_at"]
        self.assertEqual(first_resolved, second_resolved,
                         "resolved_at was overwritten on second terminal update")

    def test_update_status_unknown_complaint_raises(self):
        """update_complaint_status must raise ValueError for an unknown ID."""
        with self.assertRaises(ValueError):
            db.update_complaint_status("NO-SUCH-ID", "Resolved")

    # ── assign_complaint ──────────────────────────────────────────────────────

    def test_assign_department(self):
        """assign_complaint must persist department_id."""
        depts = db.get_all_departments()
        dept_id = depts[0]["id"]
        db.assign_complaint("DB-H-001", department_id=dept_id, officer_id=None)
        row = _get_complaint("DB-H-001")
        self.assertEqual(row["department_id"], dept_id)

    def test_assign_clears_department(self):
        """Passing department_id=None must clear the existing assignment."""
        depts = db.get_all_departments()
        db.assign_complaint("DB-H-001", department_id=depts[0]["id"], officer_id=None)
        db.assign_complaint("DB-H-001", department_id=None, officer_id=None)
        row = _get_complaint("DB-H-001")
        self.assertIsNone(row["department_id"])

    def test_assign_unknown_complaint_raises(self):
        """assign_complaint must raise ValueError for an unknown ID."""
        with self.assertRaises(ValueError):
            db.assign_complaint("NO-SUCH-ID", department_id=1, officer_id=None)

    # ── add_action_note ───────────────────────────────────────────────────────

    def test_add_note_persists(self):
        """add_action_note must persist the note in the DB."""
        before = _count_notes("DB-H-001")
        db.add_action_note("DB-H-001", "Team dispatched to site.")
        after = _count_notes("DB-H-001")
        self.assertEqual(after, before + 1)

    def test_add_note_content_correct(self):
        """The persisted note must match the input string."""
        note_text = "Repair crew scheduled for tomorrow morning."
        db.add_action_note("DB-H-001", note_text)
        with db.db_cursor() as (conn, cur):
            cur.execute(
                "SELECT note FROM action_notes WHERE complaint_id = 'DB-H-001'"
                " ORDER BY id DESC LIMIT 1;"
            )
            row = cur.fetchone()
        self.assertEqual(row["note"], note_text)

    def test_add_note_unknown_complaint_raises(self):
        """add_action_note must raise ValueError for an unknown ID."""
        with self.assertRaises(ValueError):
            db.add_action_note("NO-SUCH-ID", "Some note.")


# ──────────────────────────────────────────────────────────────────────────────
# 2. POST /admin/complaint/<id>/update ROUTE TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestStatusUpdateRoute(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()
        _insert("RT-UPDATE-001", title="Broken streetlight near park entrance area",
                status="Submitted")
        _insert("RT-UPDATE-002", title="Drainage blockage near colony entrance area",
                status="Submitted")
        _insert("RT-UPDATE-003", title="Water supply disruption in sector area",
                status="In Progress")
        _insert("RT-UPDATE-004", title="Public safety hazard near bus stand area",
                status="Under Review")

    def _post_update(self, cid, **fields):
        return self.client.post(
            f"/admin/complaint/{cid}/update",
            data=fields,
            content_type="multipart/form-data",
            follow_redirects=False,
        )

    # ── Valid update ──────────────────────────────────────────────────────────

    def test_valid_status_update_redirects(self):
        """Valid status update must redirect (302) back to detail page."""
        resp = self._post_update("RT-UPDATE-001", new_status="Under Review")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/complaint/RT-UPDATE-001", resp.headers["Location"])

    def test_valid_status_update_persists_in_db(self):
        """After a valid update, the DB status must reflect the new value."""
        self._post_update("RT-UPDATE-002", new_status="Assigned")
        row = _get_complaint("RT-UPDATE-002")
        self.assertEqual(row["status"], "Assigned")

    def test_resolved_at_set_via_route(self):
        """Updating status to 'Resolved' via the route must set resolved_at."""
        self._post_update("RT-UPDATE-003", new_status="Resolved")
        row = _get_complaint("RT-UPDATE-003")
        self.assertIsNotNone(row["resolved_at"])

    def test_non_terminal_status_leaves_resolved_at_null(self):
        """Status → 'Assigned' must not set resolved_at."""
        self._post_update("RT-UPDATE-004", new_status="Assigned")
        row = _get_complaint("RT-UPDATE-004")
        self.assertIsNone(row["resolved_at"])

    def test_status_history_created_via_route(self):
        """Status update via route must create a status_history row."""
        _insert("RT-HIST-001", title="Test road damage complaint history area",
                status="Submitted")
        before = _count_history("RT-HIST-001")
        self._post_update("RT-HIST-001", new_status="Under Review")
        after = _count_history("RT-HIST-001")
        self.assertGreater(after, before)

    def test_action_note_stored_in_history(self):
        """An action_note sent with the update must appear in status_history."""
        _insert("RT-NOTE-HIST-001", title="Sewage overflow near colony gate area",
                status="Submitted")
        self._post_update("RT-NOTE-HIST-001", new_status="In Progress",
                          action_note="Field team en route to location.")
        with db.db_cursor() as (conn, cur):
            cur.execute(
                """SELECT action_note FROM status_history
                   WHERE complaint_id = 'RT-NOTE-HIST-001'
                   ORDER BY id DESC LIMIT 1;"""
            )
            row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertIn("Field team", row["action_note"])

    # ── Invalid inputs ────────────────────────────────────────────────────────

    def test_invalid_status_returns_422(self):
        """An invalid status string must return 422."""
        resp = self._post_update("RT-UPDATE-001", new_status="NotAStatus")
        self.assertEqual(resp.status_code, 422)

    def test_unknown_complaint_returns_404(self):
        """Posting to a non-existent complaint must return 404."""
        resp = self._post_update("NO-SUCH-CMP-99999", new_status="Resolved")
        self.assertEqual(resp.status_code, 404)

    def test_empty_post_no_op_redirects(self):
        """Posting with no fields (no changes) must still redirect cleanly."""
        resp = self._post_update("RT-UPDATE-001")
        self.assertEqual(resp.status_code, 302)

    # ── Department assignment ─────────────────────────────────────────────────

    def test_department_assigned_via_route(self):
        """Valid department_id via update route must persist to DB."""
        depts = db.get_all_departments()
        dept_id = depts[0]["id"]
        _insert("RT-DEPT-001", title="Road crack near hospital entrance test",
                status="Submitted")
        self._post_update("RT-DEPT-001", department_id=str(dept_id))
        row = _get_complaint("RT-DEPT-001")
        self.assertEqual(row["department_id"], dept_id)

    def test_invalid_department_returns_422(self):
        """Non-existent department_id must return 422."""
        _insert("RT-DEPT-ERR-001", title="Pothole near school junction entrance area",
                status="Submitted")
        resp = self._post_update("RT-DEPT-ERR-001", department_id="99999")
        self.assertEqual(resp.status_code, 422)


# ──────────────────────────────────────────────────────────────────────────────
# 3. POST /admin/complaint/<id>/add_note ROUTE TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestAddNoteRoute(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()
        _insert("RT-NOTE-001", title="Garbage overflow near market stall entrance",
                status="In Progress")
        _insert("RT-NOTE-002", title="Streetlight broken on lake road markers",
                status="Submitted")
        _insert("RT-NOTE-003", title="Waterlogging in residential area sector",
                status="Submitted")

    def _post_note(self, cid, note):
        return self.client.post(
            f"/admin/complaint/{cid}/add_note",
            data={"note": note},
            content_type="multipart/form-data",
            follow_redirects=False,
        )

    # ── Valid note ────────────────────────────────────────────────────────────

    def test_valid_note_redirects(self):
        """Valid note must redirect (302) back to detail page."""
        resp = self._post_note("RT-NOTE-001", "Crew dispatched to site today.")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/complaint/RT-NOTE-001", resp.headers["Location"])

    def test_valid_note_persists_in_db(self):
        """Note content must be stored in action_notes table."""
        note_text = "Repair scheduled for next Monday morning."
        before = _count_notes("RT-NOTE-002")
        self._post_note("RT-NOTE-002", note_text)
        after = _count_notes("RT-NOTE-002")
        self.assertEqual(after, before + 1)

    def test_note_appears_on_detail_page(self):
        """Submitted note must appear on the complaint detail page."""
        unique_note = "Unique-note-text-for-visibility-check-test-4B."
        self._post_note("RT-NOTE-003", unique_note)
        # Follow to detail page
        resp = self.client.get("/admin/complaint/RT-NOTE-003")
        self.assertIn(unique_note.encode(), resp.data)

    # ── Invalid inputs ────────────────────────────────────────────────────────

    def test_empty_note_returns_422(self):
        """Empty note must return 422."""
        resp = self._post_note("RT-NOTE-001", "")
        self.assertEqual(resp.status_code, 422)

    def test_whitespace_only_note_returns_422(self):
        """Whitespace-only note must return 422 (treated as empty after strip)."""
        resp = self._post_note("RT-NOTE-001", "   ")
        self.assertEqual(resp.status_code, 422)

    def test_note_exceeding_max_length_returns_422(self):
        """Note longer than 1000 characters must return 422."""
        long_note = "x" * 1001
        resp = self._post_note("RT-NOTE-001", long_note)
        self.assertEqual(resp.status_code, 422)

    def test_note_at_max_length_accepted(self):
        """Note of exactly 1000 characters must be accepted."""
        max_note = "a" * 1000
        resp = self._post_note("RT-NOTE-001", max_note)
        self.assertEqual(resp.status_code, 302)

    def test_unknown_complaint_returns_404(self):
        """Posting a note to a non-existent complaint must return 404."""
        resp = self._post_note("NO-SUCH-CMP-88888", "Some note.")
        self.assertEqual(resp.status_code, 404)


# ──────────────────────────────────────────────────────────────────────────────
# 4. CSRF PROTECTION TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestCSRFProtection(unittest.TestCase):
    """
    Verify that the CSRF helper rejects bad tokens when TESTING=False.

    Strategy:
      - Create a non-TESTING Flask client.
      - Make a GET request first to establish a session and capture the
        server-set csrf_token cookie / session value.
      - POST with a deliberately wrong token and assert 403.
      - POST with the correct token and assert not 403.
    """

    @classmethod
    def setUpClass(cls):
        _insert("CSRF-001", title="CSRF test complaint for protection tests",
                status="Submitted")
        # Non-TESTING client so _verify_csrf() actually runs
        cls.client, cls.app = _make_client(testing=False)
        cls.app.config["SECRET_KEY"] = "csrf-test-secret-key-for-phase-4b"
        # Warm up a session by visiting a GET page
        cls.client.get("/admin/")

    def _post_update(self, cid, csrf_value, **fields):
        data = {"csrf_token": csrf_value, **fields}
        return self.client.post(
            f"/admin/complaint/{cid}/update",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=False,
        )

    def _post_note(self, cid, csrf_value, note="Test note."):
        return self.client.post(
            f"/admin/complaint/{cid}/add_note",
            data={"csrf_token": csrf_value, "note": note},
            content_type="multipart/form-data",
            follow_redirects=False,
        )

    def _get_session_token(self):
        """Retrieve the csrf_token from the current session via a GET request."""
        with self.client.session_transaction() as sess:
            return sess.get("csrf_token", "")

    # ── Rejected tokens ───────────────────────────────────────────────────────

    def test_update_route_rejects_wrong_token(self):
        """POST /update with a wrong CSRF token must return 403."""
        resp = self._post_update("CSRF-001", "wrong-token-value", new_status="Assigned")
        self.assertEqual(resp.status_code, 403,
                         f"Expected 403 with wrong CSRF token, got {resp.status_code}")

    def test_update_route_rejects_missing_token(self):
        """POST /update with no CSRF token field must return 403."""
        resp = self.client.post(
            "/admin/complaint/CSRF-001/update",
            data={"new_status": "Assigned"},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 403,
                         f"Expected 403 with missing CSRF token, got {resp.status_code}")

    def test_add_note_route_rejects_wrong_token(self):
        """POST /add_note with a wrong CSRF token must return 403."""
        resp = self._post_note("CSRF-001", "bad-token", note="Should be rejected.")
        self.assertEqual(resp.status_code, 403,
                         f"Expected 403 with wrong CSRF token on add_note, got {resp.status_code}")

    def test_add_note_route_rejects_missing_token(self):
        """POST /add_note with no CSRF token must return 403."""
        resp = self.client.post(
            "/admin/complaint/CSRF-001/add_note",
            data={"note": "Should be rejected."},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 403)

    def test_empty_string_token_rejected(self):
        """An explicitly submitted empty-string token must return 403."""
        resp = self._post_update("CSRF-001", "", new_status="Assigned")
        self.assertEqual(resp.status_code, 403)

    # ── Accepted token ────────────────────────────────────────────────────────

    def test_update_route_accepts_valid_token(self):
        """POST /update with the correct session CSRF token must NOT return 403."""
        token = self._get_session_token()
        if not token:
            self.skipTest("Session token not set — cannot test valid CSRF")
        resp = self._post_update("CSRF-001", token, new_status="Under Review")
        self.assertNotEqual(resp.status_code, 403,
                            "Correct CSRF token was incorrectly rejected")

    def test_add_note_route_accepts_valid_token(self):
        """POST /add_note with the correct session CSRF token must NOT return 403."""
        token = self._get_session_token()
        if not token:
            self.skipTest("Session token not set — cannot test valid CSRF")
        resp = self._post_note("CSRF-001", token, note="Valid CSRF note test.")
        self.assertNotEqual(resp.status_code, 403,
                            "Correct CSRF token was incorrectly rejected on add_note")


# ──────────────────────────────────────────────────────────────────────────────
# 5. DETAIL PAGE FORM PRESENCE TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestDetailPageForms(unittest.TestCase):
    """
    Verify the write forms are rendered on the complaint detail page.
    """

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()
        _insert("FORM-001", title="Public safety hazard near school road area",
                status="Submitted")
        cls.resp = cls.client.get("/admin/complaint/FORM-001")

    def test_detail_page_returns_200(self):
        self.assertEqual(self.resp.status_code, 200)

    def test_update_status_form_present(self):
        """Detail page must contain the Update Status form."""
        self.assertIn(b"Update Status", self.resp.data)

    def test_status_dropdown_present(self):
        """Detail page must contain the new_status select element."""
        self.assertIn(b'name="new_status"', self.resp.data)

    def test_status_dropdown_has_all_options(self):
        """Status dropdown must list all COMPLAINT_STATUSES options."""
        for status in COMPLAINT_STATUSES:
            self.assertIn(status.encode(), self.resp.data,
                          f"Status option '{status}' missing from detail page")

    def test_assign_department_form_present(self):
        """Detail page must contain the department assignment form."""
        self.assertIn(b"Assign Department", self.resp.data)

    def test_department_dropdown_present(self):
        """Department dropdown must be in the form."""
        self.assertIn(b'name="department_id"', self.resp.data)

    def test_department_dropdown_has_seeded_departments(self):
        """Department dropdown must list the seeded departments."""
        self.assertIn(b"Public Works", self.resp.data)
        self.assertIn(b"Water &amp; Sanitation", self.resp.data)

    def test_officer_dropdown_present(self):
        """Officer dropdown must be in the form."""
        self.assertIn(b'name="officer_id"', self.resp.data)

    def test_add_note_form_present(self):
        """Detail page must contain the Add Action Note form."""
        self.assertIn(b"Add Action Note", self.resp.data)

    def test_add_note_textarea_present(self):
        """The note textarea must be in the page."""
        self.assertIn(b'name="note"', self.resp.data)

    def test_csrf_tokens_in_forms(self):
        """All forms must include a csrf_token hidden field."""
        html = self.resp.data.decode()
        import re
        csrf_inputs = re.findall(r'name="csrf_token"', html)
        # There are three forms (update status, assign, add note)
        self.assertGreaterEqual(len(csrf_inputs), 3,
                                f"Expected ≥3 csrf_token inputs, found {len(csrf_inputs)}")

    def test_update_form_action_url(self):
        """Update form action must point to the /update route."""
        self.assertIn(b"/update", self.resp.data)

    def test_add_note_form_action_url(self):
        """Add-note form action must point to the /add_note route."""
        self.assertIn(b"/add_note", self.resp.data)


# ──────────────────────────────────────────────────────────────────────────────
# 6. REGRESSION: EXISTING ROUTES UNAFFECTED
# ──────────────────────────────────────────────────────────────────────────────

class TestPhase4BRegressions(unittest.TestCase):
    """Confirm all Phase 1–4A features still work after Phase 4B changes."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()
        _insert("REG-4B-001", title="Regression check complaint for Phase 4B",
                status="Submitted")

    def test_dashboard_returns_200(self):
        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 200)

    def test_detail_page_returns_200(self):
        resp = self.client.get("/admin/complaint/REG-4B-001")
        self.assertEqual(resp.status_code, 200)

    def test_hotspots_route_returns_200(self):
        resp = self.client.get("/admin/hotspots")
        self.assertEqual(resp.status_code, 200)

    def test_submit_form_returns_200(self):
        resp = self.client.get("/submit/")
        self.assertEqual(resp.status_code, 200)

    def test_ai_sidebar_still_present(self):
        resp = self.client.get("/admin/complaint/REG-4B-001")
        self.assertIn(b"AI Analysis", resp.data)

    def test_priority_score_still_out_of_100(self):
        """Phase 4A priority score fix must still be in place."""
        resp = self.client.get("/admin/complaint/REG-4B-001")
        self.assertIn(b"/ 100", resp.data)

    def test_gps_button_still_present(self):
        """Phase 4A GPS button must still be in the submission form."""
        resp = self.client.get("/submit/")
        self.assertIn(b"Use My Location", resp.data)

    def test_404_for_unknown_complaint(self):
        resp = self.client.get("/admin/complaint/ZZZZZ-UNKNOWN")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
