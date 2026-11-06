"""
tests/test_ai.py – CivicAI Phase 3 AI Tests

Covers:
  Categorisation (TestCategoryClassifier):
    - Road damage prediction
    - Garbage complaint prediction
    - Water supply prediction
    - Public safety prediction
    - Low-confidence handling (ambiguous text)
    - Citizen-selected category preservation
    - Model failure fallback (mocked exception)
    - Returns CategoryResult NamedTuple with correct fields

  Duplicate detection (TestDuplicateDetector):
    - Identical complaint → similarity ≈ 1.0
    - Very similar complaint → above 0.40
    - Unrelated complaint → below threshold (no match)
    - score_pair() returns float 0–1
    - Multiple duplicate matches returned
    - Self-matching prevention
    - Duplicate relationship DB insertion
    - Exception during find_duplicates returns []

  AI Engine orchestrator (TestAIEngine):
    - process_complaint returns expected keys
    - ai_category field is populated
    - citizen category is preserved in DB (never overwritten)
    - duplicate_matches list present in result
    - Engine failure → safe defaults returned

  Integration (TestAIIntegration):
    - New complaint via POST /submit/ receives AI categorisation in DB
    - New complaint via POST /submit/ receives duplicate analysis (DB check)
    - Existing Phase 1 / Phase 2 complaints remain intact
    - Dashboard filters (category, status, priority, search) still work

All tests are offline — no internet access required.
Mocked models use unittest.mock.patch.
"""

import os
import sys
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as _config
import database as db

# ── Temp DB setup ──────────────────────────────────────────────────────────────

_TEST_DIR   = None
_UPLOAD_DIR = None


def setUpModule():
    global _TEST_DIR, _UPLOAD_DIR
    _TEST_DIR   = tempfile.mkdtemp(prefix="civicai_ai_test_")
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


# ── Flask test client ──────────────────────────────────────────────────────────

def _make_client():
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client(), app


# ── Helper: insert a complaint row directly ────────────────────────────────────

def _insert_complaint(cid, title, desc, cat="Road Damage"):
    with db.db_cursor() as (conn, cur):
        cur.execute(
            """INSERT OR IGNORE INTO complaints
               (complaint_id, title, description, category)
               VALUES (?, ?, ?, ?);""",
            (cid, title, desc, cat),
        )


# ──────────────────────────────────────────────────────────────────────────────
# 1. CATEGORISATION TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestCategoryClassifier(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from ai.category_classifier import CategoryClassifier
        cls.clf = CategoryClassifier()

    def test_road_damage_prediction(self):
        r = self.clf.classify(
            "Deep pothole on MG Road causing accidents",
            "There is a very deep pothole near the MG Road junction. "
            "Two bikes have already skidded off the damaged road surface.",
        )
        self.assertEqual(r.category, "Road Damage",
                         f"Expected Road Damage, got {r.category}")
        self.assertGreater(r.confidence, 0.5)

    def test_garbage_prediction(self):
        r = self.clf.classify(
            "Garbage bins not collected for three days",
            "The public garbage bin at Central Park has not been collected "
            "for three days. Waste is spilling onto the footpath.",
        )
        self.assertEqual(r.category, "Garbage Overflow",
                         f"Expected Garbage Overflow, got {r.category}")
        self.assertGreater(r.confidence, 0.5)

    def test_water_supply_prediction(self):
        r = self.clf.classify(
            "No water supply in Sector 7 for 48 hours",
            "Residents of Sector 7 have had no piped water supply for 48 hours. "
            "Families are buying water at very high cost.",
        )
        self.assertEqual(r.category, "Water Supply",
                         f"Expected Water Supply, got {r.category}")
        self.assertGreater(r.confidence, 0.5)

    def test_public_safety_prediction(self):
        r = self.clf.classify(
            "Exposed live electrical wire on Oak Avenue footpath",
            "A live electrical wire is dangling from a broken pole near the bus stand. "
            "The wire touched a metal railing and caused sparks. Children walk here daily.",
        )
        self.assertEqual(r.category, "Public Safety",
                         f"Expected Public Safety, got {r.category}")
        self.assertGreater(r.confidence, 0.5)

    def test_streetlight_prediction(self):
        r = self.clf.classify(
            "Broken streetlight near children park entrance",
            "The streetlight directly in front of the children play area has been "
            "broken for two weeks. The area is pitch dark at night and feels unsafe.",
        )
        self.assertEqual(r.category, "Streetlight",
                         f"Expected Streetlight, got {r.category}")

    def test_waterlogging_prediction(self):
        r = self.clf.classify(
            "Severe waterlogging in Nehru Street residential area",
            "Nehru Street has standing water more than one foot deep. "
            "Residents cannot leave their homes. Water is entering ground-floor houses.",
        )
        self.assertEqual(r.category, "Waterlogging",
                         f"Expected Waterlogging, got {r.category}")

    def test_low_confidence_sets_needs_review(self):
        """Genuinely ambiguous text should set needs_review=True."""
        clf_low = __import__("ai.category_classifier", fromlist=["CategoryClassifier"])
        from ai.category_classifier import CategoryClassifier
        clf = CategoryClassifier(confidence_threshold=0.99)   # extremely strict
        r = clf.classify("Some issue", "There is a problem here somewhere.")
        self.assertTrue(r.needs_review,
                        "Low-confidence prediction must set needs_review=True")

    def test_result_has_all_fields(self):
        """CategoryResult NamedTuple must have all four required fields."""
        r = self.clf.classify("Pothole on road", "Large pothole on main road causing damage.")
        self.assertIsNotNone(r.category)
        self.assertIsInstance(r.confidence, float)
        self.assertIsInstance(r.explanation, str)
        self.assertIsInstance(r.needs_review, bool)

    def test_confidence_between_0_and_1(self):
        r = self.clf.classify(
            "Waterlogging after rain in Brigade Road underpass",
            "The underpass floods to knee level within 30 minutes of rainfall.",
        )
        self.assertGreaterEqual(r.confidence, 0.0)
        self.assertLessEqual(r.confidence, 1.0)

    def test_model_failure_fallback(self):
        """If _classify_inner raises, classify() must return a safe fallback."""
        from ai.category_classifier import CategoryClassifier
        clf = CategoryClassifier()
        with patch.object(clf, "_classify_inner", side_effect=RuntimeError("model crashed")):
            r = clf.classify("test title", "test description")
        self.assertEqual(r.category, "Other")
        self.assertEqual(r.confidence, 0.0)
        self.assertTrue(r.needs_review)
        self.assertIn("error", r.explanation.lower())

    def test_citizen_category_not_overwritten(self):
        """Classifier returns AI prediction but never touches citizen category col."""
        cid = "CAT-PRESERVE-001"
        _insert_complaint(cid, "Broken road near school", "Large cracks in the road surface.", "Road Damage")
        r = self.clf.classify("Broken road near school", "Large cracks in the road surface.")
        # Save AI result
        db.save_ai_results(cid, r.category, r.confidence, r.explanation, r.needs_review)
        # Fetch back
        row = db.get_complaint_by_id(cid)
        self.assertEqual(row["category"], "Road Damage",  # original preserved
                         "Citizen category must never be overwritten")
        self.assertEqual(row["ai_category"], r.category,   # AI stored separately
                         "AI category must be stored in ai_category")


