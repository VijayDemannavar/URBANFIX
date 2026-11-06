# CivicAI – From Complaints to Action

> **Hackathon Project** for PromptWars × ASTRA  
> An AI-powered civic complaint management platform.

---

## Problem Statement

Cities generate thousands of citizen complaints every day: potholes, waterlogging, broken streetlights, garbage overflow, drainage failures, and public safety hazards. These complaints are often:

- Entered manually into siloed systems with no intelligent triage.
- Duplicated across departments by multiple citizens reporting the same issue.
- Unpriorised — a collapsed wall and a broken bench receive equal attention.
- Never aggregated geographically, so hotspot patterns remain invisible.
- Responded to with no clear action briefs, leaving officers guessing.

**CivicAI** solves this by automating categorisation, deduplication, priority scoring, hotspot detection, and action brief generation using LLMs and NLP — all in a single, integrated platform.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Browser / Mobile Client                 │
│              HTML + CSS + JS  (Jinja2 templates)         │
└─────────────────────┬───────────────────────────────────┘
                      │  HTTP (JSON / form data)
┌─────────────────────▼───────────────────────────────────┐
│               Flask Backend  (app.py)                    │
│  Routes → config.py  →  database.py  →  ai/             │
└──────┬──────────────────────────────────────┬───────────┘
       │ SQL (parameterised)                  │ Python calls
┌──────▼──────────────┐          ┌────────────▼───────────┐
│   SQLite Database   │          │      AI Layer (ai/)     │
│   civicai.db        │          │  ai_engine.py           │
│                     │          │  duplicate_detector.py  │
│  6 tables (see DB   │          │  priority_engine.py     │
│  Schema section)    │          │  hotspot_detector.py    │
│                     │          │  action_brief.py        │
└─────────────────────┘          └─────────────────────────┘
       │
┌──────▼──────────────┐
│   uploads/          │
│   (image files)     │
└─────────────────────┘
```

### Request Lifecycle (Phase 2+)
1. Citizen submits complaint form (title, description, category, image, GPS coordinates).
2. Flask route validates input, saves image to `uploads/`, generates a unique `complaint_id`.
3. Route calls `database.py` to insert the raw complaint row.
4. Route calls `ai_engine.py` → chains: categorise → summarise → deduplicate → score priority → detect hotspot.
5. AI results (`ai_category`, `priority_score`, `duplicate_ids`, etc.) are written back to the complaint row.
6. Department dashboard queries and renders complaint lists via Jinja2 templates.

---

## Project Structure

```
civicai/
│
├── app.py                  Flask application entry point
├── config.py               All configuration settings
├── database.py             Database layer (connection, tables, helpers)
├── seed_data.py            Synthetic data generator (40+ complaints)
├── requirements.txt        Python dependencies
├── README.md               This file
│
├── database/               SQLite database files (civicai.db)
├── uploads/                User-uploaded complaint images
│
├── ai/                     AI pipeline modules
│   ├── __init__.py
│   ├── ai_engine.py        Orchestrator – chains all AI sub-modules
│   ├── duplicate_detector.py  Semantic similarity duplicate detection
│   ├── priority_engine.py  Rule-based + LLM priority scoring
│   ├── hotspot_detector.py Geographic cluster detection
│   └── action_brief.py     LLM-generated officer action briefs
│
├── templates/              Jinja2 HTML templates (Phase 2)
├── static/
│   ├── css/                Stylesheets (Phase 2)
│   ├── js/                 JavaScript (Phase 2)
│   └── images/             Static image assets
│
└── tests/
    ├── __init__.py
    └── test_database.py    Phase 1 database tests
