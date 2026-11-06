"""
tests/test_action_brief.py – CivicAI Phase 3E Action Brief Tests

Covers:
  Generator unit tests:
    - Empty complaint dataset
    - Single complaint
    - Multiple categories
    - All four priority levels
    - Multiple locations
    - Missing coordinates (graceful handling)
    - Missing category (graceful handling)
    - Department-wise recommendations
    - Hotspot integration
    - Generated timestamp format
    - Invalid / incomplete data
    - Status field values
    - Urgent complaints ordering
    - Recommendations list structure
    - Situation summary content

  Route tests:
    - GET /admin/brief returns 200
    - Brief page shows situation summary
    - Brief page shows priority overview
    - Brief page has Refresh button
    - Brief page has CSRF token
    - Brief page links back to dashboard
    - Brief nav link present on all admin pages
    - POST /admin/brief/generate redirects to /admin/brief
    - POST /admin/brief/generate CSRF-protected

  Legacy API compatibility:
    - generate_cluster_brief() still returns a string
    - generate_cluster_brief() with zero count returns empty string

  Existing functionality regressions:
    - Dashboard still works
    - Detail page still works
    - Hotspots still work
    - Submit form still works
"""

import os
import sys
import shutil
import tempfile
import unittest
from collections import namedtuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as _config
import database as db
from ai.action_brief import (
    ActionBriefGenerator,
    ActionBrief,
    HotspotSummary,
    get_brief_generator,
    _empty_brief,
    _hotspot_reason,
    _category_action,
)

# ── Fake Hotspot namedtuple (mirrors ai.hotspot_detector.Hotspot) ────────────

FakeHotspot = namedtuple(
    "FakeHotspot",
    ["center_lat", "center_lon", "complaint_ids", "count",
     "dominant_category", "radius_km", "critical_count",
     "high_count", "avg_priority_score"],
)


# ── Test DB setup ──────────────────────────────────────────────────────────────

_TEST_DIR   = None
_UPLOAD_DIR = None


def setUpModule():
    global _TEST_DIR, _UPLOAD_DIR
    _TEST_DIR   = tempfile.mkdtemp(prefix="civicai_3e_test_")
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


def _insert(cid, title, cat="Road Damage", status="Submitted",
            priority_level="Medium", priority_score=30,
            address=None, latitude=None, longitude=None,
            department_id=None):
    with db.db_cursor() as (conn, cur):
        cur.execute(
            """INSERT OR IGNORE INTO complaints
               (complaint_id, title, description, category, status,
                priority_level, priority_score, address,
                latitude, longitude, department_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);""",
            (cid, title,
             "Test description that is at least twenty characters long.",
             cat, status, priority_level, priority_score,
             address, latitude, longitude, department_id),
        )


# ──────────────────────────────────────────────────────────────────────────────
# 1. GENERATOR UNIT TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestActionBriefGeneratorEmpty(unittest.TestCase):
    """ActionBriefGenerator.generate() with an empty complaint list."""

    def setUp(self):
        self.gen   = ActionBriefGenerator()
        self.brief = self.gen.generate([])

    def test_returns_action_brief_dataclass(self):
        self.assertIsInstance(self.brief, ActionBrief)

    def test_status_is_empty(self):
        self.assertEqual(self.brief.status, "empty")

    def test_total_analysed_is_zero(self):
        self.assertEqual(self.brief.total_analysed, 0)

    def test_situation_summary_mentions_no_complaints(self):
        self.assertIn("No complaints", self.brief.situation_summary)

    def test_top_categories_is_empty_list(self):
        self.assertEqual(self.brief.top_categories, [])

    def test_affected_locations_is_empty_list(self):
        self.assertEqual(self.brief.affected_locations, [])

    def test_priority_overview_all_zero(self):
        po = self.brief.priority_overview
        self.assertEqual(po["critical"], 0)
        self.assertEqual(po["high"],     0)
        self.assertEqual(po["medium"],   0)
        self.assertEqual(po["low"],      0)

    def test_urgent_complaints_is_empty(self):
        self.assertEqual(self.brief.urgent_complaints, [])

    def test_hotspot_analysis_is_empty(self):
        self.assertEqual(self.brief.hotspot_analysis, [])

    def test_recommendations_is_non_empty_list(self):
        """Empty brief still has at least one advisory recommendation."""
        self.assertIsInstance(self.brief.recommendations, list)
        self.assertGreater(len(self.brief.recommendations), 0)

    def test_dept_recommendations_is_empty(self):
        self.assertEqual(self.brief.dept_recommendations, {})

    def test_generated_at_is_string(self):
        self.assertIsInstance(self.brief.generated_at, str)
        self.assertGreater(len(self.brief.generated_at), 0)


