"""
seed_data.py – CivicAI Synthetic Data Generator
Inserts 40+ fictional complaints, 6 departments, and demo officers.
Safe to run multiple times – uses INSERT OR IGNORE on complaint_id.
No real personal data is used.

Demo city: Novapolis (fictional), centred at 12.9716° N, 77.5946° E
"""

import sys
import os
import sqlite3
import logging
import random
from datetime import datetime, timedelta

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_connection, init_db, seed_departments

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Demo city centre (fictional Novapolis) ────────────────────────────────────
CITY_LAT = 12.9716
CITY_LON = 77.5946

random.seed(42)   # Reproducible results


def jitter(base: float, spread: float = 0.01) -> float:
    """Add small random offset to a coordinate."""
    return round(base + random.uniform(-spread, spread), 6)


def past_date(days_ago: int) -> str:
    """Return an ISO datetime string days_ago days in the past."""
    dt = datetime.now() - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ── Officers ──────────────────────────────────────────────────────────────────
# (department_name, officer_name)
OFFICERS = [
    ("Public Works",          "Rajan Mehta"),
    ("Public Works",          "Sunita Rao"),
    ("Water & Sanitation",    "Deepak Pillai"),
    ("Water & Sanitation",    "Anita Sharma"),
    ("Waste Management",      "Priya Nair"),
    ("Waste Management",      "Kiran Bose"),
    ("Electrical Department", "Vikram Joshi"),
    ("Electrical Department", "Meena Krishnan"),
    ("Traffic & Safety",      "Arjun Patil"),
    ("Traffic & Safety",      "Lakshmi Iyer"),
    ("Parks & Environment",   "Rohan Gupta"),
    ("Parks & Environment",   "Nalini Das"),
]

# ── Complaints ────────────────────────────────────────────────────────────────
# Fields: complaint_id, title, description, category,
#         lat, lon, address,
#         priority_score, priority_level, priority_reason,
#         status, dept_name, officer_name (or None),
#         created_days_ago, resolved_days_ago (or None)
#
# DELIBERATE DUPLICATE PAIRS (same incident, different reporters):
#   CMP-0003 / CMP-0023  – Road pothole, MG Road
#   CMP-0007 / CMP-0027  – Waterlogging, Nehru Street
#   CMP-0012 / CMP-0032  – Garbage overflow, City Market
#   CMP-0015 / CMP-0035  – Broken streetlight, Park Avenue
#   CMP-0019 / CMP-0039  – Drainage blockage, Lotus Colony
#
# GEOGRAPHIC CLUSTER (Lotus Colony area, coords within ~200 m):
#   CMP-0019, CMP-0020, CMP-0021, CMP-0022, CMP-0039
#
# URGENT SAFETY COMPLAINTS (priority_level = Critical):
#   CMP-0001, CMP-0008, CMP-0014, CMP-0025, CMP-0031