```

---

## Database Schema

### `departments`
| Column           | Type    | Constraints              |
|------------------|---------|--------------------------|
| id               | INTEGER | PK, AUTOINCREMENT        |
| department_name  | TEXT    | NOT NULL, UNIQUE         |
| description      | TEXT    |                          |

### `officers`
| Column       | Type    | Constraints                        |
|--------------|---------|------------------------------------|
| id           | INTEGER | PK, AUTOINCREMENT                  |
| officer_name | TEXT    | NOT NULL                           |
| department_id| INTEGER | NOT NULL, FK → departments(id)     |
| created_at   | TEXT    | DEFAULT datetime('now')            |

### `complaints`
| Column           | Type    | Constraints                        |
|------------------|---------|------------------------------------|
| id               | INTEGER | PK, AUTOINCREMENT                  |
| complaint_id     | TEXT    | NOT NULL, UNIQUE (e.g. CMP-0001)   |
| title            | TEXT    | NOT NULL                           |
| description      | TEXT    | NOT NULL                           |
| category         | TEXT    | NOT NULL (citizen-selected)        |
| ai_category      | TEXT    | AI-predicted category (Phase 3)    |
| ai_summary       | TEXT    | AI one-line summary (Phase 3)      |
| image_path       | TEXT    | Relative path inside uploads/      |
| latitude         | REAL    |                                    |
| longitude        | REAL    |                                    |
| address          | TEXT    |                                    |
| priority_score   | REAL    | DEFAULT 0.0                        |
| priority_level   | TEXT    | DEFAULT 'Low'                      |
| priority_reason  | TEXT    |                                    |
| status           | TEXT    | DEFAULT 'Submitted'                |
| department_id    | INTEGER | FK → departments(id)               |
| assigned_officer | INTEGER | FK → officers(id)                  |
| created_at       | TEXT    | DEFAULT datetime('now')            |
| updated_at       | TEXT    | DEFAULT datetime('now')            |
| resolved_at      | TEXT    | NULL until resolved                |

### `status_history`
| Column       | Type    | Constraints                              |
|--------------|---------|------------------------------------------|
| id           | INTEGER | PK, AUTOINCREMENT                        |
| complaint_id | TEXT    | NOT NULL, FK → complaints(complaint_id)  |
| old_status   | TEXT    | NULL for initial status                  |
| new_status   | TEXT    | NOT NULL                                 |
| action_note  | TEXT    |                                          |
| changed_at   | TEXT    | DEFAULT datetime('now')                  |

### `duplicate_links`
| Column               | Type    | Constraints                              |
|----------------------|---------|------------------------------------------|
| id                   | INTEGER | PK, AUTOINCREMENT                        |
| complaint_id         | TEXT    | NOT NULL, FK → complaints(complaint_id)  |
| matched_complaint_id | TEXT    | NOT NULL, FK → complaints(complaint_id)  |
| similarity_score     | REAL    | DEFAULT 0.0  (0.0 – 1.0)                |
| created_at           | TEXT    | DEFAULT datetime('now')                  |

### `action_notes`
| Column       | Type    | Constraints                              |
|--------------|---------|------------------------------------------|
| id           | INTEGER | PK, AUTOINCREMENT                        |
| complaint_id | TEXT    | NOT NULL, FK → complaints(complaint_id)  |
| note         | TEXT    | NOT NULL                                 |
| created_at   | TEXT    | DEFAULT datetime('now')                  |

---

## Technology Stack

| Layer        | Technology                                  | Phase   |
|--------------|---------------------------------------------|---------|
| Backend      | Python 3.11+, Flask 3.0                     | 1–7     |
| Database     | SQLite 3 (via built-in `sqlite3` module)    | 1–7     |
| Frontend     | HTML5, CSS3, JavaScript (Jinja2 templates)  | 2       |
| Maps         | Leaflet.js                                  | 5       |
| AI / NLP     | Hugging Face Transformers, sentence-transformers | 3  |
| LLM          | OpenAI GPT-4 / Google Gemini                | 4, 6    |
| Image AI     | Vision API for complaint images             | 3       |
| Dev tools    | VS Code, PowerShell, pytest                 | 1–7     |

---

## Installation (Windows PowerShell)

### Step 1 – Create the project folder and open in VS Code

```powershell
# Navigate to where you want to place the project (e.g. Desktop)
cd $HOME\Desktop

# Clone or create the civicai folder
# If you received the files, just place the civicai/ folder here.
# Then open in VS Code:
code civicai
```

### Step 2 – Create and activate a virtual environment

```powershell
cd $HOME\Desktop\civicai

# Create virtual environment
python -m venv venv

# Activate
.\venv\Scripts\Activate.ps1
```

> **Note:** If you get a script execution policy error, run:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```
> Then activate again.