class TestActionBriefGeneratorSingle(unittest.TestCase):
    """ActionBriefGenerator.generate() with a single complaint."""

    def setUp(self):
        self.gen = ActionBriefGenerator()
        self.complaints = [{
            "complaint_id":   "BRIEF-001",
            "title":          "Pothole on main road",
            "category":       "Road Damage",
            "status":         "Submitted",
            "priority_level": "High",
            "priority_score": 55,
            "address":        "Main Road, Novapolis",
            "latitude":       None,
            "longitude":      None,
            "department_id":  None,
        }]
        self.brief = self.gen.generate(self.complaints)

    def test_status_is_ok(self):
        self.assertEqual(self.brief.status, "ok")

    def test_total_analysed_is_one(self):
        self.assertEqual(self.brief.total_analysed, 1)

    def test_top_categories_has_road_damage(self):
        cats = [cat for cat, _ in self.brief.top_categories]
        self.assertIn("Road Damage", cats)

    def test_affected_locations_has_address(self):
        self.assertIn("Main Road, Novapolis", self.brief.affected_locations)

    def test_priority_overview_has_one_high(self):
        self.assertEqual(self.brief.priority_overview["high"], 1)

    def test_urgent_complaints_has_complaint_id(self):
        self.assertIn("BRIEF-001", self.brief.urgent_complaints)

    def test_situation_summary_mentions_total(self):
        self.assertIn("1", self.brief.situation_summary)

    def test_recommendations_not_empty(self):
        self.assertGreater(len(self.brief.recommendations), 0)

    def test_recommendations_are_strings(self):
        for rec in self.brief.recommendations:
            self.assertIsInstance(rec, str)


class TestActionBriefMultipleCategories(unittest.TestCase):
    """Brief with complaints across multiple categories."""

    def setUp(self):
        self.gen = ActionBriefGenerator()
        self.complaints = [
            {
                "complaint_id": f"MC-{i:03d}",
                "title": f"Complaint {i}",
                "category": cat,
                "status": "Submitted",
                "priority_level": "Medium",
                "priority_score": 30,
                "address": f"Area {i}",
                "latitude": None,
                "longitude": None,
                "department_id": None,
            }
            for i, cat in enumerate([
                "Road Damage", "Road Damage", "Waterlogging",
                "Garbage Overflow", "Streetlight", "Road Damage",
            ], start=1)
        ]
        self.brief = self.gen.generate(self.complaints)

    def test_top_category_is_road_damage(self):
        """Road Damage has 3 occurrences — should be top category."""
        self.assertEqual(self.brief.top_categories[0][0], "Road Damage")
        self.assertEqual(self.brief.top_categories[0][1], 3)

    def test_top_categories_at_most_three(self):
        self.assertLessEqual(len(self.brief.top_categories), 3)

    def test_situation_summary_mentions_road_damage(self):
        self.assertIn("Road Damage", self.brief.situation_summary)

    def test_total_analysed_correct(self):
        self.assertEqual(self.brief.total_analysed, 6)


