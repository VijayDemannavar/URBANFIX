"""
tests/test_date_time_handling.py – Unit and Integration Tests for Date & Time Handling in URBANFIX

Validates:
1. Indian Standard Time (IST / Asia/Kolkata = UTC+05:30) conversion.
2. Date format '07 Nov 2026' (%d %b %Y).
3. Time format 12-hour with AM/PM (%I:%M %p).
4. Datetime format '07 Nov 2026, 10:10 AM'.
5. Midnight boundary edge cases (preventing date shifting).
6. Graceful handling of missing, null, and invalid dates without crashing.
7. Dynamic calculation of current date and year.
8. Accurate submission, tracking, status history, and notification timestamps in IST.
9. Admin dashboard, reports table, and CSV export formatting in IST.
10. IST date range query boundaries converted to UTC.
"""

from datetime import datetime, timezone, timedelta
import re
import unittest

from app import create_app
import database as db
import dates


def _extract_csrf_token(html: str) -> str:
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    if m:
        return m.group(1)
    m = re.search(r'value="([^"]+)"\s+name="csrf_token"', html)
    return m.group(1) if m else ""


class TestDateTimeHandling(unittest.TestCase):
    """Test suite verifying robust date and time handling across URBANFIX."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app(admin_auth_mode="session")
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    # ── 1. Core Conversion & Formatting Tests ─────────────────────────────────

    def test_timezone_is_kolkata_ist(self):
        """IST timezone must be UTC+05:30."""
        now = datetime.now(dates.IST)
        offset = now.utcoffset()
        self.assertEqual(offset, timedelta(hours=5, minutes=30))

    def test_date_formatting_dd_mon_yyyy(self):
        """Dates must format as '07 Nov 2026'."""
        formatted = dates.format_date("2026-11-06 18:30:00")
        self.assertEqual(formatted, "07 Nov 2026")

    def test_time_formatting_12_hour_am_pm(self):
        """Time must format in 12-hour format with AM/PM."""
        t_am = dates.format_time("2026-11-06 18:30:00")  # 00:00 IST
        self.assertEqual(t_am, "12:00 AM")

        t_pm = dates.format_time("2026-11-07 09:30:00")  # 15:00 IST
        self.assertEqual(t_pm, "03:00 PM")

    def test_datetime_formatting(self):
        """Datetime must format as '07 Nov 2026, 12:00 AM'."""
        dt_str = dates.format_datetime("2026-11-06 18:30:00")
        self.assertEqual(dt_str, "07 Nov 2026, 12:00 AM")

    def test_midnight_boundary_transitions(self):
        """Verify exact boundary transitions around midnight to prevent date shifting."""
        # 18:29:59 UTC is 11:59:59 PM on 06 Nov 2026 in IST
        self.assertEqual(dates.format_date("2026-11-06 18:29:59"), "06 Nov 2026")
        self.assertEqual(dates.format_time("2026-11-06 18:29:59"), "11:59 PM")

        # 18:30:00 UTC is exactly 00:00:00 on 07 Nov 2026 in IST
        self.assertEqual(dates.format_date("2026-11-06 18:30:00"), "07 Nov 2026")
        self.assertEqual(dates.format_time("2026-11-06 18:30:00"), "12:00 AM")

        # 18:30:01 UTC is 00:00:01 on 07 Nov 2026 in IST
        self.assertEqual(dates.format_date("2026-11-06 18:30:01"), "07 Nov 2026")
        self.assertEqual(dates.format_time("2026-11-06 18:30:01"), "12:00 AM")

        # 06:30:00 UTC is 12:00 PM (noon) on 07 Nov 2026 in IST
        self.assertEqual(dates.format_date("2026-11-07 06:30:00"), "07 Nov 2026")
        self.assertEqual(dates.format_time("2026-11-07 06:30:00"), "12:00 PM")

        # 18:29:59 UTC is 11:59 PM on 07 Nov 2026 in IST
        self.assertEqual(dates.format_date("2026-11-07 18:29:59"), "07 Nov 2026")
        self.assertEqual(dates.format_time("2026-11-07 18:29:59"), "11:59 PM")

        # 18:30:00 UTC is 00:00:00 on 08 Nov 2026 in IST
        self.assertEqual(dates.format_date("2026-11-07 18:30:00"), "08 Nov 2026")
        self.assertEqual(dates.format_time("2026-11-07 18:30:00"), "12:00 AM")

    def test_missing_null_and_invalid_dates_handled_gracefully(self):
        """Missing or corrupt date values must return default and never raise exceptions."""
        self.assertEqual(dates.format_date(None, default="-"), "-")
        self.assertEqual(dates.format_date("", default="N/A"), "N/A")
        self.assertEqual(dates.format_date("   ", default="-"), "-")
        self.assertEqual(dates.format_date("null", default="-"), "-")
        self.assertEqual(dates.format_date("corrupted-date-xyz", default="-"), "-")

        self.assertEqual(dates.format_time(None, default="-"), "-")
        self.assertEqual(dates.format_time("corrupted", default="-"), "-")

        self.assertEqual(dates.format_datetime(None, default="-"), "-")
        self.assertEqual(dates.format_datetime("corrupted", default="-"), "-")

    def test_dynamic_current_date_and_year(self):
        """Current date and year must be calculated dynamically."""
        now = dates.now_ist()
        self.assertEqual(now.year, datetime.now(dates.IST).year)
        today_formatted = dates.format_date(now)
        self.assertTrue(re.match(r"^\d{2}\s[A-Z][a-z]{2}\s\d{4}$", today_formatted))

    def test_ist_date_range_to_utc_boundaries(self):
        """User input of '2026-11-07' in IST must span 2026-11-06 18:30:00 to 2026-11-07 18:29:59 UTC."""
        start_utc, end_utc = dates.ist_date_range_to_utc("2026-11-07", "2026-11-07")
        self.assertEqual(start_utc, "2026-11-06 18:30:00")
        self.assertEqual(end_utc, "2026-11-07 18:29:59")

    # ── 2. Full Application Integration & Route Tests ─────────────────────────

    def test_submission_and_tracking_view_dates(self):
        """Complaint tracking must display accurate IST submitted date and time."""
        cid = "TIME-TEST-001"
        with db.db_cursor() as (conn, cur):
            cur.execute(
                """INSERT OR REPLACE INTO complaints
                   (complaint_id, title, description, category, status, priority_level, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?);""",
                (cid, "Time test complaint", "Testing IST date display in tracking view.",
                 "Road Damage", "Submitted", "Medium", "2026-11-06 18:30:00"),
            )
            cur.execute(
                """INSERT INTO status_history
                   (complaint_id, old_status, new_status, action_note, changed_at)
                   VALUES (?, ?, ?, ?, ?);""",
                (cid, None, "Submitted", "Initial submission", "2026-11-06 18:30:00"),
            )

        resp = self.client.get(f"/submit/track?complaint_id={cid}")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        # 18:30:00 UTC must display as 07 Nov 2026, 12:00 AM in IST
        self.assertIn("07 Nov 2026, 12:00 AM", html)

    def test_resolution_date_display(self):
        """Resolved complaint must display accurate IST resolution date and time."""
        cid = "TIME-RES-001"
        with db.db_cursor() as (conn, cur):
            cur.execute(
                """INSERT OR REPLACE INTO complaints
                   (complaint_id, title, description, category, status, priority_level,
                    created_at, resolved_at, resolution_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);""",
                (cid, "Resolution time test", "Testing resolution date formatting.",
                 "Road Damage", "Resolved", "High", "2026-11-06 10:00:00",
                 "2026-11-06 18:30:00", "Repaired pothole."),
            )

        resp = self.client.get(f"/submit/track?complaint_id={cid}")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Resolution Date:", html)
        self.assertIn("07 Nov 2026, 12:00 AM", html)

    def test_notification_date_display(self):
        """Notification center must display accurate IST timestamps."""
        cid = "TIME-NOTIF-001"
        with db.db_cursor() as (conn, cur):
            cur.execute(
                """INSERT OR REPLACE INTO complaints
                   (complaint_id, title, description, category, status, priority_level, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?);""",
                (cid, "Notif time test", "Testing notification date formatting.",
                 "Streetlight", "Submitted", "Low", "2026-11-06 12:00:00"),
            )
            cur.execute(
                """INSERT INTO notifications
                   (complaint_id, title, message, created_at)
                   VALUES (?, ?, ?, ?);""",
                (cid, "Inspection Scheduled", "Field worker assigned to inspect streetlight.",
                 "2026-11-06 18:30:00"),
            )

        with self.client.session_transaction() as sess:
            sess["my_complaints"] = [cid]

        resp = self.client.get("/submit/notifications")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("07 Nov 2026, 12:00 AM", html)

    def test_admin_dashboard_and_detail_dates(self):
        """Admin dashboard must format date as '07 Nov 2026' and detail must format full datetime."""
        cid = "TIME-ADMIN-001"
        with db.db_cursor() as (conn, cur):
            cur.execute(
                """INSERT OR REPLACE INTO complaints
                   (complaint_id, title, description, category, status, priority_level, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?);""",
                (cid, "Admin date test", "Testing admin views date formatting.",
                 "Water Supply", "Submitted", "Medium", "2026-11-06 18:30:00", "2026-11-06 18:30:00"),
            )

        # 1. Dashboard table
        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("07 Nov 2026", html)

        # 2. Detail view
        det_resp = self.client.get(f"/admin/complaint/{cid}")
        self.assertEqual(det_resp.status_code, 200)
        det_html = det_resp.data.decode("utf-8")
        self.assertIn("07 Nov 2026, 12:00 AM", det_html)

    def test_csv_export_contains_formatted_ist_timestamps(self):
        """CSV export must include accurate IST formatted timestamps."""
        cid = "TIME-CSV-001"
        with db.db_cursor() as (conn, cur):
            cur.execute(
                """INSERT OR REPLACE INTO complaints
                   (complaint_id, title, description, category, status, priority_level,
                    created_at, resolved_at, resolution_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);""",
                (cid, "CSV date test", "Testing CSV export timestamps.",
                 "Public Safety", "Resolved", "Critical", "2026-11-06 18:30:00",
                 "2026-11-07 06:30:00", "Resolved hazard."),
            )

        resp = self.client.get("/admin/reports/export.csv")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "text/csv")
        csv_text = resp.data.decode("utf-8")

        # 2026-11-06 18:30:00 UTC -> 07 Nov 2026, 12:00 AM
        self.assertIn("07 Nov 2026, 12:00 AM", csv_text)
        # 2026-11-07 06:30:00 UTC -> 07 Nov 2026, 12:00 PM
        self.assertIn("07 Nov 2026, 12:00 PM", csv_text)


if __name__ == "__main__":
    unittest.main()
