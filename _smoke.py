from ai.duplicate_detector import DuplicateDetector, _text_pair_similarity
det = DuplicateDetector(threshold=0.30)
# Test score_pair identical text, no category, no coords
s = det.score_pair("Road damage", "Big pothole", "Road damage", "Big pothole")
print("Identical score:", s)

# Diagnose: what are the individual signal values?
t = _text_pair_similarity("Road damage", "Road damage")
d = _text_pair_similarity("Big pothole", "Big pothole")
print(f"  title_sim={t} desc_sim={d}")
# With geo_sim=None, cat_sim=0.0 (empty category):
# blend = (0.50/0.90)*1 + (0.30/0.90)*1 + (0.10/0.90)*0 = 0.8889

# Now test M-002 multiple matches:
existing = [
    {"complaint_id": "M-001", "title": "Pothole on MG Road", "description": "Large pothole on MG Road near junction causing accidents."},
    {"complaint_id": "M-002", "title": "Deep pothole MG Road junction", "description": "Very deep pothole on MG Road at 1st Cross. Vehicles damaged."},
]
t1 = _text_pair_similarity("Pothole on MG Road near 1st Cross", "Pothole on MG Road")
d1 = _text_pair_similarity("Deep pothole at MG Road junction causing vehicles to skid.", "Large pothole on MG Road near junction causing accidents.")
t2 = _text_pair_similarity("Pothole on MG Road near 1st Cross", "Deep pothole MG Road junction")
d2 = _text_pair_similarity("Deep pothole at MG Road junction causing vehicles to skid.", "Very deep pothole on MG Road at 1st Cross. Vehicles damaged.")
print(f"\nM-001: title={t1:.3f} desc={d1:.3f}")
print(f"M-002: title={t2:.3f} desc={d2:.3f}")
# With 0.30 threshold and geo_sim=None, cat_sim=0:
w_t = 0.50/0.80; w_d = 0.30/0.80  # if cat also excluded
score1_nocatgeo = w_t*t1 + w_d*d1
score2_nocatgeo = w_t*t2 + w_d*d2
print(f"  Score1 (no cat/geo): {score1_nocatgeo:.4f}")
print(f"  Score2 (no cat/geo): {score2_nocatgeo:.4f}")
