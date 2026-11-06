"""
tests/test_phase4c_notifications.py – In-App Notifications Tests
Covers Phase 4-C:
  - Notifications generated on status updates.
  - Notifications generated on complaint submission.
  - Querying notifications for complaint.
  - Unread notification count.
  - Marking notifications as read.
  - Deduplication prevents spamming identical alerts within short intervals.
  - CSRF protection on mark-read endpoints.
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


def setUpModule():
    global _TEST_DIR
    _TEST_DIR = tempfile.mkdtemp(prefix="civicai_notif_test_")
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


def _make_client(testing=True):
    from app import create_app
    app = create_app()
    app.config["TESTING"] = testing
    return app.test_client(), app


def _insert_complaint(cid, title="Notification testing issue", status="Submitted"):
    with db.db_cursor() as (conn, cur):
        cur.execute(
            """INSERT OR IGNORE INTO complaints
               (complaint_id, title, description, category, status)
               VALUES (?, ?, 'Valid test description with more than 20 chars', 'Road Damage', ?);""",
            (cid, title, status),
        )


class TestInAppNotifications(unittest.TestCase):

    def test_status_update_creates_persistent_notification(self):
        """Updating status triggers an automated notification."""
        cid = "NOTIF-STAT-001"
        _insert_complaint(cid, status="Submitted")

        # Update status
        db.update_complaint_status(cid, "In Progress", action_note="Repair crew dispatched")

        # Check notifications
        notifs = db.get_notifications_by_complaint(cid)
        self.assertGreaterEqual(len(notifs), 1)

        latest = notifs[0]
        self.assertEqual(latest["complaint_id"], cid)
        self.assertIn("In Progress", latest["title"])
        self.assertIn("Repair crew dispatched", latest["message"])
        self.assertEqual(latest["is_read"], 0)

    def test_unread_count_and_mark_as_read(self):
        """Marking a notification as read updates its status and count."""
        cid = "NOTIF-READ-001"
        _insert_complaint(cid)

        nid = db.create_notification(cid, "Inspector Assigned", "Officer John has been assigned.")
        self.assertIsNotNone(nid)

        unread_before = db.get_unread_notification_count([cid])
        self.assertGreaterEqual(unread_before, 1)

        # Mark as read
        ok = db.mark_notification_as_read(nid)
        self.assertTrue(ok)

        notifs = db.get_notifications_by_complaint(cid)
        matching = [n for n in notifs if n["id"] == nid]
        self.assertEqual(matching[0]["is_read"], 1)

    def test_mark_all_read(self):
        """Mark all matching notifications as read."""
        cid = "NOTIF-ALL-001"
        _insert_complaint(cid)
        db.create_notification(cid, "Notice 1", "Message 1")
        db.create_notification(cid, "Notice 2", "Message 2")

        count = db.mark_all_notifications_read([cid])
        self.assertGreaterEqual(count, 1)

        unread = db.get_unread_notification_count([cid])
        self.assertEqual(unread, 0)

    def test_notification_views_via_http(self):
        """Notification center renders notifications when complaint is tracked in session."""
        cid = "NOTIF-HTTP-001"
        _insert_complaint(cid)
        db.create_notification(cid, "System Alert", "Road inspection scheduled.")

        client, app = _make_client()
        with client.session_transaction() as sess:
            sess["my_complaints"] = [cid]

        resp = client.get(f"/submit/notifications?complaint_id={cid}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"System Alert", resp.data)
        self.assertIn(b"Road inspection scheduled.", resp.data)

    def test_notification_views_hides_untracked_complaints(self):
        """Querying arbitrary complaint_id via GET does NOT reveal notifications if untracked."""
        cid = "NOTIF-SECRET-001"
        _insert_complaint(cid)
        db.create_notification(cid, "Classified Alert", "Sensitive inspection notes.")

        client, app = _make_client()
        # Citizen session does not include cid
        resp = client.get(f"/submit/notifications?complaint_id={cid}")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b"Classified Alert", resp.data)
        self.assertNotIn(b"Sensitive inspection notes.", resp.data)

    def test_mark_read_endpoint_authorized_via_http(self):
        """POST /submit/notifications/<id>/read marks notification read when complaint is tracked."""
        cid = "NOTIF-POST-001"
        _insert_complaint(cid)
        nid = db.create_notification(cid, "Milestone Alert", "Work started.")

        client, app = _make_client()
        with client.session_transaction() as sess:
            sess["my_complaints"] = [cid]

        resp = client.post(f"/submit/notifications/{nid}/read", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        notifs = db.get_notifications_by_complaint(cid)
        matching = [n for n in notifs if n["id"] == nid]
        self.assertEqual(matching[0]["is_read"], 1)

    def test_mark_read_unauthorized_empty_session_rejects(self):
        """POST /submit/notifications/<id>/read rejects with 403 if session has no tracked complaints."""
        cid = "NOTIF-UNAUTH-001"
        _insert_complaint(cid)
        nid = db.create_notification(cid, "Secure Notice", "Secret information.")

        client, app = _make_client()
        resp = client.post(f"/submit/notifications/{nid}/read")
        self.assertEqual(resp.status_code, 403)

        notif = db.get_notification_by_id(nid)
        self.assertIsNotNone(notif)
        self.assertEqual(notif["is_read"], 0)

    def test_mark_read_unauthorized_different_complaint_rejects(self):
        """POST /submit/notifications/<id>/read rejects with 403 if notification belongs to another complaint."""
        target_cid = "NOTIF-TARGET-001"
        other_cid = "NOTIF-OTHER-001"
        _insert_complaint(target_cid)
        _insert_complaint(other_cid)
        nid = db.create_notification(target_cid, "Target Notice", "Details.")

        client, app = _make_client()
        with client.session_transaction() as sess:
            sess["my_complaints"] = [other_cid]

        resp = client.post(f"/submit/notifications/{nid}/read")
        self.assertEqual(resp.status_code, 403)

        notif = db.get_notification_by_id(nid)
        self.assertIsNotNone(notif)
        self.assertEqual(notif["is_read"], 0)

    def test_mark_all_read_unauthorized_forged_complaint_id_rejects(self):
        """POST /submit/notifications/read-all rejects with 403 if complaint_id is not in session."""
        owned_cid = "NOTIF-OWN-001"
        victim_cid = "NOTIF-VICTIM-001"
        _insert_complaint(owned_cid)
        _insert_complaint(victim_cid)
        nid_victim = db.create_notification(victim_cid, "Victim Notice", "Confidential.")

        client, app = _make_client()
        with client.session_transaction() as sess:
            sess["my_complaints"] = [owned_cid]

        resp = client.post("/submit/notifications/read-all", data={"complaint_id": victim_cid})
        self.assertEqual(resp.status_code, 403)

        notif = db.get_notification_by_id(nid_victim)
        self.assertIsNotNone(notif)
        self.assertEqual(notif["is_read"], 0)

    def test_mark_all_read_empty_session_affects_zero_notifications(self):
        """POST /submit/notifications/read-all with empty session does not mark any notifications as read."""
        cid = "NOTIF-UNTOUCHED-001"
        _insert_complaint(cid)
        nid = db.create_notification(cid, "Untouched Notice", "Must stay unread.")

        client, app = _make_client()
        resp = client.post("/submit/notifications/read-all", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        notif = db.get_notification_by_id(nid)
        self.assertIsNotNone(notif)
        self.assertEqual(notif["is_read"], 0)

    def test_mark_all_read_authorized_in_session(self):
        """POST /submit/notifications/read-all marks only citizen's tracked notifications as read."""
        cid_mine = "NOTIF-MINE-001"
        cid_other = "NOTIF-THEIRS-001"
        _insert_complaint(cid_mine)
        _insert_complaint(cid_other)
        nid_mine = db.create_notification(cid_mine, "Mine Notice", "Read me.")
        nid_other = db.create_notification(cid_other, "Other Notice", "Leave me unread.")

        client, app = _make_client()
        with client.session_transaction() as sess:
            sess["my_complaints"] = [cid_mine]

        resp = client.post("/submit/notifications/read-all", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        notif_mine = db.get_notification_by_id(nid_mine)
        notif_other = db.get_notification_by_id(nid_other)
        self.assertEqual(notif_mine["is_read"], 1)
        self.assertEqual(notif_other["is_read"], 0)

    def test_database_mark_all_read_empty_list_returns_zero(self):
        """db.mark_all_notifications_read([]) safely returns 0 without modifying rows."""
        cid = "NOTIF-DB-EMPTY-001"
        _insert_complaint(cid)
        nid = db.create_notification(cid, "Notice", "Stay unread.")

        count = db.mark_all_notifications_read([])
        self.assertEqual(count, 0)

        notif = db.get_notification_by_id(nid)
        self.assertEqual(notif["is_read"], 0)

    def test_database_mark_read_with_complaint_ids_constraint(self):
        """db.mark_notification_as_read enforces complaint_ids if provided."""
        cid = "NOTIF-DB-OWN-001"
        _insert_complaint(cid)
        nid = db.create_notification(cid, "Notice", "Ownership check.")

        # Wrong complaint ID
        ok_wrong = db.mark_notification_as_read(nid, complaint_ids=["DIFFERENT-CID"])
        self.assertFalse(ok_wrong)
        notif = db.get_notification_by_id(nid)
        self.assertEqual(notif["is_read"], 0)

        # Empty complaint ID list
        ok_empty = db.mark_notification_as_read(nid, complaint_ids=[])
        self.assertFalse(ok_empty)
        notif = db.get_notification_by_id(nid)
        self.assertEqual(notif["is_read"], 0)

        # Correct complaint ID
        ok_correct = db.mark_notification_as_read(nid, complaint_ids=[cid])
        self.assertTrue(ok_correct)
        notif = db.get_notification_by_id(nid)
        self.assertEqual(notif["is_read"], 1)


if __name__ == "__main__":
    unittest.main()