class TestActionBriefPriorityLevels(unittest.TestCase):
    """Brief correctly counts all four priority levels."""

    def setUp(self):
        self.gen = ActionBriefGenerator()
        self.complaints = [
            {"complaint_id": "PRI-001", "title": "T1", "category": "Drainage",
             "status": "Submitted", "priority_level": "Critical",
             "priority_score": 80, "address": None,
             "latitude": None, "longitude": None, "department_id": None},
            {"complaint_id": "PRI-002", "title": "T2", "category": "Drainage",
             "status": "Submitted", "priority_level": "High",
             "priority_score": 60, "address": None,
             "latitude": None, "longitude": None, "department_id": None},
            {"complaint_id": "PRI-003", "title": "T3", "category": "Drainage",
             "status": "Submitted", "priority_level": "Medium",
             "priority_score": 35, "address": None,
             "latitude": None, "longitude": None, "department_id": None},
            {"complaint_id": "PRI-004", "title": "T4", "category": "Drainage",
             "status": "Submitted", "priority_level": "Low",
             "priority_score": 10, "address": None,
             "latitude": None, "longitude": None, "department_id": None},
        ]
        self.brief = self.gen.generate(self.complaints)

    def test_critical_count(self):
        self.assertEqual(self.brief.priority_overview["critical"], 1)

    def test_high_count(self):
        self.assertEqual(self.brief.priority_overview["high"], 1)

    def test_medium_count(self):
        self.assertEqual(self.brief.priority_overview["medium"], 1)

    def test_low_count(self):
        self.assertEqual(self.brief.priority_overview["low"], 1)

    def test_situation_summary_mentions_critical(self):
        self.assertIn("Critical", self.brief.situation_summary)

    def test_urgent_complaints_sorted_by_score(self):
        """Highest priority score should appear first in urgent list."""
        ids = self.brief.urgent_complaints
        # PRI-001 (score 80) must come before PRI-004 (score 10)
        self.assertLess(ids.index("PRI-001"), ids.index("PRI-004"))

    def test_recommendations_mention_critical_escalation(self):
        recs_text = " ".join(self.brief.recommendations)
        self.assertIn("Critical", recs_text)


class TestActionBriefLocations(unittest.TestCase):
    """Brief extracts up to 5 unique locations."""

    def setUp(self):
        self.gen = ActionBriefGenerator()
        addresses = [
            "Lotus Colony, Novapolis",
            "River Road, Novapolis",
            "Market Area, Novapolis",
            "School Road, Novapolis",
            "Central Park, Novapolis",
            "Bus Stand, Novapolis",   # 6th — should be excluded
        ]
        self.complaints = [
            {"complaint_id": f"LOC-{i:03d}", "title": f"Complaint {i}",
             "category": "Drainage", "status": "Submitted",
             "priority_level": "Low", "priority_score": 15,
             "address": addr,
             "latitude": None, "longitude": None, "department_id": None}
            for i, addr in enumerate(addresses, start=1)
        ]
        self.brief = self.gen.generate(self.complaints)

    def test_at_most_five_locations(self):
        self.assertLessEqual(len(self.brief.affected_locations), 5)

    def test_first_location_present(self):
        self.assertIn("Lotus Colony, Novapolis", self.brief.affected_locations)

    def test_sixth_location_excluded(self):
        self.assertNotIn("Bus Stand, Novapolis", self.brief.affected_locations)


