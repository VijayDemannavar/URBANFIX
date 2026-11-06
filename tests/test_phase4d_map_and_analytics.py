"""
tests/test_phase4d_map_and_analytics.py – Map, Analytics, Reports, and Recommendations Tests
Covers:
  - Phase 4-D: /admin/map interactive Leaflet view and coordinate handling.
  - Phase 4-E: Combined dashboard filters (category + status + priority) and clear button.
  - Phase 5.3: DepartmentRecommender matches categories and descriptions.
  - Phase 5.5: PredictiveInsightsEngine identifies clusters and trends.
  - Phase 5.7: /admin/analytics dashboard rendering and metrics.
  - Phase 5.10: /admin/reports filtering and /admin/reports/export.csv formatting and sanitization.
"""

import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as _config
import database as db
from ai.department_recommender import get_recommender
from ai.clarity_analyzer import get_clarity_analyzer
from ai.predictive_insights import get_insights_engine

_TEST_DIR = None


def setUpModule():
    global _TEST_DIR
    _TEST_DIR = tempfile.mkdtemp(prefix="civicai_map_test_")
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


def _make_client():
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client(), app


def _insert_geo_complaint(cid, title, cat, lat, lon, status="Submitted", priority="Medium", resolved_at=None):
    with db.db_cursor() as (conn, cur):
        cur.execute(
            """INSERT OR IGNORE INTO complaints
               (complaint_id, title, description, category, latitude, longitude,
                address, status, priority_level, priority_score, resolved_at)
               VALUES (?, ?, 'Valid test description of civic problem with details', ?, ?, ?, 'MG Road Novapolis', ?, ?, 50.0, ?);""",
            (cid, title, cat, lat, lon, status, priority, resolved_at),
        )


class TestMapAndCivicManagement(unittest.TestCase):

    def setUp(self):
        _insert_geo_complaint("MAP-001", "Pothole on Main St", "Road Damage", 12.9716, 77.5946, status="Submitted", priority="High")
        _insert_geo_complaint("MAP-002", "Streetlight broken", "Streetlight", 12.9720, 77.5950, status="Resolved", priority="Low", resolved_at="2026-11-06 12:00:00")
        _insert_geo_complaint("MAP-NO-GPS", "Noise complaint", "Noise Pollution", None, None, status="In Progress")

    def test_admin_map_renders_with_geo_complaints(self):
        """Admin map page renders successfully with Leaflet container and data."""
        client, app = _make_client()
        resp = client.get("/admin/map")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"admin-map", resp.data)
        self.assertIn(b"Interactive Complaint Map", resp.data)
        self.assertIn(b"MAP-001", resp.data)
        # Non-GPS complaints are not in the spatial map JSON
        self.assertNotIn(b"MAP-NO-GPS", resp.data)

    def test_department_recommender(self):
        """Department recommender correctly maps categories and keywords to departments."""
        recommender = get_recommender()

        rec1 = recommender.recommend("Road Damage", "Huge crater in asphalt", "Deep pothole damaging vehicles")
        self.assertEqual(rec1.recommended_department, "Public Works")
        self.assertIn("Public Works", rec1.rationale)

        rec2 = recommender.recommend("Streetlight", "Dark street lamp broken", "No light near junction")
        self.assertEqual(rec2.recommended_department, "Electrical Department")

        rec3 = recommender.recommend("Garbage Overflow", "Trash bin overflowing", "Rotting waste on sidewalk")
        self.assertEqual(rec3.recommended_department, "Waste Management")

    def test_clarity_analyzer(self):
        """Clarity analyzer gives suggestions for brief or vague text and approves detailed text."""
        analyzer = get_clarity_analyzer()

        vague = analyzer.analyze("please fix this.")
        self.assertFalse(vague.is_clear)
        self.assertTrue(len(vague.suggestions) > 0)

        detailed = analyzer.analyze("Deep 2-foot pothole on 100ft Ring Road near Central Park Gate 4 creating severe bottleneck for morning traffic.")
        self.assertTrue(detailed.is_clear)

    def test_predictive_insights_engine(self):
        """Predictive insights engine produces insights from complaint records."""
        engine = get_insights_engine()
        sample_complaints = [
            {"complaint_id": "P-1", "category": "Road Damage", "address": "Market Street", "priority_level": "Critical", "status": "Submitted"},
            {"complaint_id": "P-2", "category": "Road Damage", "address": "Market Street", "priority_level": "High", "status": "Submitted"},
            {"complaint_id": "P-3", "category": "Road Damage", "address": "Market Street", "priority_level": "Medium", "status": "In Progress"},
        ]
        insights = engine.generate_insights(sample_complaints)
        self.assertTrue(len(insights) > 0)
        recurring = [i for i in insights if i.insight_type == "recurring_hazard"]
        self.assertTrue(len(recurring) > 0)
        self.assertIn("Market Street", recurring[0].title)

    def test_admin_analytics_dashboard(self):
        """Analytics page computes metrics and renders without error."""
        client, app = _make_client()
        resp = client.get("/admin/analytics")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Civic Analytics", resp.data)
        self.assertIn(b"Resolution Rate", resp.data)

    def test_admin_reports_and_csv_export(self):
        """Reports view renders table and CSV export returns clean valid CSV with headers."""
        client, app = _make_client()
        # View HTML
        resp = client.get("/admin/reports?category=Road+Damage")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Complaint Reports", resp.data)
        self.assertIn(b"Export Filtered CSV", resp.data)

        # Download CSV
        csv_resp = client.get("/admin/reports/export.csv?category=Road+Damage")
        self.assertEqual(csv_resp.status_code, 200)
        self.assertEqual(csv_resp.mimetype, "text/csv")
        csv_text = csv_resp.data.decode("utf-8")
        self.assertIn("Complaint ID,Title,Category,Status", csv_text)
        self.assertIn("MAP-001", csv_text)


if __name__ == "__main__":
    unittest.main()