COMPLAINTS = [
    # ── CRITICAL / URGENT SAFETY ─────────────────────────────────────────────
    (
        "CMP-0001", "Large sinkhole on Highway 4",
        "A massive sinkhole approximately 3 metres wide has opened up on Highway 4 near the flyover. "
        "Vehicles are swerving dangerously. Immediate barricading required.",
        "Public Safety",
        12.9805, 77.5823, "Highway 4, Near Flyover, Novapolis",
        9.5, "Critical", "Large sinkhole blocking highway, immediate risk to life",
        "In Progress", "Traffic & Safety", "Arjun Patil",
        14, None,
    ),
    (
        "CMP-0002", "Collapsed boundary wall blocking road",
        "Boundary wall of an abandoned property has collapsed onto the road near School Lane, "
        "blocking one full lane and posing falling debris risk.",
        "Public Safety",
        12.9680, 77.5912, "School Lane, West Block, Novapolis",
        8.5, "High", "Collapsed wall blocking traffic lane, debris hazard",
        "Assigned", "Traffic & Safety", "Lakshmi Iyer",
        10, None,
    ),
    (
        "CMP-0003", "Deep pothole on MG Road causing accidents",
        "There is a very deep pothole near the MG Road junction with 1st Cross. Two bikes have "
        "already skidded. The road surface has completely eroded.",
        "Road Damage",
        12.9750, 77.5960, "MG Road, 1st Cross Junction, Novapolis",
        7.8, "High", "Deep pothole causing vehicle accidents",
        "Under Review", "Public Works", "Rajan Mehta",
        7, None,
    ),
    (
        "CMP-0004", "Road crack spanning entire width of 5th Main",
        "A longitudinal crack has developed spanning the full width of 5th Main Road near the hospital. "
        "Large vehicles cause it to widen further.",
        "Road Damage",
        12.9730, 77.5975, "5th Main Road, Near General Hospital, Novapolis",
        6.5, "High", "Full-width road crack near hospital, worsening",
        "Submitted", "Public Works", None,
        5, None,
    ),
    (
        "CMP-0005", "Waterlogging after rain – Brigade Road underpass",
        "The underpass at Brigade Road floods to knee level within 30 minutes of moderate rainfall. "
        "Vehicles stall and pedestrians are stranded.",
        "Waterlogging",
        12.9700, 77.5940, "Brigade Road Underpass, Novapolis",
        7.2, "High", "Underpass floods rapidly, vehicle stalling risk",
        "Assigned", "Water & Sanitation", "Deepak Pillai",
        20, None,
    ),
    (
        "CMP-0006", "Street garbage bin overflowing for 3 days",
        "The public garbage bin at Central Park Gate 2 has not been collected for 3 days. "
        "Waste is spilling onto the footpath and attracting stray animals.",
        "Garbage Overflow",
        12.9690, 77.5965, "Central Park, Gate 2, Novapolis",
        5.0, "Medium", "Uncollected garbage attracting animals, hygiene risk",
        "Submitted", "Waste Management", None,
        3, None,
    ),
    (
        "CMP-0007", "Severe waterlogging – Nehru Street residential area",
        "Nehru Street near House #45–60 has standing water more than 1 foot deep. "
        "Residents cannot leave their homes. Water entering ground-floor houses.",
        "Waterlogging",
        12.9665, 77.5900, "Nehru Street, Block B, Novapolis",
        8.8, "Critical", "Standing water inside homes, residents trapped",
        "In Progress", "Water & Sanitation", "Anita Sharma",
        6, None,
    ),
    (
        "CMP-0008", "Exposed live electrical wire on footpath",
        "A live electrical wire is dangling from a broken pole on Oak Avenue footpath. "
        "The wire touched a metal railing and caused sparks. Children walk this route daily.",
        "Public Safety",
        12.9710, 77.5985, "Oak Avenue, Near Bus Stand, Novapolis",
        9.9, "Critical", "Exposed live wire, sparks near pedestrian path",
        "Assigned", "Electrical Department", "Vikram Joshi",
        2, None,
    ),
    (
        "CMP-0009", "Broken streetlight – entire stretch of Lake Road dark",
        "Four consecutive streetlights on Lake Road between Marker 3 and Marker 7 are non-functional. "
        "The stretch is 400 metres long. Robberies reported in the area last week.",
        "Streetlight",
        12.9720, 77.5870, "Lake Road, Markers 3–7, Novapolis",
        7.5, "High", "400 m dark stretch, recent criminal activity",
        "Under Review", "Electrical Department", "Meena Krishnan",
        12, None,
    ),
    (
        "CMP-0010", "Drainage pipe burst on Elm Street",
        "A drainage pipe has burst on Elm Street near the post office. Foul-smelling water is "
        "flowing onto the street and into a nearby open drain.",
        "Drainage",
        12.9745, 77.5925, "Elm Street, Near Post Office, Novapolis",
        7.0, "High", "Burst drainage pipe, sewage on road",
        "Assigned", "Water & Sanitation", "Deepak Pillai",
        8, None,
    ),
    (
        "CMP-0011", "Garbage dumping near school – health risk",
        "Unknown persons are dumping construction and domestic waste in the open plot adjacent to "
        "Sunrise Primary School. Children are playing near the waste heap.",
        "Garbage Overflow",
        12.9686, 77.5958, "Sunrise School Lane, Novapolis",
        6.8, "High", "Waste dump near school, child safety risk",
        "Under Review", "Waste Management", "Priya Nair",
        15, None,
    ),
    (
        "CMP-0012", "Garbage overflow at City Market – bins not cleared",
        "All four garbage bins at City Market Main Entrance have been overflowing since Monday. "
        "The stench is affecting nearby shops and shoppers.",
        "Garbage Overflow",
        12.9730, 77.5912, "City Market, Main Entrance, Novapolis",
        6.0, "Medium", "Market bins overflowing, commercial area impacted",
        "In Progress", "Waste Management", "Kiran Bose",
        5, None,
    ),
    (
        "CMP-0013", "Pothole cluster – Industrial Area Road 3",
        "At least 8 potholes along a 100-metre stretch of Industrial Area Road 3. "
        "Heavy vehicles are damaged daily. Several tyre burst incidents this month.",
        "Road Damage",
        12.9800, 77.5880, "Industrial Area Road 3, Novapolis",
        6.5, "High", "Multiple potholes on heavy-vehicle route",
        "Submitted", "Public Works", None,
        18, None,
    ),
    (
        "CMP-0014", "Tree fallen on road blocking full carriageway",
        "A large rain tree has fallen across the full width of Greenwood Avenue following last night's "
        "storm. Both lanes completely blocked. Power cable may be snagged.",
        "Tree / Vegetation",
        12.9760, 77.5870, "Greenwood Avenue, Novapolis",
        9.2, "Critical", "Fallen tree blocking full road, possible power cable involved",
        "In Progress", "Parks & Environment", "Rohan Gupta",
        1, None,
    ),
    (
        "CMP-0015", "Broken streetlight – Park Avenue near children's park",
        "The streetlight directly in front of the children's play area on Park Avenue has been broken "
        "for two weeks. The area is pitch dark at night and feels unsafe.",
        "Streetlight",
        12.9698, 77.5947, "Park Avenue, Children's Park, Novapolis",
        6.2, "Medium", "Dark area near children's park, safety concern",
        "Under Review", "Electrical Department", "Meena Krishnan",
        14, None,
    ),
    (
        "CMP-0016", "Water supply disruption – Sector 7",
        "Sector 7 residential colony has had no piped water supply for 48 hours. "
        "Families are buying water at high cost. Old residents and infants affected.",
        "Water Supply",
        12.9655, 77.5950, "Sector 7 Colony, Novapolis",
        8.0, "High", "48-hour water cut, vulnerable residents affected",
        "Assigned", "Water & Sanitation", "Anita Sharma",
        3, None,
    ),
    (
        "CMP-0017", "Sewage overflow near residential colony gate",
        "Manhole near the main gate of Sunshine Colony is overflowing with sewage. "
        "The smell is unbearable and children are getting sick.",
        12.9680, 77.5930, "Sunshine Colony, Gate 1, Novapolis",
        7.5, "High", "Sewage overflow at colony entrance, health risk",
        "Submitted", "Water & Sanitation", None,
        4, None,
    ),
    # ── Fix the tuple above which accidentally consumed category ──────────────
]