### Step 3 – Install requirements

```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4 – Initialise the database

```powershell
python database.py
```

Expected output:
```
INFO: Database initialised at <path>\database\civicai.db
INFO: Departments seeded.
Database ready at: <path>\database\civicai.db
```

### Step 5 – Generate synthetic data

```powershell
python seed_data.py
```

Expected output:
```
INFO: === CivicAI Seed Script ===
INFO: Initialising database …
INFO: Departments seeded.
INFO: Seeded 12 officers.
INFO: Inserted 42 new complaints (skipped existing).
INFO: Seeded duplicate links.
INFO: Seeded status history entries.
INFO: Seeded action notes.
INFO: === Seed complete. ===
```

> Running the script a second time will show 0 new complaints (safe to re-run).

### Step 6 – Run database tests

```powershell
# Option A: using pytest (recommended)
python -m pytest tests/ -v

# Option B: using plain Python
python tests/test_database.py
```

Expected output (pytest):
```
tests/test_database.py::TestDatabaseConnection::test_close_connection_safe PASSED
tests/test_database.py::TestDatabaseConnection::test_foreign_keys_enabled PASSED
tests/test_database.py::TestDatabaseConnection::test_get_connection_returns_connection PASSED
tests/test_database.py::TestDatabaseConnection::test_row_factory_is_set PASSED
tests/test_database.py::TestTableCreation::test_all_tables_exist PASSED
tests/test_database.py::TestTableCreation::test_complaints_columns PASSED
tests/test_database.py::TestTableCreation::test_indexes_created PASSED
tests/test_database.py::TestForeignKeyEnforcement::test_insert_complaint_invalid_department_raises PASSED
tests/test_database.py::TestComplaintInsertion::test_complaint_defaults PASSED
tests/test_database.py::TestComplaintInsertion::test_insert_and_fetch_complaint PASSED
tests/test_database.py::TestUniqueComplaintID::test_duplicate_complaint_id_raises PASSED
tests/test_database.py::TestStatusHistoryInsertion::test_insert_status_history PASSED
tests/test_database.py::TestStatusHistoryInsertion::test_status_history_fk_invalid_complaint PASSED

13 passed in X.XXs
```

### Step 7 – Start Flask (Phase 1 smoke test)

```powershell
python app.py
```

Visit `http://127.0.0.1:5000/` — you should see:
```json
{"phase": 1, "status": "CivicAI backend is running"}
```

---

## Verifying the database directly (optional)

```powershell
# Count complaints
python -c "import database; conn = database.get_connection(); cur = conn.cursor(); cur.execute('SELECT COUNT(*) FROM complaints'); print('Complaints:', cur.fetchone()[0]); conn.close()"

# List categories
python -c "import database; conn = database.get_connection(); cur = conn.cursor(); cur.execute('SELECT category, COUNT(*) c FROM complaints GROUP BY category ORDER BY c DESC'); [print(dict(r)) for r in cur.fetchall()]; conn.close()"
```

---

## Future Phases

| Phase | Title                              | Description                                                    |
|-------|------------------------------------|----------------------------------------------------------------|
| 1     | ✅ Architecture, DB & Synthetic Data | Foundation, six tables, 40+ seed complaints, tests            |
| 2     | Flask Routes & Frontend            | Complaint submission form, department dashboard, status update |
| 3     | AI Categorisation & Deduplication  | Zero-shot NLP categoriser, sentence-transformer duplicate detection |
| 4     | Priority Scoring Engine            | Rule-based + LLM priority scoring (0–10), level assignment     |
| 5     | Hotspot Detection & Maps           | Haversine clustering, Leaflet.js heatmap, hotspot alerts       |
| 6     | Action Brief Generator             | GPT-4 / Gemini action briefs for officers, SLA suggestions     |
| 7     | Dashboard, Reports & Deployment    | Charts, CSV export, admin panel, production deployment         |

---

## Demo City

All synthetic complaints are set in **Novapolis** (fictional), centred at  
`12.9716° N, 77.5946° E`.  
No real personal data is used anywhere in the seed dataset.

---

*Built for PromptWars × ASTRA Hackathon*