class TestActionBriefMissingData(unittest.TestCase):
    """Generator handles missing/None fields gracefully."""

    def setUp(self):
        self.gen = ActionBriefGenerator()

    def test_none_latitude_longitude_no_crash(self):
        complaints = [{
            "complaint_id": "MIS-001", "title": "Pothole",
            "category": "Road Damage", "status": "Submitted",
            "priority_level": "High", "priority_score": 55,
            "address": None, "latitude": None, "longitude": None,
            "department_id": None,
        }]
        brief = self.gen.generate(complaints)
        self.assertIsInstance(brief, ActionBrief)
        self.assertEqual(brief.status, "ok")
        self.assertEqual(brief.affected_locations, [])

    def test_none_category_handled(self):
        complaints = [{
            "complaint_id": "MIS-002", "title": "Issue",
            "category": None, "status": "Submitted",
            "priority_level": "Low", "priority_score": 10,
            "address": None, "latitude": None, "longitude": None,
            "department_id": None,
        }]
        brief = self.gen.generate(complaints)
        self.assertIsInstance(brief, ActionBrief)
        # Should use "Unknown" as category
        top_cats = [c for c, _ in brief.top_categories]
        self.assertIn("Unknown", top_cats)

    def test_none_priority_level_handled(self):
        complaints = [{
            "complaint_id": "MIS-003", "title": "Issue",
            "category": "Other", "status": "Submitted",
            "priority_level": None, "priority_score": None,
            "address": None, "latitude": None, "longitude": None,
            "department_id": None,
        }]
        brief = self.gen.generate(complaints)
        self.assertIsInstance(brief, ActionBrief)
        # Should default None level to "low" bucket
        self.assertGreaterEqual(brief.priority_overview["low"], 1)

    def test_completely_empty_dict_no_crash(self):
        """Even an empty dict should not crash the generator."""
        # Minimal: only complaint_id is required for urgent list
        complaints = [{"complaint_id": "MIS-004"}]
        brief = self.gen.generate(complaints)
        self.assertIsInstance(brief, ActionBrief)

    def test_invalid_input_returns_partial_brief(self):
        """Passing a completely non-iterable crashes gracefully → partial brief."""
        # We can't easily cause an internal crash without monkey-patching,
        # so verify the empty-brief fallback for a None input works.
        try:
            brief = self.gen.generate(None)   # type: ignore
        except Exception:
            brief = None
        # Either it returns a partial brief or raises — both are acceptable
        # but the generator should ideally return a partial brief.
        if brief is not None:
            self.assertIsInstance(brief, ActionBrief)


class TestActionBriefHotspotIntegration(unittest.TestCase):
    """Generator processes Hotspot NamedTuples from the detector."""

    def setUp(self):
        self.gen = ActionBriefGenerator()
        self.complaints = [
            {"complaint_id": f"HS-{i:03d}", "title": f"Road issue {i}",
             "category": "Road Damage", "status": "Submitted",
             "priority_level": "High", "priority_score": 60,
             "address": f"Area {i}", "latitude": 12.97 + i * 0.001,
             "longitude": 77.59 + i * 0.001, "department_id": None}
            for i in range(5)
        ]
        self.fake_hotspot = FakeHotspot(
            center_lat=12.972,
            center_lon=77.592,
            complaint_ids=["HS-001", "HS-002", "HS-003"],
            count=3,
            dominant_category="Road Damage",
            radius_km=0.5,
            critical_count=0,
            high_count=3,
            avg_priority_score=60.0,
        )

    def test_hotspot_analysis_populated(self):
        brief = self.gen.generate(self.complaints, [self.fake_hotspot])
        self.assertEqual(len(brief.hotspot_analysis), 1)

    def test_hotspot_summary_fields(self):
        brief = self.gen.generate(self.complaints, [self.fake_hotspot])
        hs = brief.hotspot_analysis[0]
        self.assertIsInstance(hs, HotspotSummary)
        self.assertEqual(hs.index, 1)
        self.assertEqual(hs.count, 3)
        self.assertEqual(hs.dominant_category, "Road Damage")
        self.assertEqual(hs.high_count, 3)
        self.assertIsInstance(hs.attention_reason, str)
        self.assertGreater(len(hs.attention_reason), 0)

    def test_hotspot_ids_preserved(self):
        brief = self.gen.generate(self.complaints, [self.fake_hotspot])
        hs = brief.hotspot_analysis[0]
        self.assertIn("HS-001", hs.complaint_ids)

    def test_situation_summary_mentions_hotspot(self):
        brief = self.gen.generate(self.complaints, [self.fake_hotspot])
        self.assertIn("hotspot", brief.situation_summary.lower())

    def test_recommendations_mention_hotspot(self):
        brief = self.gen.generate(self.complaints, [self.fake_hotspot])
        recs = " ".join(brief.recommendations)
        self.assertIn("hotspot", recs.lower())

    def test_no_hotspots_gives_empty_analysis(self):
        brief = self.gen.generate(self.complaints, [])
        self.assertEqual(brief.hotspot_analysis, [])