# That entry (CMP-0017) had a missing category field. Let me redefine the full list properly:
# (All 40 entries in one clean list below.)

COMPLAINTS = [
    # ── CRITICAL / URGENT SAFETY (5 entries) ─────────────────────────────────
    (
        "CMP-0001", "Large sinkhole on Highway 4",
        "A massive sinkhole approximately 3 metres wide has opened up on Highway 4 near the flyover. "
        "Vehicles are swerving dangerously. Immediate barricading required.",
        "Public Safety",
        12.9805, 77.5823, "Highway 4, Near Flyover, Novapolis",
        9.5, "Critical", "Large sinkhole blocking highway, immediate risk to life",
        "In Progress", "Traffic & Safety", "Arjun Patil", 14, None,
    ),
    (
        "CMP-0008", "Exposed live electrical wire on footpath",
        "A live electrical wire is dangling from a broken pole on Oak Avenue footpath. "
        "The wire touched a metal railing and caused sparks. Children walk this route daily.",
        "Public Safety",
        12.9710, 77.5985, "Oak Avenue, Near Bus Stand, Novapolis",
        9.9, "Critical", "Exposed live wire, sparks near pedestrian path",
        "Assigned", "Electrical Department", "Vikram Joshi", 2, None,
    ),
    (
        "CMP-0014", "Tree fallen on road blocking full carriageway",
        "A large rain tree has fallen across the full width of Greenwood Avenue following last night's "
        "storm. Both lanes completely blocked. Power cable may be snagged.",
        "Tree / Vegetation",
        12.9760, 77.5870, "Greenwood Avenue, Novapolis",
        9.2, "Critical", "Fallen tree blocking full road, possible power cable involved",
        "In Progress", "Parks & Environment", "Rohan Gupta", 1, None,
    ),
    (
        "CMP-0025", "Gas smell reported near Civic Centre",
        "Residents near Civic Centre Block A are reporting a strong gas smell since morning. "
        "Possible underground gas line leak. Evacuation may be needed.",
        "Public Safety",
        12.9720, 77.5940, "Civic Centre, Block A, Novapolis",
        9.8, "Critical", "Potential gas leak, evacuation risk",
        "In Progress", "Traffic & Safety", "Arjun Patil", 1, None,
    ),
    (
        "CMP-0031", "Manhole cover missing on busy intersection",
        "The manhole cover at the intersection of MG Road and 3rd Cross is completely missing. "
        "A motorcyclist fell in last evening. No barriers or warning signs present.",
        "Public Safety",
        12.9752, 77.5962, "MG Road, 3rd Cross Intersection, Novapolis",
        9.7, "Critical", "Open manhole on busy road, injury already occurred",
        "Assigned", "Public Works", "Rajan Mehta", 2, None,
    ),
    # ── ROAD DAMAGE ──────────────────────────────────────────────────────────
    (
        "CMP-0003", "Deep pothole on MG Road causing accidents",
        "There is a very deep pothole near the MG Road junction with 1st Cross. Two bikes have "
        "already skidded. The road surface has completely eroded.",
        "Road Damage",
        12.9750, 77.5960, "MG Road, 1st Cross Junction, Novapolis",
        7.8, "High", "Deep pothole causing vehicle accidents",
        "Under Review", "Public Works", "Rajan Mehta", 7, None,
    ),
    (
        "CMP-0004", "Road crack spanning entire width of 5th Main",
        "A longitudinal crack has developed spanning the full width of 5th Main Road near the hospital. "
        "Large vehicles cause it to widen further.",
        "Road Damage",
        12.9730, 77.5975, "5th Main Road, Near General Hospital, Novapolis",
        6.5, "High", "Full-width road crack near hospital, worsening",
        "Submitted", "Public Works", None, 5, None,
    ),
    (
        "CMP-0013", "Pothole cluster – Industrial Area Road 3",
        "At least 8 potholes along a 100-metre stretch of Industrial Area Road 3. "
        "Heavy vehicles are damaged daily. Several tyre burst incidents this month.",
        "Road Damage",
        12.9800, 77.5880, "Industrial Area Road 3, Novapolis",
        6.5, "High", "Multiple potholes on heavy-vehicle route",
        "Submitted", "Public Works", None, 18, None,
    ),
    (
        "CMP-0023", "Pothole at MG Road junction (duplicate report)",
        "Reporting a dangerous pothole at MG Road near 1st Cross. It caused my bike to skid this morning. "
        "The municipality must act urgently.",
        "Road Damage",
        12.9751, 77.5961, "MG Road, 1st Cross, Novapolis",
        7.5, "High", "Duplicate – same pothole as CMP-0003",
        "Under Review", "Public Works", "Rajan Mehta", 6, None,
    ),
    (
        "CMP-0033", "Speed breaker damaged – vehicle undercarriage scraping",
        "The speed breaker on College Road near Gate 3 has sunk and cracked. "
        "Vehicles are scraping against it and it is creating noise pollution at night.",
        "Road Damage",
        12.9715, 77.5955, "College Road, Gate 3, Novapolis",
        4.0, "Medium", "Damaged speed breaker causing vehicle damage",
        "Submitted", "Public Works", None, 9, None,
    ),
    # ── WATERLOGGING ─────────────────────────────────────────────────────────
    (
        "CMP-0005", "Waterlogging after rain – Brigade Road underpass",
        "The underpass at Brigade Road floods to knee level within 30 minutes of moderate rainfall. "
        "Vehicles stall and pedestrians are stranded.",
        "Waterlogging",
        12.9700, 77.5940, "Brigade Road Underpass, Novapolis",
        7.2, "High", "Underpass floods rapidly, vehicle stalling risk",
        "Assigned", "Water & Sanitation", "Deepak Pillai", 20, None,
    ),
    (
        "CMP-0007", "Severe waterlogging – Nehru Street residential area",
        "Nehru Street near House #45–60 has standing water more than 1 foot deep. "
        "Residents cannot leave their homes. Water entering ground-floor houses.",
        "Waterlogging",
        12.9665, 77.5900, "Nehru Street, Block B, Novapolis",
        8.8, "Critical", "Standing water inside homes, residents trapped",
        "In Progress", "Water & Sanitation", "Anita Sharma", 6, None,
    ),
    (
        "CMP-0027", "Standing water on Nehru Street – waterlogging again",
        "The waterlogging problem on Nehru Street (Block B) is still not resolved. "
        "Water has entered our compound wall again. We need a permanent fix.",
        "Waterlogging",
        12.9666, 77.5901, "Nehru Street, Block B, House 50, Novapolis",
        8.5, "Critical", "Duplicate – same waterlogging as CMP-0007, recurring",
        "Under Review", "Water & Sanitation", "Anita Sharma", 5, None,
    ),
    (
        "CMP-0036", "Low-lying road floods during every rain",
        "The road in front of Sunrise Apartments on Ring Road dips at one point and floods during "
        "every shower. The municipality dug a trench two months ago but never refilled it.",
        "Waterlogging",
        12.9688, 77.5935, "Ring Road, Sunrise Apartments, Novapolis",
        5.5, "Medium", "Recurring flood due to unfilled trench",
        "Submitted", "Water & Sanitation", None, 60, None,
    ),
    # ── GARBAGE OVERFLOW ─────────────────────────────────────────────────────
    (
        "CMP-0006", "Street garbage bin overflowing for 3 days",
        "The public garbage bin at Central Park Gate 2 has not been collected for 3 days. "
        "Waste is spilling onto the footpath and attracting stray animals.",
        "Garbage Overflow",
        12.9690, 77.5965, "Central Park, Gate 2, Novapolis",
        5.0, "Medium", "Uncollected garbage attracting animals, hygiene risk",
        "Submitted", "Waste Management", None, 3, None,
    ),
    (
        "CMP-0011", "Garbage dumping near school – health risk",
        "Unknown persons are dumping construction and domestic waste in the open plot adjacent to "
        "Sunrise Primary School. Children are playing near the waste heap.",
        "Garbage Overflow",
        12.9686, 77.5958, "Sunrise School Lane, Novapolis",
        6.8, "High", "Waste dump near school, child safety risk",
        "Under Review", "Waste Management", "Priya Nair", 15, None,
    ),
    (
        "CMP-0012", "Garbage overflow at City Market – bins not cleared",
        "All four garbage bins at City Market Main Entrance have been overflowing since Monday. "
        "The stench is affecting nearby shops and shoppers.",
        "Garbage Overflow",
        12.9730, 77.5912, "City Market, Main Entrance, Novapolis",
        6.0, "Medium", "Market bins overflowing, commercial area impacted",
        "In Progress", "Waste Management", "Kiran Bose", 5, None,
    ),
    (
        "CMP-0032", "Garbage not collected at City Market for 4 days",
        "City Market garbage bins are still overflowing. No collection has happened for 4 days. "
        "The situation is worsening and shopkeepers are complaining.",
        "Garbage Overflow",
        12.9731, 77.5913, "City Market, Main Entrance Area, Novapolis",
        5.8, "Medium", "Duplicate – same market garbage issue as CMP-0012",
        "In Progress", "Waste Management", "Kiran Bose", 4, None,
    ),
    (
        "CMP-0037", "Illegal dumping on riverside footpath",
        "People are dumping household garbage on the riverside footpath near River View Bridge. "
        "The river water may get contaminated. Bags are torn open by dogs.",
        "Garbage Overflow",
        12.9810, 77.5850, "River View Bridge, Riverside Footpath, Novapolis",
        5.5, "Medium", "Illegal dumping near water body, contamination risk",
        "Submitted", "Waste Management", None, 22, None,
    ),
    # ── STREETLIGHT ──────────────────────────────────────────────────────────
    (
        "CMP-0009", "Broken streetlight – Lake Road 400 m stretch dark",
        "Four consecutive streetlights on Lake Road between Marker 3 and Marker 7 are non-functional. "
        "The stretch is 400 metres long. Robberies reported in the area last week.",
        "Streetlight",
        12.9720, 77.5870, "Lake Road, Markers 3–7, Novapolis",
        7.5, "High", "400 m dark stretch, recent criminal activity",
        "Under Review", "Electrical Department", "Meena Krishnan", 12, None,
    ),
    (
        "CMP-0015", "Broken streetlight – Park Avenue near children's park",
        "The streetlight directly in front of the children's play area on Park Avenue has been broken "
        "for two weeks. The area is pitch dark at night and feels unsafe.",
        "Streetlight",
        12.9698, 77.5947, "Park Avenue, Children's Park, Novapolis",
        6.2, "Medium", "Dark area near children's park, safety concern",
        "Under Review", "Electrical Department", "Meena Krishnan", 14, None,
    ),
    (
        "CMP-0035", "Streetlight out at Park Avenue children's area",
        "The light near the children's play area on Park Avenue is still broken. "
        "We submitted a complaint before but nothing was done. Reporting again.",
        "Streetlight",
        12.9699, 77.5948, "Park Avenue, Children's Park Area, Novapolis",
        6.0, "Medium", "Duplicate – same streetlight as CMP-0015",
        "Submitted", "Electrical Department", None, 7, None,
    ),
    (
        "CMP-0040", "Multiple streetlights out – Old Town Circuit",
        "Seven streetlights across Old Town Circuit (1st Street to 4th Street) are out. "
        "Old Town has seen three chain snatching incidents in the dark this month.",
        "Streetlight",
        12.9660, 77.5870, "Old Town Circuit, Novapolis",
        8.0, "High", "Multiple lights out in area with active crime",
        "Submitted", "Electrical Department", None, 30, None,
    ),
    # ── DRAINAGE ─────────────────────────────────────────────────────────────
    (
        "CMP-0010", "Drainage pipe burst on Elm Street",
        "A drainage pipe has burst on Elm Street near the post office. Foul-smelling water is "
        "flowing onto the street and into a nearby open drain.",
        "Drainage",
        12.9745, 77.5925, "Elm Street, Near Post Office, Novapolis",
        7.0, "High", "Burst drainage pipe, sewage on road",
        "Assigned", "Water & Sanitation", "Deepak Pillai", 8, None,
    ),
    (
        "CMP-0019", "Drainage blockage causing flooding – Lotus Colony",
        "The main drainage channel behind Lotus Colony Block C is completely blocked with silt and waste. "
        "Every rain floods 6 houses in the area.",
        "Drainage",
        12.9672, 77.5932, "Lotus Colony, Block C, Novapolis",
        8.2, "High", "Blocked drain causes recurrent house flooding",
        "In Progress", "Water & Sanitation", "Deepak Pillai", 30, None,
    ),
    (
        "CMP-0039", "Clogged drain behind Lotus Colony – same issue",
        "Reporting once more – the drain at Lotus Colony Block C is still blocked. "
        "Water flooded three houses again last night. The municipality must take permanent action.",
        "Drainage",
        12.9673, 77.5933, "Lotus Colony, Block C Rear, Novapolis",
        8.0, "High", "Duplicate – same drain as CMP-0019, flooding confirmed",
        "Submitted", "Water & Sanitation", None, 5, None,
    ),
    (
        "CMP-0028", "Open drain without cover near bus stop",
        "The open drainage channel near the Central Bus Terminal stop has no cover or railing. "
        "A child fell into it last month. No action taken.",
        "Drainage",
        12.9705, 77.5960, "Central Bus Terminal, Novapolis",
        7.0, "High", "Uncovered drain, child injury already occurred",
        "Submitted", "Water & Sanitation", None, 35, None,
    ),
    # ── WATER SUPPLY ─────────────────────────────────────────────────────────
    (
        "CMP-0016", "Water supply disruption – Sector 7",
        "Sector 7 residential colony has had no piped water supply for 48 hours. "
        "Families are buying water at high cost. Old residents and infants affected.",
        "Water Supply",
        12.9655, 77.5950, "Sector 7 Colony, Novapolis",
        8.0, "High", "48-hour water cut, vulnerable residents affected",
        "Assigned", "Water & Sanitation", "Anita Sharma", 3, None,
    ),
    (
        "CMP-0029", "Water discolouration – brown water from taps",
        "Residents of Harmony Housing Society are receiving muddy brown water from taps since yesterday. "
        "Many people are falling sick. Possible pipe contamination.",
        "Water Supply",
        12.9660, 77.5975, "Harmony Housing Society, Novapolis",
        7.5, "High", "Contaminated water supply, residents falling ill",
        "Under Review", "Water & Sanitation", "Deepak Pillai", 2, None,
    ),
    (
        "CMP-0034", "Water meter broken – billing dispute",
        "The water meter at House #14, Jasmine Lane is broken and spinning constantly showing "
        "high readings. Residents are being billed for water they are not using.",
        "Water Supply",
        12.9675, 77.5942, "Jasmine Lane, House 14, Novapolis",
        3.0, "Low", "Faulty meter causing billing issue",
        "Submitted", "Water & Sanitation", None, 20, None,
    ),
    # ── SEWAGE ───────────────────────────────────────────────────────────────
    (
        "CMP-0017", "Sewage overflow near Sunshine Colony gate",
        "Manhole near the main gate of Sunshine Colony is overflowing with sewage. "
        "The smell is unbearable and children are getting sick.",
        "Sewage",
        12.9680, 77.5930, "Sunshine Colony, Gate 1, Novapolis",
        7.5, "High", "Sewage overflow at colony entrance, health risk",
        "Submitted", "Water & Sanitation", None, 4, None,
    ),
    (
        "CMP-0030", "Sewage pipe leaking into footpath – Health Zone",
        "A sewage pipe is leaking directly onto the footpath near the Health Zone Clinic. "
        "Patients and staff have to walk through sewage to reach the entrance.",
        "Sewage",
        12.9715, 77.5945, "Health Zone Clinic, Main Road, Novapolis",
        8.5, "High", "Sewage on clinic footpath, serious health risk",
        "In Progress", "Water & Sanitation", "Anita Sharma", 7, None,
    ),
    # ── TREE / VEGETATION ────────────────────────────────────────────────────
    (
        "CMP-0002", "Collapsed boundary wall blocking road",
        "Boundary wall of an abandoned property has collapsed onto the road near School Lane, "
        "blocking one full lane and posing falling debris risk.",
        "Public Safety",
        12.9680, 77.5912, "School Lane, West Block, Novapolis",
        8.5, "High", "Collapsed wall blocking traffic lane, debris hazard",
        "Assigned", "Traffic & Safety", "Lakshmi Iyer", 10, None,
    ),
    (
        "CMP-0018", "Overgrown tree branches blocking traffic signal",
        "Tree branches near the traffic signal at Newton Circle have grown so large they are "
        "obscuring the signal lights. Drivers cannot see the lights from far.",
        "Tree / Vegetation",
        12.9695, 77.5908, "Newton Circle, Novapolis",
        6.0, "Medium", "Tree obscuring traffic signal, road safety risk",
        "Under Review", "Parks & Environment", "Rohan Gupta", 25, None,
    ),
    (
        "CMP-0038", "Dry tree about to fall near market",
        "A large dry tree in front of City Supermarket is leaning dangerously. "
        "Heavy winds last week split one branch which fell onto the pavement.",
        "Tree / Vegetation",
        12.9740, 77.5915, "City Supermarket, Market Road, Novapolis",
        7.8, "High", "Leaning dead tree, branch already fell",
        "Submitted", "Parks & Environment", None, 11, None,
    ),
    # ── NOISE POLLUTION ──────────────────────────────────────────────────────
    (
        "CMP-0024", "Construction noise at night violating norms",
        "A construction site on 7th Cross Road is operating noisy equipment past midnight, "
        "violating noise pollution norms. Residents have complained to the builder with no response.",
        "Noise Pollution",
        12.9725, 77.5935, "7th Cross Road, Near Temple, Novapolis",
        4.5, "Medium", "Nighttime construction violating noise norms",
        "Submitted", "Traffic & Safety", None, 6, None,
    ),
    (
        "CMP-0026", "Loudspeaker from shop disturbing hospital patients",
        "A textile shop on Hospital Road is playing loud music using external speakers from 8 AM to "
        "10 PM. Hospital patients and staff are being disturbed.",
        "Noise Pollution",
        12.9712, 77.5970, "Hospital Road, Near City Hospital, Novapolis",
        5.0, "Medium", "Loud music near hospital, patient disturbance",
        "Submitted", "Traffic & Safety", None, 8, None,
    ),
    # ── OTHER / MISCELLANEOUS ─────────────────────────────────────────────────
    (
        "CMP-0020", "Broken footpath tiles – Lotus Colony main road",
        "Several footpath tiles near Lotus Colony main road entrance have cracked and lifted. "
        "Elderly residents have tripped. One fracture case reported.",
        "Road Damage",
        12.9670, 77.5930, "Lotus Colony, Main Road Entrance, Novapolis",
        6.5, "Medium", "Cracked footpath, elderly injury reported",
        "Submitted", "Public Works", None, 40, None,
    ),
    (
        "CMP-0021", "Stray dog menace near Lotus Colony park",
        "A pack of 12–15 aggressive stray dogs has taken over the park near Lotus Colony. "
        "Two children bitten this week. The situation is dangerous.",
        "Public Safety",
        12.9671, 77.5931, "Lotus Colony, Community Park, Novapolis",
        8.5, "High", "Aggressive stray dog pack, children bitten",
        "In Progress", "Traffic & Safety", "Lakshmi Iyer", 8, None,
    ),
    (
        "CMP-0022", "Flooded park path – Lotus Colony",
        "The walking path inside the Lotus Colony park is submerged under 2 inches of stagnant water. "
        "Mosquito breeding is observed. No drainage in the park.",
        "Waterlogging",
        12.9672, 77.5932, "Lotus Colony, Community Park, Novapolis",
        5.5, "Medium", "Stagnant water in park, mosquito breeding",
        "Submitted", "Parks & Environment", None, 15, None,
    ),
    (
        "CMP-0041", "Unrepaired road after utility work – Sector 5",
        "The Public Works Department dug up Section 5 Ring Road for cable laying 3 months ago. "
        "The trench was loosely refilled and now has a 15 cm dip causing vehicle damage.",
        "Road Damage",
        12.9640, 77.5960, "Section 5 Ring Road, Novapolis",
        5.0, "Medium", "Poorly refilled utility trench causing vehicle damage",
        "Submitted", "Public Works", None, 90, None,
    ),
    (
        "CMP-0042", "Faded road markings at pedestrian crossing",
        "All road markings at the pedestrian crossing near City College have completely faded. "
        "Drivers do not stop for pedestrians. Near-miss accidents daily.",
        "Road Damage",
        12.9706, 77.5968, "City College, Main Road Crossing, Novapolis",
        5.5, "Medium", "Invisible pedestrian crossing, near-miss accidents",
        "Resolved", "Public Works", "Sunita Rao", 45, 10,
    ),
    (
        "CMP-0043", "Broken park bench – Central Park",
        "Two benches near the fountain in Central Park have broken legs. "
        "Elderly visitors have nowhere safe to sit.",
        "Other",
        12.9692, 77.5962, "Central Park, Fountain Area, Novapolis",
        2.5, "Low", "Broken benches, low impact but affects elderly users",
        "Resolved", "Parks & Environment", "Nalini Das", 55, 20,
    ),
    (
        "CMP-0044", "Missing road sign – right turn at Junction 9",
        "The road sign indicating right-turn-only at Junction 9 on Outer Ring Road has been missing "
        "for over a month. Wrong-way drivers are causing near-misses.",
        "Traffic & Safety",   # Note: using category matching department logic for phase 2
        12.9830, 77.5920, "Outer Ring Road, Junction 9, Novapolis",
        6.0, "Medium", "Missing road sign causing wrong-way driving",
        "Under Review", "Traffic & Safety", "Arjun Patil", 32, None,
    ),
]