# ──────────────────────────────────────────────────────────────────────────────
# 2. DUPLICATE DETECTION TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestDuplicateDetector(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from ai.duplicate_detector import DuplicateDetector
        # Use a low threshold so similar (not just identical) complaints match
        cls.det = DuplicateDetector(threshold=0.30)

        cls.existing = [
            {
                "complaint_id": "DUP-ORIG-001",
                "title": "Deep pothole on MG Road causing accidents",
                "description": "There is a very deep pothole near the MG Road junction "
                               "with 1st Cross. Two bikes have already skidded.",
            },
            {
                "complaint_id": "DUP-ORIG-002",
                "title": "Garbage overflow at City Market bins",
                "description": "All four garbage bins at City Market have been "
                               "overflowing since Monday. The stench is affecting shops.",
            },
            {
                "complaint_id": "DUP-ORIG-003",
                "title": "Waterlogging after heavy rain on Brigade Road",
                "description": "The underpass at Brigade Road floods to knee level "
                               "within 30 minutes of moderate rainfall.",
            },
        ]

    def test_identical_complaint_detected(self):
        """Exact duplicate should return similarity_score == 1.0."""
        matches = self.det.find_duplicates(
            "DUP-NEW-001",
            "Deep pothole on MG Road causing accidents",
            "There is a very deep pothole near the MG Road junction "
            "with 1st Cross. Two bikes have already skidded.",
            self.existing,
        )
        self.assertTrue(any(m.complaint_id == "DUP-ORIG-001" for m in matches),
                        "Identical complaint not detected")
        match = next(m for m in matches if m.complaint_id == "DUP-ORIG-001")
        self.assertAlmostEqual(match.similarity_score, 1.0, places=2)

    def test_similar_complaint_detected(self):
        """Clearly similar complaint should score above 0.30 threshold."""
        score = self.det.score_pair(
            "Deep pothole on MG Road causing accidents",
            "Very deep dangerous pothole at MG Road junction causing vehicle skids",
            "Deep pothole on MG Road causing accidents",
            "There is a very deep pothole near the MG Road junction "
            "with 1st Cross. Two bikes have already skidded.",
        )
        self.assertGreater(score, 0.30, f"Expected similar score > 0.30, got {score}")

    def test_unrelated_complaint_no_match(self):
        """Unrelated complaint should not match."""
        matches = self.det.find_duplicates(
            "DUP-NEW-002",
            "Noise pollution from construction near temple",
            "Construction equipment is operating past midnight violating noise norms.",
            self.existing,
        )
        self.assertEqual(matches, [],
                         "Unrelated complaint should produce no duplicate matches")

    def test_score_pair_returns_float(self):
        score = self.det.score_pair("Road damage", "Big pothole",
                                    "Road damage", "Big pothole")
        self.assertIsInstance(score, float)
        self.assertAlmostEqual(score, 1.0, places=2)

    def test_score_pair_range(self):
        s1 = self.det.score_pair("Pothole", "Road crack", "Waterlogging", "Flooded street")
        self.assertGreaterEqual(s1, 0.0)
        self.assertLessEqual(s1, 1.0)

    def test_multiple_matches_returned(self):
        """Two similar complaints should both be returned, sorted desc."""
        existing_multi = [
            {"complaint_id": "M-001", "title": "Pothole on MG Road",
             "description": "Large pothole on MG Road near junction causing accidents."},
            {"complaint_id": "M-002", "title": "Deep pothole MG Road junction",
             "description": "Very deep pothole on MG Road at 1st Cross. Vehicles damaged."},
            {"complaint_id": "M-003", "title": "Unrelated noise issue at park",
             "description": "Loud music being played in the park every evening."},
        ]
        det = __import__("ai.duplicate_detector", fromlist=["DuplicateDetector"]).DuplicateDetector(threshold=0.30)
        matches = det.find_duplicates(
            "M-NEW",
            "Pothole on MG Road near 1st Cross",
            "Deep pothole at MG Road junction causing vehicles to skid.",
            existing_multi,
        )
        # At least the two pothole complaints should match
        matched_ids = [m.complaint_id for m in matches]
        self.assertIn("M-001", matched_ids, "First pothole not detected")
        self.assertIn("M-002", matched_ids, "Second pothole not detected")
        # Sorted descending
        if len(matches) >= 2:
            self.assertGreaterEqual(matches[0].similarity_score,
                                    matches[1].similarity_score,
                                    "Matches must be sorted by similarity descending")

    def test_self_matching_prevented(self):
        """The complaint must never match itself."""
        existing_with_self = self.existing + [
            {
                "complaint_id": "SELF-001",
                "title": "Deep pothole on MG Road causing accidents",
                "description": "There is a very deep pothole near the MG Road junction.",
            }
        ]
        matches = self.det.find_duplicates(
            "SELF-001",
            "Deep pothole on MG Road causing accidents",
            "There is a very deep pothole near the MG Road junction.",
            existing_with_self,
        )
        self.assertFalse(any(m.complaint_id == "SELF-001" for m in matches),
                         "Complaint must not match itself")

    def test_duplicate_link_db_insertion(self):
        """save_duplicate_link must persist and be retrievable."""
        _insert_complaint("DB-DUP-A", "Pothole on road", "Large pothole on main road.", "Road Damage")
        _insert_complaint("DB-DUP-B", "Pothole on main road", "Large pothole causing damage.", "Road Damage")

        db.save_duplicate_link("DB-DUP-A", "DB-DUP-B", 0.87)

        with db.db_cursor() as (conn, cur):
            cur.execute(
                "SELECT * FROM duplicate_links WHERE complaint_id = 'DB-DUP-A';",
            )
            row = cur.fetchone()

        self.assertIsNotNone(row, "Duplicate link not found in DB")
        self.assertEqual(row["matched_complaint_id"], "DB-DUP-B")
        self.assertAlmostEqual(row["similarity_score"], 0.87, places=2)

    def test_duplicate_link_idempotent(self):
        """Saving the same duplicate link twice must not create two rows."""
        _insert_complaint("IDEM-A", "Waterlogging on street", "Standing water on road.", "Waterlogging")
        _insert_complaint("IDEM-B", "Water on road", "Waterlogging on main road.", "Waterlogging")

        db.save_duplicate_link("IDEM-A", "IDEM-B", 0.80)
        db.save_duplicate_link("IDEM-A", "IDEM-B", 0.80)

        with db.db_cursor() as (conn, cur):
            cur.execute(
                "SELECT COUNT(*) FROM duplicate_links "
                "WHERE complaint_id = 'IDEM-A' AND matched_complaint_id = 'IDEM-B';"
            )
            count = cur.fetchone()[0]

        self.assertEqual(count, 1, "Duplicate link must be idempotent (only 1 row)")

    def test_exception_returns_empty_list(self):
        """If find_duplicates raises internally, it must return []."""
        from ai.duplicate_detector import DuplicateDetector
        det = DuplicateDetector(threshold=0.30)
        with patch.object(det, "_find_inner", side_effect=RuntimeError("crash")):
            result = det.find_duplicates("X-001", "title", "desc", [])
        self.assertEqual(result, [], "Exception must produce empty list, not raise")

    def test_empty_existing_complaints(self):
        """When no existing complaints exist, find_duplicates returns []."""
        matches = self.det.find_duplicates("NEW-001", "Road damage", "Pothole.", [])
        self.assertEqual(matches, [])

    def test_duplicate_match_has_explanation(self):
        """Each DuplicateMatch must include a non-empty explanation string."""
        matches = self.det.find_duplicates(
            "EXP-NEW",
            "Deep pothole on MG Road causing accidents",
            "There is a very deep pothole near the MG Road junction "
            "with 1st Cross. Two bikes have already skidded.",
            self.existing,
        )
        self.assertTrue(len(matches) > 0, "Expected at least one match")
        for m in matches:
            self.assertIsInstance(m.explanation, str)
            self.assertGreater(len(m.explanation), 0)