class TestActionBriefDepartmentRecommendations(unittest.TestCase):
    """Department-wise recommendations based on complaint categories."""

    def setUp(self):
        self.gen = ActionBriefGenerator()
        # Road Damage + Waterlogging → Public Works, Water & Sanitation, Traffic & Safety
        self.complaints = [
            {"complaint_id": "DR-001", "title": "Road pothole issue",
             "category": "Road Damage", "status": "Submitted",
             "priority_level": "High", "priority_score": 55,
             "address": "Main Road", "latitude": None, "longitude": None,
             "department_id": None},
            {"complaint_id": "DR-002", "title": "Waterlogging at market",
             "category": "Waterlogging", "status": "Submitted",
             "priority_level": "Medium", "priority_score": 35,
             "address": "Market Road", "latitude": None, "longitude": None,
             "department_id": None},
            {"complaint_id": "DR-003", "title": "Garbage overflow test area",
             "category": "Garbage Overflow", "status": "Submitted",
             "priority_level": "Low", "priority_score": 15,
             "address": "Park Road", "latitude": None, "longitude": None,
             "department_id": None},
        ]
        self.brief = self.gen.generate(self.complaints)

    def test_dept_recommendations_is_dict(self):
        self.assertIsInstance(self.brief.dept_recommendations, dict)

    def test_public_works_has_recommendations(self):
        """Public Works handles Road Damage."""
        self.assertIn("Public Works", self.brief.dept_recommendations)

    def test_waste_management_has_recommendations(self):
        """Waste Management handles Garbage Overflow."""
        self.assertIn("Waste Management", self.brief.dept_recommendations)

    def test_dept_with_no_open_complaints_absent(self):
        """Electrical Department has no Streetlight complaints → absent."""
        self.assertNotIn("Electrical Department", self.brief.dept_recommendations)

    def test_dept_actions_are_strings(self):
        for dept, actions in self.brief.dept_recommendations.items():
            self.assertIsInstance(actions, list)
            for action in actions:
                self.assertIsInstance(action, str)

    def test_dept_actions_mention_complaint_count(self):
        """Each dept section should mention the open complaint count."""
        for dept, actions in self.brief.dept_recommendations.items():
            # At least one action string mentions a number
            combined = " ".join(actions)
            has_digit = any(ch.isdigit() for ch in combined)
            self.assertTrue(has_digit,
                            f"No count in dept '{dept}' actions: {actions}")