# ── Duplicate link definitions ────────────────────────────────────────────────
DUPLICATE_PAIRS = [
    ("CMP-0003", "CMP-0023", 0.91),
    ("CMP-0007", "CMP-0027", 0.89),
    ("CMP-0012", "CMP-0032", 0.87),
    ("CMP-0015", "CMP-0035", 0.85),
    ("CMP-0019", "CMP-0039", 0.92),
]


# ── Geographic cluster: Lotus Colony ─────────────────────────────────────────
# CMP-0019, CMP-0020, CMP-0021, CMP-0022, CMP-0039 are all within ~200 m of
# Lotus Colony (12.9672, 77.5932). This cluster is used by the hotspot detector.


# ── Seeder functions ─────────────────────────────────────────────────────────

def get_dept_map(conn: sqlite3.Connection) -> dict:
    """Return {department_name: id} mapping."""
    cur = conn.cursor()
    cur.execute("SELECT id, department_name FROM departments;")
    return {row["department_name"]: row["id"] for row in cur.fetchall()}


def get_or_create_officer(conn: sqlite3.Connection, name: str, dept_id: int) -> int:
    """Return officer id, creating the officer if they don't exist."""
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM officers WHERE officer_name = ? AND department_id = ?;",
        (name, dept_id),
    )
    row = cur.fetchone()
    if row:
        return row["id"]
    cur.execute(
        "INSERT INTO officers (officer_name, department_id) VALUES (?, ?);",
        (name, dept_id),
    )
    conn.commit()
    return cur.lastrowid