# ──────────────────────────────────────────────────────────────────────────────
# 3. AI ENGINE ORCHESTRATOR TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestAIEngine(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from ai.ai_engine import AIEngine
        cls.engine = AIEngine()

    def test_process_complaint_returns_expected_keys(self):
        result = self.engine.process_complaint(
            complaint_id="ENG-001",
            title="Pothole on road",
            description="Large pothole on main road damaging vehicles.",
            category="Road Damage",
            existing_complaints=[],
        )
        for key in ("ai_category", "ai_confidence", "ai_explanation",
                    "ai_needs_review", "duplicate_matches"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_ai_category_populated(self):
        result = self.engine.process_complaint(
            complaint_id="ENG-002",
            title="Garbage bins overflowing at the market",
            description="The garbage bins at City Market have not been collected for days.",
            category="Garbage Overflow",
            existing_complaints=[],
        )
        self.assertIn(result["ai_category"],
                      _config.COMPLAINT_CATEGORIES,
                      f"ai_category '{result['ai_category']}' not a valid category")

    def test_ai_confidence_in_range(self):
        result = self.engine.process_complaint(
            complaint_id="ENG-003",
            title="Streetlight broken on Lake Road",
            description="Four streetlights on Lake Road are non-functional. "
                        "The area is dark and unsafe at night.",
            category="Streetlight",
            existing_complaints=[],
        )
        self.assertGreaterEqual(result["ai_confidence"], 0.0)
        self.assertLessEqual(result["ai_confidence"], 1.0)

    def test_duplicate_matches_is_list(self):
        result = self.engine.process_complaint(
            complaint_id="ENG-004",
            title="Water supply disrupted in colony",
            description="No water supply for two days in residential colony.",
            category="Water Supply",
            existing_complaints=[],
        )
        self.assertIsInstance(result["duplicate_matches"], list)

    def test_classifier_failure_gives_safe_defaults(self):
        """If classifier raises, engine returns citizen category as fallback."""
        from ai.ai_engine import AIEngine
        engine = AIEngine()
        engine._classifier = None   # simulate load failure
        result = engine.process_complaint(
            complaint_id="ENG-005",
            title="Tree fallen on road",
            description="A large tree has fallen across the road blocking traffic.",
            category="Tree / Vegetation",
            existing_complaints=[],
        )
        # When classifier is None, ai_category defaults to citizen category
        self.assertEqual(result["ai_category"], "Tree / Vegetation")
        self.assertEqual(result["ai_confidence"], 0.0)
        self.assertFalse(result["ai_needs_review"])


# ──────────────────────────────────────────────────────────────────────────────
# 4. INTEGRATION TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestAIIntegration(unittest.TestCase):
    """End-to-end: POST /submit/ → AI pipeline → DB results."""

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()

    def _post_complaint(self, title, description, category="Road Damage",
                        address="Test Street, Novapolis"):
        return self.client.post(
            "/submit/",
            data={
                "title":       title,
                "description": description,
                "category":    category,
                "address":     address,
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )

    def test_submission_receives_ai_category(self):
        """After submission, complaints.ai_category must be populated."""
        resp = self._post_complaint(
            "Garbage bins not collected near the bus stop area",
            "The garbage bins at the central bus stop area have not been collected "
            "for three days. Waste is overflowing and attracting stray animals.",
            category="Garbage Overflow",
        )
        self.assertEqual(resp.status_code, 302)
        cid = resp.headers["Location"].split("/submit/success/")[-1].rstrip("/")

        row = db.get_complaint_by_id(cid)
        self.assertIsNotNone(row)
        self.assertIsNotNone(row["ai_category"],
                             "ai_category must be populated after submission")
        self.assertIn(row["ai_category"], _config.COMPLAINT_CATEGORIES)

    def test_submission_receives_ai_confidence(self):
        """After submission, complaints.ai_confidence must be a float 0–1."""
        resp = self._post_complaint(
            "Streetlight broken near school entrance on main avenue road",
            "The streetlight near the school entrance on Main Avenue has been broken "
            "for two weeks. The area is completely dark at night.",
            category="Streetlight",
        )
        self.assertEqual(resp.status_code, 302)
        cid = resp.headers["Location"].split("/submit/success/")[-1].rstrip("/")

        row = db.get_complaint_by_id(cid)
        self.assertIsNotNone(row["ai_confidence"])
        self.assertGreaterEqual(row["ai_confidence"], 0.0)
        self.assertLessEqual(row["ai_confidence"], 1.0)

    def test_citizen_category_preserved_after_submission(self):
        """
        citizen category column must equal what was submitted,
        even if AI predicts something different.
        """
        resp = self._post_complaint(
            "Road surface broken near old town junction area",
            "The road surface near Old Town has developed large cracks and potholes. "
            "Vehicles are getting damaged every day.",
            category="Road Damage",
        )
        self.assertEqual(resp.status_code, 302)
        cid = resp.headers["Location"].split("/submit/success/")[-1].rstrip("/")

        row = db.get_complaint_by_id(cid)
        self.assertEqual(row["category"], "Road Damage",
                         "Citizen category must never be overwritten by AI")

    def test_duplicate_analysis_runs_after_submission(self):
        """
        After submitting a complaint that is clearly similar to an existing one,
        a duplicate_links row should be created.
        """
        # Insert a 'seed' complaint for the duplicate to match against
        _insert_complaint(
            "DUP-SEED-INT",
            "Waterlogging near Nehru Street residential area house",
            "Nehru Street near House 45 has standing water more than one foot deep. "
            "Residents cannot leave their homes. Water is entering ground-floor houses.",
            "Waterlogging",
        )

        # Submit an almost-identical complaint via the web form
        resp = self._post_complaint(
            "Waterlogging near Nehru Street residential area house",
            "Nehru Street near House 45 has standing water more than one foot deep. "
            "Residents cannot leave their homes. Water entering ground-floor houses.",
            category="Waterlogging",
        )
        self.assertEqual(resp.status_code, 302)
        cid = resp.headers["Location"].split("/submit/success/")[-1].rstrip("/")

        with db.db_cursor() as (conn, cur):
            cur.execute(
                "SELECT * FROM duplicate_links WHERE complaint_id = ?;", (cid,)
            )
            rows = cur.fetchall()

        self.assertGreater(len(rows), 0,
                           f"No duplicate link created for {cid} vs DUP-SEED-INT")
        self.assertIn("DUP-SEED-INT",
                      [r["matched_complaint_id"] for r in rows])

    def test_existing_complaints_intact_after_ai(self):
        """Phase 1 seeded departments and AI do not corrupt existing records."""
        with db.db_cursor() as (conn, cur):
            cur.execute("SELECT COUNT(*) FROM departments;")
            dept_count = cur.fetchone()[0]
        self.assertGreaterEqual(dept_count, 6)

    def test_dashboard_still_works_after_ai(self):
        """Admin dashboard must return 200 and render filter elements."""
        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"filter-priority",  resp.data)
        self.assertIn(b"filter-status",    resp.data)
        self.assertIn(b"filter-category",  resp.data)
        self.assertIn(b"search-input",     resp.data)
        self.assertIn(b"clear-filters",    resp.data)

    def test_detail_page_shows_ai_analysis_section(self):
        """Detail page must contain the AI Analysis sidebar section."""
        # Submit a complaint and check its detail page
        resp = self._post_complaint(
            "Sewage overflow near sunshine colony gate entrance",
            "Manhole near the main gate of Sunshine Colony is overflowing with sewage. "
            "The smell is unbearable and children are getting sick from the fumes.",
            category="Sewage",
        )
        cid = resp.headers["Location"].split("/submit/success/")[-1].rstrip("/")
        detail = self.client.get(f"/admin/complaint/{cid}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"AI Analysis", detail.data)
        self.assertIn(b"Citizen category", detail.data)
        self.assertIn(b"AI prediction",    detail.data)


# ──────────────────────────────────────────────────────────────────────────────
# 5. PRIORITY ENGINE TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestPriorityEngine(unittest.TestCase):
    """
    Tests for ai/priority_engine.py (Phase 3C).
    All tests are pure-Python, no DB, no network.
    """

    @classmethod
    def setUpClass(cls):
        from ai.priority_engine import PriorityEngine
        cls.pe = PriorityEngine()

    # ── Return type and structure ──────────────────────────────────────────────

    def test_returns_priority_result_namedtuple(self):
        """score() must return a PriorityResult NamedTuple."""
        from ai.priority_engine import PriorityResult
        result = self.pe.score("Road Damage", "Pothole on road", "There is a pothole.")
        self.assertIsInstance(result, PriorityResult)

    def test_result_has_all_fields(self):
        """PriorityResult must expose priority_score, priority_level, priority_reason."""
        r = self.pe.score("Road Damage", "Pothole on road", "There is a pothole.")
        self.assertTrue(hasattr(r, "priority_score"))
        self.assertTrue(hasattr(r, "priority_level"))
        self.assertTrue(hasattr(r, "priority_reason"))

    def test_score_is_integer(self):
        """priority_score must be an int."""
        r = self.pe.score("Road Damage", "Pothole on road", "There is a pothole.")
        self.assertIsInstance(r.priority_score, int)

    def test_score_in_range_0_to_100(self):
        """priority_score must be in [0, 100]."""
        r = self.pe.score("Road Damage", "Pothole on road", "There is a pothole.")
        self.assertGreaterEqual(r.priority_score, 0)
        self.assertLessEqual(r.priority_score, 100)

    def test_level_is_valid_string(self):
        """priority_level must be one of Low/Medium/High/Critical."""
        r = self.pe.score("Road Damage", "Pothole on road", "There is a pothole.")
        self.assertIn(r.priority_level, ["Low", "Medium", "High", "Critical"])

    def test_reason_is_nonempty_string(self):
        """priority_reason must be a non-empty string."""
        r = self.pe.score("Road Damage", "Pothole on road", "There is a pothole.")
        self.assertIsInstance(r.priority_reason, str)
        self.assertGreater(len(r.priority_reason), 0)

    # ── Level thresholds ───────────────────────────────────────────────────────

    def test_score_to_level_critical(self):
        self.assertEqual(self.pe.score_to_level(75), "Critical")
        self.assertEqual(self.pe.score_to_level(100), "Critical")

    def test_score_to_level_high(self):
        self.assertEqual(self.pe.score_to_level(50), "High")
        self.assertEqual(self.pe.score_to_level(74), "High")

    def test_score_to_level_medium(self):
        self.assertEqual(self.pe.score_to_level(25), "Medium")
        self.assertEqual(self.pe.score_to_level(49), "Medium")

    def test_score_to_level_low(self):
        self.assertEqual(self.pe.score_to_level(0), "Low")
        self.assertEqual(self.pe.score_to_level(24), "Low")

    # ── Category base scores ──────────────────────────────────────────────────

    def test_public_safety_base_is_highest(self):
        """Public Safety must score higher than Road Damage with same neutral description."""
        r_safety = self.pe.score("Public Safety", "Issue near bus stop",
                                 "There is a safety issue near the bus stop.")
        r_road   = self.pe.score("Road Damage",   "Issue near bus stop",
                                 "There is a safety issue near the bus stop.")
        self.assertGreater(r_safety.priority_score, r_road.priority_score)

    def test_noise_pollution_base_is_low(self):
        """Noise Pollution with neutral text should score Low."""
        r = self.pe.score("Noise Pollution", "Loud music in park",
                          "Music is playing loudly in the park.")
        self.assertEqual(r.priority_level, "Low")

    # ── Urgency keyword detection ─────────────────────────────────────────────

    def test_urgency_keyword_raises_score(self):
        """A complaint mentioning 'accident' should score higher than one without."""
        r_urgent = self.pe.score("Road Damage", "Accident on pothole road",
                                 "A serious accident happened due to the pothole.")
        r_normal = self.pe.score("Road Damage", "Pothole on road",
                                 "There is a pothole on the road.")
        self.assertGreater(r_urgent.priority_score, r_normal.priority_score)

    def test_public_safety_with_assault_is_critical(self):
        """Public Safety + assault keyword must reach Critical."""
        r = self.pe.score(
            "Public Safety",
            "Woman assaulted near bus stop",
            "A woman was assaulted near the bus stop on Main Road. Dangerous area.",
        )
        self.assertEqual(r.priority_level, "Critical")

    def test_road_damage_with_collapse_and_injuries_is_critical(self):
        """Road Damage + collapse + injured must reach Critical."""
        r = self.pe.score(
            "Road Damage",
            "Bridge collapsed injuring multiple people",
            "The bridge collapsed. Several people were injured. Emergency services called.",
            duplicate_count=2,
        )
        self.assertEqual(r.priority_level, "Critical")

    # ── Infrastructure risk detection ─────────────────────────────────────────

    def test_infra_keyword_raises_score(self):
        """A complaint mentioning 'no water supply' should score higher than one without."""
        r_infra  = self.pe.score("Water Supply", "No water supply since yesterday",
                                 "There is no water supply in our entire colony.")
        r_normal = self.pe.score("Water Supply", "Water pressure low",
                                 "Water pressure has been low since morning.")
        self.assertGreater(r_infra.priority_score, r_normal.priority_score)

    def test_open_manhole_raises_score(self):
        """Mention of open manhole (infrastructure risk) should raise the score."""
        r_with    = self.pe.score("Drainage", "Open manhole on road",
                                  "There is an uncovered manhole on the main road.")
        r_without = self.pe.score("Drainage", "Drain issue on road",
                                  "There is a drain issue on the main road.")
        self.assertGreater(r_with.priority_score, r_without.priority_score)

    # ── Scope keyword detection ───────────────────────────────────────────────

    def test_scope_keyword_raises_score(self):
        """A complaint affecting 'entire area' should score higher than a single-point one."""
        r_wide   = self.pe.score("Waterlogging", "Waterlogging on MG Road",
                                 "The entire area is flooded. All residents affected.")
        r_narrow = self.pe.score("Waterlogging", "Waterlogging on MG Road",
                                 "There is some water near the bus stop.")
        self.assertGreater(r_wide.priority_score, r_narrow.priority_score)

    # ── Duration keyword detection ────────────────────────────────────────────

    def test_duration_keyword_raises_score(self):
        """A complaint that has persisted 'for months' should score higher."""
        r_long   = self.pe.score("Streetlight", "Broken streetlight",
                                 "This streetlight has been broken for months.")
        r_recent = self.pe.score("Streetlight", "Broken streetlight",
                                 "This streetlight broke this morning.")
        self.assertGreater(r_long.priority_score, r_recent.priority_score)

    # ── Duplicate count bonus ─────────────────────────────────────────────────

    def test_duplicate_count_bonus_raises_score(self):
        """A complaint with 2 confirmed duplicates must score higher than with 0."""
        r_with    = self.pe.score("Garbage Overflow", "Garbage overflow",
                                  "Garbage bins are overflowing.", duplicate_count=2)
        r_without = self.pe.score("Garbage Overflow", "Garbage overflow",
                                  "Garbage bins are overflowing.", duplicate_count=0)
        self.assertGreater(r_with.priority_score, r_without.priority_score)

    def test_duplicate_count_bonus_is_capped(self):
        """Duplicate bonus must not exceed MAX_DUPLICATE_BONUS (15 pts)."""
        r_many = self.pe.score("Road Damage", "Pothole issue", "Big pothole.",
                               duplicate_count=100)
        r_few  = self.pe.score("Road Damage", "Pothole issue", "Big pothole.",
                               duplicate_count=3)
        # Both should have same score because cap of 15 is hit at 3 duplicates
        self.assertEqual(r_many.priority_score, r_few.priority_score)

    # ── Score clamping ────────────────────────────────────────────────────────

    def test_max_score_does_not_exceed_100(self):
        """Even with every signal firing the score must be ≤ 100."""
        r = self.pe.score(
            "Public Safety",
            "Emergency: attacked, injured, fire, collapsed, flooding, electrocution",
            "Entire area affected. No water supply. Power outage. Gas leak. "
            "Road blocked. Hundreds of people injured. This has been going on for months.",
            duplicate_count=100,
        )
        self.assertLessEqual(r.priority_score, 100)

    def test_min_score_is_not_negative(self):
        """Score must never be negative."""
        r = self.pe.score("Other", "X", "Y")
        self.assertGreaterEqual(r.priority_score, 0)

    # ── Reason content ────────────────────────────────────────────────────────

    def test_reason_mentions_category(self):
        """priority_reason should mention the category used."""
        r = self.pe.score("Road Damage", "Pothole on road", "Big pothole.")
        self.assertIn("Road Damage", r.priority_reason)

    def test_reason_mentions_urgency_when_triggered(self):
        """If an urgency signal fires, priority_reason must mention it."""
        r = self.pe.score("Road Damage", "Pothole caused a fatal accident",
                          "A fatal accident happened due to the pothole.")
        self.assertIn("urgency", r.priority_reason.lower())

    # ── AI Engine integration ─────────────────────────────────────────────────

    def test_ai_engine_process_includes_priority_keys(self):
        """process_complaint() must return priority_score, priority_level, priority_reason."""
        from ai.ai_engine import AIEngine
        engine = AIEngine()
        result = engine.process_complaint(
            complaint_id="PRI-TEST-001",
            title="Severe pothole on MG Road causing accidents",
            description="Deep dangerous pothole. Multiple vehicles damaged.",
            category="Road Damage",
            existing_complaints=[],
        )
        self.assertIn("priority_score",  result)
        self.assertIn("priority_level",  result)
        self.assertIn("priority_reason", result)

    def test_ai_engine_priority_score_in_range(self):
        """priority_score returned by AIEngine must be in [0, 100]."""
        from ai.ai_engine import AIEngine
        engine = AIEngine()
        result = engine.process_complaint(
            complaint_id="PRI-TEST-002",
            title="Garbage overflow at market",
            description="Garbage bin overflowing since Monday.",
            category="Garbage Overflow",
            existing_complaints=[],
        )
        self.assertGreaterEqual(result["priority_score"], 0)
        self.assertLessEqual(result["priority_score"], 100)

    def test_ai_engine_priority_failure_gives_safe_defaults(self):
        """If PriorityEngine raises, process_complaint must still succeed."""
        from ai.ai_engine import AIEngine
        engine = AIEngine()
        with patch.object(engine._priority, "score", side_effect=RuntimeError("crash")):
            result = engine.process_complaint(
                complaint_id="PRI-TEST-003",
                title="Test complaint",
                description="Test description.",
                category="Other",
                existing_complaints=[],
            )
        # Should still return safe defaults (no exception propagated)
        self.assertIn("priority_score",  result)
        self.assertEqual(result["priority_level"], "Low")


# ──────────────────────────────────────────────────────────────────────────────
# 6. HOTSPOT DETECTOR TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestHotspotDetector(unittest.TestCase):
    """
    Tests for ai/hotspot_detector.py (Phase 3D).
    All tests are pure-Python — no DB, no HTTP, no network.

    Lotus Colony seed cluster used as the primary fixture:
        CMP-0019  (12.9672, 77.5932)  Drainage
        CMP-0020  (12.9670, 77.5930)  Road Damage
        CMP-0021  (12.9671, 77.5931)  Public Safety
        CMP-0022  (12.9672, 77.5932)  Waterlogging
        CMP-0039  (12.9673, 77.5933)  Drainage
    All five are within ~50 m of each other → well inside 0.5 km.
    """

    # ── Fixtures ──────────────────────────────────────────────────────────────

    LOTUS_CLUSTER = [
        {"complaint_id": "LC-001", "latitude": 12.9672, "longitude": 77.5932,
         "category": "Drainage",      "priority_level": "High",     "priority_score": 52.0},
        {"complaint_id": "LC-002", "latitude": 12.9670, "longitude": 77.5930,
         "category": "Road Damage",   "priority_level": "Medium",   "priority_score": 30.0},
        {"complaint_id": "LC-003", "latitude": 12.9671, "longitude": 77.5931,
         "category": "Public Safety", "priority_level": "Critical",  "priority_score": 80.0},
        {"complaint_id": "LC-004", "latitude": 12.9672, "longitude": 77.5932,
         "category": "Waterlogging",  "priority_level": "High",     "priority_score": 45.0},
        {"complaint_id": "LC-005", "latitude": 12.9673, "longitude": 77.5933,
         "category": "Drainage",      "priority_level": "High",     "priority_score": 48.0},
    ]

    # Two points ~55 km apart from the Lotus cluster — used for
    # the "two separate clusters" and "no cross-contamination" tests.
    NORTH_CLUSTER = [
        {"complaint_id": "NC-001", "latitude": 13.4620, "longitude": 77.5932,
         "category": "Garbage Overflow", "priority_level": "Medium", "priority_score": 20.0},
        {"complaint_id": "NC-002", "latitude": 13.4622, "longitude": 77.5933,
         "category": "Garbage Overflow", "priority_level": "Medium", "priority_score": 22.0},
        {"complaint_id": "NC-003", "latitude": 13.4621, "longitude": 77.5931,
         "category": "Streetlight",      "priority_level": "Low",    "priority_score": 15.0},
    ]

    @classmethod
    def setUpClass(cls):
        from ai.hotspot_detector import HotspotDetector
        cls.det = HotspotDetector(radius_km=0.5, min_complaints=3)

    # ── Return type ───────────────────────────────────────────────────────────

    def test_returns_list(self):
        """detect() must always return a list."""
        result = self.det.detect([])
        self.assertIsInstance(result, list)

    def test_empty_input_returns_empty(self):
        """Empty complaint list → empty hotspot list."""
        self.assertEqual(self.det.detect([]), [])

    # ── Coordinate filtering ──────────────────────────────────────────────────

    def test_missing_lat_lon_skipped(self):
        """Complaints without lat/lon must not form a hotspot."""
        no_coords = [
            {"complaint_id": f"X-{i}", "latitude": None, "longitude": None,
             "category": "Other", "priority_level": "Low", "priority_score": 10.0}
            for i in range(5)
        ]
        self.assertEqual(self.det.detect(no_coords), [])

    def test_invalid_coords_skipped(self):
        """Non-finite, out-of-range, and string coordinates must be filtered out."""
        from ai.hotspot_detector import _is_valid_coord
        import math
        # None
        self.assertFalse(_is_valid_coord(None, None))
        # Non-numeric
        self.assertFalse(_is_valid_coord("12.97", "77.59"))
        # NaN
        self.assertFalse(_is_valid_coord(float("nan"), 77.59))
        # Infinity
        self.assertFalse(_is_valid_coord(float("inf"), 77.59))
        # Latitude out of range
        self.assertFalse(_is_valid_coord(91.0, 77.59))
        self.assertFalse(_is_valid_coord(-91.0, 77.59))
        # Longitude out of range
        self.assertFalse(_is_valid_coord(12.97, 181.0))
        self.assertFalse(_is_valid_coord(12.97, -181.0))
        # Valid boundary values
        self.assertTrue(_is_valid_coord(90.0, 180.0))
        self.assertTrue(_is_valid_coord(-90.0, -180.0))
        self.assertTrue(_is_valid_coord(0.0, 0.0))

    def test_mixed_valid_invalid_coords(self):
        """Only valid-coord rows contribute; if valid count < min_complaints → []."""
        mixed = [
            {"complaint_id": "V-001", "latitude": 12.9672, "longitude": 77.5932,
             "category": "Drainage", "priority_level": "High", "priority_score": 50.0},
            {"complaint_id": "V-002", "latitude": None,   "longitude": None,
             "category": "Drainage", "priority_level": "High", "priority_score": 50.0},
            {"complaint_id": "V-003", "latitude": 999.0,  "longitude": 77.5932,
             "category": "Drainage", "priority_level": "High", "priority_score": 50.0},
        ]
        # Only 1 valid row → below min_complaints threshold
        self.assertEqual(self.det.detect(mixed), [])

    # ── Minimum threshold ─────────────────────────────────────────────────────

    def test_below_min_threshold_no_hotspot(self):
        """2 nearby complaints must not form a hotspot (min = 3)."""
        two = self.LOTUS_CLUSTER[:2]
        result = self.det.detect(two)
        self.assertEqual(result, [], "2 complaints must not form a hotspot")

    def test_exactly_min_threshold_forms_hotspot(self):
        """Exactly 3 complaints within radius must form 1 hotspot."""
        three = self.LOTUS_CLUSTER[:3]
        result = self.det.detect(three)
        self.assertEqual(len(result), 1, "3 complaints within radius must form exactly 1 hotspot")

    # ── Cluster detection ─────────────────────────────────────────────────────

    def test_lotus_cluster_detected(self):
        """The 5-point Lotus Colony fixture must produce exactly 1 hotspot."""
        result = self.det.detect(self.LOTUS_CLUSTER)
        self.assertEqual(len(result), 1,
                         f"Expected 1 hotspot, got {len(result)}")

    def test_cluster_count_correct(self):
        """Detected hotspot must contain all 5 Lotus Colony complaints."""
        result = self.det.detect(self.LOTUS_CLUSTER)
        self.assertEqual(result[0].count, 5)

    def test_cluster_complaint_ids_complete(self):
        """Hotspot must reference exactly the 5 Lotus Colony IDs."""
        result = self.det.detect(self.LOTUS_CLUSTER)
        self.assertEqual(sorted(result[0].complaint_ids),
                         sorted(c["complaint_id"] for c in self.LOTUS_CLUSTER))

    def test_cluster_centre_near_mean(self):
        """Hotspot centre must be within ±0.001° of the arithmetic mean of member coords."""
        result = self.det.detect(self.LOTUS_CLUSTER)
        h = result[0]
        expected_lat = sum(c["latitude"]  for c in self.LOTUS_CLUSTER) / len(self.LOTUS_CLUSTER)
        expected_lon = sum(c["longitude"] for c in self.LOTUS_CLUSTER) / len(self.LOTUS_CLUSTER)
        self.assertAlmostEqual(h.center_lat, expected_lat, delta=0.001)
        self.assertAlmostEqual(h.center_lon, expected_lon, delta=0.001)

    def test_dominant_category_correct(self):
        """Dominant category must be 'Drainage' (appears 2× in LOTUS_CLUSTER)."""
        result = self.det.detect(self.LOTUS_CLUSTER)
        self.assertEqual(result[0].dominant_category, "Drainage")

    # ── Two separate clusters ─────────────────────────────────────────────────

    def test_two_separate_clusters(self):
        """Two geographically distant groups must produce two distinct hotspots."""
        combined = self.LOTUS_CLUSTER + self.NORTH_CLUSTER
        result = self.det.detect(combined)
        self.assertEqual(len(result), 2,
                         f"Expected 2 hotspots, got {len(result)}")

    def test_no_overlap_between_clusters(self):
        """No complaint ID may appear in more than one hotspot."""
        combined = self.LOTUS_CLUSTER + self.NORTH_CLUSTER
        result = self.det.detect(combined)
        all_ids = [cid for h in result for cid in h.complaint_ids]
        self.assertEqual(len(all_ids), len(set(all_ids)),
                         "Duplicate complaint IDs found across hotspots")

    # ── Haversine distance ────────────────────────────────────────────────────

    def test_haversine_same_point_is_zero(self):
        """Distance from a point to itself must be 0.0 km."""
        from ai.hotspot_detector import haversine_km
        self.assertAlmostEqual(haversine_km(12.9716, 77.5946, 12.9716, 77.5946),
                               0.0, places=6)

    def test_haversine_known_distance(self):
        """1 degree of longitude at the equator ≈ 111.19 km."""
        from ai.hotspot_detector import haversine_km
        d = haversine_km(0.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(d, 111.195, delta=0.1)

    def test_haversine_lotus_cluster_is_small(self):
        """All Lotus Colony pairs should be < 0.1 km apart."""
        from ai.hotspot_detector import haversine_km
        pts = self.LOTUS_CLUSTER
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                d = haversine_km(pts[i]["latitude"], pts[i]["longitude"],
                                 pts[j]["latitude"], pts[j]["longitude"])
                self.assertLess(d, 0.1,
                                f"Distance between {pts[i]['complaint_id']} and "
                                f"{pts[j]['complaint_id']} = {d:.4f} km (expected < 0.1)")

    # ── Custom radius ─────────────────────────────────────────────────────────

    def test_custom_tight_radius_no_hotspot(self):
        """With radius_km=0.001 (1 m), the Lotus cluster must not form a hotspot."""
        from ai.hotspot_detector import HotspotDetector
        tight = HotspotDetector(radius_km=0.001, min_complaints=3)
        result = tight.detect(self.LOTUS_CLUSTER)
        self.assertEqual(result, [],
                         "Radius of 1 m should prevent cluster formation")

    # ── Priority statistics ───────────────────────────────────────────────────

    def test_critical_count(self):
        """critical_count must equal the number of Critical-level members."""
        result = self.det.detect(self.LOTUS_CLUSTER)
        h = result[0]
        expected = sum(1 for c in self.LOTUS_CLUSTER
                       if c["priority_level"] == "Critical")
        self.assertEqual(h.critical_count, expected)

    def test_high_count(self):
        """high_count must equal the number of High-level members."""
        result = self.det.detect(self.LOTUS_CLUSTER)
        h = result[0]
        expected = sum(1 for c in self.LOTUS_CLUSTER
                       if c["priority_level"] == "High")
        self.assertEqual(h.high_count, expected)

    def test_avg_priority_score(self):
        """avg_priority_score must equal the arithmetic mean of member scores."""
        result = self.det.detect(self.LOTUS_CLUSTER)
        h = result[0]
        expected = sum(c["priority_score"] for c in self.LOTUS_CLUSTER) / len(self.LOTUS_CLUSTER)
        self.assertAlmostEqual(h.avg_priority_score, expected, delta=0.05)

    def test_priority_stats_missing_fields(self):
        """If priority_level / priority_score are absent, no exception is raised."""
        bare = [
            {"complaint_id": f"B-{i}", "latitude": 12.9672 + i * 0.0001,
             "longitude": 77.5932, "category": "Other"}
            for i in range(3)
        ]
        try:
            result = self.det.detect(bare)
        except Exception as exc:
            self.fail(f"detect() raised {exc} when priority fields are missing")
        # avg_priority_score should default to 0.0 when scores absent
        if result:
            self.assertEqual(result[0].avg_priority_score, 0.0)

    # ── Result is NamedTuple ──────────────────────────────────────────────────

    def test_result_is_hotspot_namedtuple(self):
        """Each item in the returned list must be a Hotspot NamedTuple."""
        from ai.hotspot_detector import Hotspot
        result = self.det.detect(self.LOTUS_CLUSTER)
        self.assertIsInstance(result[0], Hotspot)

    def test_hotspot_has_all_fields(self):
        """Hotspot must expose all required fields."""
        result = self.det.detect(self.LOTUS_CLUSTER)
        h = result[0]
        for field in ("center_lat", "center_lon", "complaint_ids", "count",
                      "dominant_category", "radius_km",
                      "critical_count", "high_count", "avg_priority_score"):
            self.assertTrue(hasattr(h, field), f"Missing field: {field}")

    # ── Sorted output ─────────────────────────────────────────────────────────

    def test_results_sorted_by_count_descending(self):
        """Hotspots must be returned in descending order of complaint count."""
        combined = self.LOTUS_CLUSTER + self.NORTH_CLUSTER
        result = self.det.detect(combined)
        counts = [h.count for h in result]
        self.assertEqual(counts, sorted(counts, reverse=True))


# ──────────────────────────────────────────────────────────────────────────────
# 7. HOTSPOT ROUTE TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestHotspotRoute(unittest.TestCase):
    """
    HTTP-level tests for GET /admin/hotspots (Phase 3D).
    Uses the Flask test client with a temp database.
    """

    @classmethod
    def setUpClass(cls):
        cls.client, cls.app = _make_client()

    def test_hotspots_route_returns_200(self):
        """GET /admin/hotspots must return HTTP 200."""
        resp = self.client.get("/admin/hotspots")
        self.assertEqual(resp.status_code, 200,
                         f"Expected 200, got {resp.status_code}")

    def test_hotspots_page_title_present(self):
        """Response must contain the page heading text."""
        resp = self.client.get("/admin/hotspots")
        self.assertIn(b"Hotspot Map", resp.data)

    def test_hotspots_page_has_leaflet_or_empty_state(self):
        """Response must contain either leaflet (map) or empty-state text."""
        resp = self.client.get("/admin/hotspots")
        has_map    = b"leaflet" in resp.data.lower()
        has_empty  = b"No hotspots detected" in resp.data
        self.assertTrue(has_map or has_empty,
                        "Page must contain either Leaflet map or empty-state message")

    def test_hotspots_nav_link_in_all_admin_pages(self):
        """Every admin page must render the Hotspots nav link."""
        for url in ("/admin/", "/admin/hotspots"):
            resp = self.client.get(url)
            self.assertIn(b"Hotspots", resp.data,
                          f"Hotspots nav link missing from {url}")

    def test_existing_dashboard_still_works(self):
        """The existing admin dashboard must still return 200 after Phase 3D changes."""
        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Admin Dashboard", resp.data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