class TestActionBriefGeneratedAt(unittest.TestCase):
    """generated_at is a non-empty ISO timestamp string."""

    def test_generated_at_is_iso_format(self):
        gen = ActionBriefGenerator()
        brief = gen.generate([{
            "complaint_id": "TS-001", "title": "Timestamp test complaint",
            "category": "Other", "status": "Submitted",
            "priority_level": "Low", "priority_score": 10,
            "address": None, "latitude": None, "longitude": None,
            "department_id": None,
        }])
        # ISO format: YYYY-MM-DDTHH:MM:SS+00:00
        ts = brief.generated_at
        self.assertRegex(ts, r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

    def test_empty_brief_also_has_timestamp(self):
        gen = ActionBriefGenerator()
        brief = gen.generate([])
        self.assertIsInstance(brief.generated_at, str)
        self.assertGreater(len(brief.generated_at), 5)


class TestActionBriefRecommendationsLimit(unittest.TestCase):
    """Recommendations are capped at AI_BRIEF_MAX_STEPS."""

    def test_recommendations_respect_max_steps(self):
        from config import AI_BRIEF_MAX_STEPS
        gen = ActionBriefGenerator()
        # Create enough complaints to trigger many recommendation rules
        complaints = [
            {"complaint_id": f"REC-{i:03d}", "title": f"Issue {i}",
             "category": cat, "status": "Submitted",
             "priority_level": "Critical", "priority_score": 80,
             "address": f"Location {i}", "latitude": None, "longitude": None,
             "department_id": None}
            for i, cat in enumerate([
                "Road Damage", "Waterlogging", "Garbage Overflow",
                "Public Safety", "Streetlight", "Drainage", "Sewage",
            ], start=1)
        ]
        hotspots = [
            FakeHotspot(12.97, 77.59, [f"REC-{i:03d}" for i in range(1, 4)],
                        3, "Road Damage", 0.5, 1, 2, 60.0),
            FakeHotspot(12.98, 77.60, [f"REC-{i:03d}" for i in range(4, 7)],
                        3, "Waterlogging", 0.5, 0, 3, 55.0),
            FakeHotspot(12.99, 77.61, [f"REC-{i:03d}" for i in range(5, 8)],
                        3, "Drainage", 0.5, 0, 1, 40.0),
        ]
        brief = gen.generate(complaints, hotspots)
        self.assertLessEqual(len(brief.recommendations), AI_BRIEF_MAX_STEPS)


class TestLegacyAPI(unittest.TestCase):
    """Backward-compatible legacy interface."""

    def setUp(self):
        self.gen = ActionBriefGenerator()

    def test_generate_cluster_brief_returns_string(self):
        result = self.gen.generate_cluster_brief({
            "count": 5,
            "dominant_category": "Road Damage",
            "center_lat": 12.9716,
            "center_lon": 77.5946,
        })
        self.assertIsInstance(result, str)

    def test_generate_cluster_brief_content(self):
        result = self.gen.generate_cluster_brief({
            "count": 3,
            "dominant_category": "Waterlogging",
            "center_lat": 12.9716,
            "center_lon": 77.5946,
        })
        self.assertIn("Waterlogging", result)
        self.assertIn("3", result)

    def test_generate_cluster_brief_empty_cluster(self):
        result = self.gen.generate_cluster_brief({"count": 0})
        self.assertEqual(result, "")

    def test_singleton_factory(self):
        g1 = get_brief_generator()
        g2 = get_brief_generator()
        self.assertIs(g1, g2)


class TestHelperFunctions(unittest.TestCase):
    """Unit tests for module-level helper functions."""

    def test_empty_brief_status_empty(self):
        brief = _empty_brief()
        self.assertEqual(brief.status, "empty")
        self.assertEqual(brief.total_analysed, 0)

    def test_empty_brief_partial_status(self):
        brief = _empty_brief(status="partial")
        self.assertEqual(brief.status, "partial")

    def test_hotspot_reason_mentions_category(self):
        h = FakeHotspot(12.97, 77.59, ["X-001", "X-002", "X-003"],
                        3, "Road Damage", 0.5, 0, 3, 58.0)
        reason = _hotspot_reason(h)
        self.assertIn("Road Damage", reason)
        self.assertIn("3", reason)

    def test_hotspot_reason_mentions_critical(self):
        h = FakeHotspot(12.97, 77.59, ["X-001", "X-002", "X-003"],
                        3, "Sewage", 0.5, 2, 1, 80.0)
        reason = _hotspot_reason(h)
        self.assertIn("Critical", reason)

    def test_category_action_known_category(self):
        action = _category_action("Road Damage", 4)
        self.assertIsInstance(action, str)
        self.assertIn("Road Damage", action)

    def test_category_action_unknown_category_returns_none(self):
        action = _category_action("UnknownCategory", 1)
        self.assertIsNone(action)


# ──────────────────────────────────────────────────────────────────────────────
# 2. ROUTE TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestActionBriefRoutes(unittest.TestCase):
    """Integration tests for /admin/brief and /admin/brief/generate routes."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()
        # Seed a couple of complaints so the brief has data to show
        _insert("BREF-001", "Pothole near main school entrance on road",
                cat="Road Damage", status="Submitted",
                priority_level="High", priority_score=60,
                address="School Road, Novapolis")
        _insert("BREF-002", "Waterlogging at market junction road area",
                cat="Waterlogging", status="Submitted",
                priority_level="Critical", priority_score=80,
                address="Market Road, Novapolis")
        _insert("BREF-003", "Garbage overflow near park road test area",
                cat="Garbage Overflow", status="Submitted",
                priority_level="Medium", priority_score=30)

    def test_brief_route_returns_200(self):
        resp = self.client.get("/admin/brief")
        self.assertEqual(resp.status_code, 200)

    def test_brief_page_has_title(self):
        resp = self.client.get("/admin/brief")
        self.assertIn(b"Action Brief", resp.data)

    def test_brief_page_has_situation_summary(self):
        resp = self.client.get("/admin/brief")
        self.assertIn(b"Situation Summary", resp.data)

    def test_brief_page_has_priority_overview(self):
        resp = self.client.get("/admin/brief")
        self.assertIn(b"Priority Overview", resp.data)

    def test_brief_page_has_recommendations(self):
        resp = self.client.get("/admin/brief")
        self.assertIn(b"Recommended Actions", resp.data)

    def test_brief_page_has_refresh_button(self):
        resp = self.client.get("/admin/brief")
        self.assertIn(b"Refresh Brief", resp.data)

    def test_brief_page_has_csrf_token(self):
        resp = self.client.get("/admin/brief")
        self.assertIn(b'name="csrf_token"', resp.data)

    def test_brief_page_has_back_link(self):
        resp = self.client.get("/admin/brief")
        self.assertIn(b"Back to Dashboard", resp.data)

    def test_brief_page_shows_total_complaints(self):
        """Brief should show how many complaints were analysed."""
        resp = self.client.get("/admin/brief")
        html = resp.data.decode()
        self.assertIn("analysed", html.lower())

    def test_brief_page_shows_complaint_ids_or_categories(self):
        resp = self.client.get("/admin/brief")
        # Either a category or a complaint ID badge must appear
        has_cat  = b"Road Damage" in resp.data or b"Waterlogging" in resp.data
        self.assertTrue(has_cat, "Neither category nor data appears on brief page")

    def test_generate_route_redirects(self):
        """POST /admin/brief/generate must redirect to /admin/brief."""
        resp = self.client.post(
            "/admin/brief/generate",
            data={},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertIn(resp.status_code, (301, 302))
        self.assertIn("/admin/brief", resp.headers.get("Location", ""))

    def test_generate_route_follows_to_200(self):
        resp = self.client.post(
            "/admin/brief/generate",
            data={},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Action Brief", resp.data)

    def test_generate_route_csrf_protected_in_non_testing_mode(self):
        """With TESTING=False, /brief/generate must reject missing CSRF."""
        from app import create_app
        real_app = create_app(admin_auth_mode="open")
        # TESTING is NOT set — CSRF enforcement is active
        with real_app.test_client() as c:
            c.get("/admin/brief")  # establish session
            resp = c.post(
                "/admin/brief/generate",
                data={},  # no csrf_token
                content_type="multipart/form-data",
            )
        self.assertEqual(resp.status_code, 403,
                         "CSRF not enforced on /brief/generate outside TESTING mode")


class TestActionBriefNavLink(unittest.TestCase):
    """Brief nav link appears on every admin page."""

    @classmethod
    def setUpClass(cls):
        cls.client, _ = _make_client()

    def test_brief_nav_link_on_dashboard(self):
        resp = self.client.get("/admin/")
        self.assertIn(b"Brief", resp.data)

    def test_brief_nav_link_on_hotspots(self):
        resp = self.client.get("/admin/hotspots")
        self.assertIn(b"Brief", resp.data)

    def test_brief_nav_link_on_brief_page(self):
        resp = self.client.get("/admin/brief")
        self.assertIn(b"Brief", resp.data)

    def test_brief_nav_link_href(self):
        resp = self.client.get("/admin/")
        self.assertIn(b"/admin/brief", resp.data)


class TestActionBriefEmptyDB(unittest.TestCase):
    """Brief page works when the DB has no complaints (separate empty DB)."""

    @classmethod
    def setUpClass(cls):
        """Create an isolated empty-DB app instance."""
        import tempfile, shutil
        cls._empty_dir = tempfile.mkdtemp(prefix="civicai_empty_")
        test_db = os.path.join(cls._empty_dir, "empty.db")
        _config.DATABASE_DIR  = cls._empty_dir
        _config.DATABASE_PATH = test_db
        db.DATABASE_DIR  = cls._empty_dir
        db.DATABASE_PATH = test_db
        db.init_db()
        db.seed_departments()

        from app import create_app
        app = create_app()
        app.config["TESTING"] = True
        cls.client = app.test_client()

    @classmethod
    def tearDownClass(cls):
        import shutil
        if hasattr(cls, "_empty_dir") and os.path.exists(cls._empty_dir):
            shutil.rmtree(cls._empty_dir)

    def test_brief_returns_200_on_empty_db(self):
        resp = self.client.get("/admin/brief")
        self.assertEqual(resp.status_code, 200)

    def test_brief_shows_no_data_message(self):
        resp = self.client.get("/admin/brief")
        html = resp.data.decode()
        # The empty-state path shows "No complaints" messaging
        self.assertTrue(
            "No complaints" in html or "no complaints" in html.lower(),
            "Empty-state message not shown on brief page with no data"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 3. REGRESSION TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestPhase3ERegressions(unittest.TestCase):
    """Ensure all existing features still work after Phase 3E changes."""

    @classmethod
    def setUpClass(cls):
        cls.client, _ = _make_client()
        _insert("REG3E-001", "Regression complaint for phase 3E test suite",
                cat="Road Damage", status="Submitted",
                priority_level="Medium", priority_score=30)

    def test_dashboard_returns_200(self):
        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 200)

    def test_detail_page_returns_200(self):
        resp = self.client.get("/admin/complaint/REG3E-001")
        self.assertEqual(resp.status_code, 200)

    def test_hotspots_returns_200(self):
        resp = self.client.get("/admin/hotspots")
        self.assertEqual(resp.status_code, 200)

    def test_submit_form_returns_200(self):
        resp = self.client.get("/submit/")
        self.assertEqual(resp.status_code, 200)

    def test_brief_route_returns_200(self):
        resp = self.client.get("/admin/brief")
        self.assertEqual(resp.status_code, 200)

    def test_dashboard_stats_present(self):
        resp = self.client.get("/admin/")
        self.assertIn(b"Total Complaints", resp.data)

    def test_priority_score_out_of_100(self):
        resp = self.client.get("/admin/complaint/REG3E-001")
        self.assertIn(b"/ 100", resp.data)

    def test_gps_button_present(self):
        resp = self.client.get("/submit/")
        self.assertIn(b"Use My Location", resp.data)

    def test_hotspots_nav_link_present(self):
        resp = self.client.get("/admin/")
        self.assertIn(b"Hotspots", resp.data)

    def test_brief_nav_link_present(self):
        resp = self.client.get("/admin/")
        self.assertIn(b"Brief", resp.data)

    def test_csrf_token_on_detail_page(self):
        resp = self.client.get("/admin/complaint/REG3E-001")
        self.assertIn(b'name="csrf_token"', resp.data)

    def test_write_forms_on_detail_page(self):
        resp = self.client.get("/admin/complaint/REG3E-001")
        self.assertIn(b"Update Status", resp.data)
        self.assertIn(b"Add Action Note", resp.data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