def seed_officers(conn: sqlite3.Connection, dept_map: dict) -> dict:
    """Insert demo officers; return {officer_name: id}."""
    officer_map = {}
    for dept_name, officer_name in OFFICERS:
        if dept_name not in dept_map:
            logger.warning("Department not found: %s", dept_name)
            continue
        oid = get_or_create_officer(conn, officer_name, dept_map[dept_name])
        officer_map[officer_name] = oid
    logger.info("Seeded %d officers.", len(officer_map))
    return officer_map


def seed_complaints(conn: sqlite3.Connection, dept_map: dict, officer_map: dict) -> None:
    """Insert all synthetic complaints (idempotent via INSERT OR IGNORE)."""
    cur = conn.cursor()

    sql = """
        INSERT OR IGNORE INTO complaints (
            complaint_id, title, description, category,
            latitude, longitude, address,
            priority_score, priority_level, priority_reason,
            status, department_id, assigned_officer,
            created_at, updated_at, resolved_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """

    count = 0
    for row in COMPLAINTS:
        (
            cid, title, desc, category,
            lat, lon, address,
            pscore, plevel, preason,
            status, dept_name, officer_name,
            days_ago, resolved_days_ago,
        ) = row

        dept_id   = dept_map.get(dept_name)
        officer_id = officer_map.get(officer_name) if officer_name else None
        created   = past_date(days_ago)
        updated   = past_date(days_ago - 1) if days_ago > 1 else created
        resolved  = past_date(resolved_days_ago) if resolved_days_ago else None

        cur.execute(sql, (
            cid, title, desc, category,
            lat, lon, address,
            pscore, plevel, preason,
            status, dept_id, officer_id,
            created, updated, resolved,
        ))
        if cur.rowcount:
            count += 1

    conn.commit()
    logger.info("Inserted %d new complaints (skipped existing).", count)


def seed_duplicate_links(conn: sqlite3.Connection) -> None:
    """Insert known duplicate pairs."""
    cur = conn.cursor()
    sql = """
        INSERT OR IGNORE INTO duplicate_links
            (complaint_id, matched_complaint_id, similarity_score)
        VALUES (?, ?, ?);
    """
    # Use complaint_id+matched_complaint_id combo uniqueness via WHERE NOT EXISTS
    for cid, matched, score in DUPLICATE_PAIRS:
        cur.execute(
            """INSERT INTO duplicate_links (complaint_id, matched_complaint_id, similarity_score)
               SELECT ?, ?, ?
               WHERE NOT EXISTS (
                   SELECT 1 FROM duplicate_links
                   WHERE complaint_id = ? AND matched_complaint_id = ?
               );""",
            (cid, matched, score, cid, matched),
        )
    conn.commit()
    logger.info("Seeded duplicate links.")


def seed_status_history(conn: sqlite3.Connection) -> None:
    """Insert initial status history entries for all complaints."""
    cur = conn.cursor()
    cur.execute(
        "SELECT complaint_id, status, created_at FROM complaints;"
    )
    rows = cur.fetchall()

    insert_sql = """
        INSERT INTO status_history (complaint_id, old_status, new_status, action_note, changed_at)
        SELECT ?, NULL, ?, 'Initial complaint submission', ?
        WHERE NOT EXISTS (
            SELECT 1 FROM status_history WHERE complaint_id = ? AND old_status IS NULL
        );
    """
    for row in rows:
        cur.execute(insert_sql, (
            row["complaint_id"], row["status"], row["created_at"], row["complaint_id"]
        ))
    conn.commit()
    logger.info("Seeded status history entries.")


def seed_action_notes(conn: sqlite3.Connection) -> None:
    """Insert sample action notes for in-progress / assigned complaints."""
    notes = [
        ("CMP-0001", "Barricades deployed, JCB dispatched for sinkhole filling."),
        ("CMP-0007", "Pump installed to remove standing water. Root cause investigation pending."),
        ("CMP-0008", "Emergency team dispatched. Area cordoned off."),
        ("CMP-0010", "Pipe section replaced. Road patching scheduled tomorrow."),
        ("CMP-0014", "Tree removal crew on site. Power company notified about cable."),
        ("CMP-0005", "Desilting of underpass drain scheduled for next week."),
        ("CMP-0012", "Additional garbage truck deployed to City Market area."),
        ("CMP-0030", "Sewage pipe section identified. Replacement parts ordered."),
    ]
    sql = """
        INSERT INTO action_notes (complaint_id, note)
        SELECT ?, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM action_notes WHERE complaint_id = ? AND note = ?
        );
    """
    cur = conn.cursor()
    for cid, note in notes:
        cur.execute(sql, (cid, note, cid, note))
    conn.commit()
    logger.info("Seeded action notes.")


# ── Main ──────────────────────────────────────────────────────────────────────

def run_seed() -> None:
    """Run the complete seed sequence."""
    logger.info("=== CivicAI Seed Script ===")
    logger.info("Initialising database …")
    init_db()
    seed_departments()

    conn = get_connection()
    try:
        dept_map    = get_dept_map(conn)
        officer_map = seed_officers(conn, dept_map)
        seed_complaints(conn, dept_map, officer_map)
        seed_duplicate_links(conn)
        seed_status_history(conn)
        seed_action_notes(conn)
    finally:
        conn.close()

    logger.info("=== Seed complete. ===")


if __name__ == "__main__":
    run_seed()
