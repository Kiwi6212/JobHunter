# JobHunter

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/Flask-3.0+-green.svg)](https://flask.palletsprojects.com)

> Automated job monitoring tool for work-study (alternance) opportunities in Systems & Network Administration. Aggregates multiple sources, filters offers by criteria, and provides an interactive tracking dashboard.

---

## Overview

JobHunter is a self-hosted job search assistant that automates the tedious part of job hunting. It collects offers from official APIs, job boards, and company career pages, filters them against predefined criteria, and presents everything in a web dashboard with full application tracking.

**Key principles:**

* **Semi-automated** — The tool finds and filters offers; the user decides when and where to apply
* **Privacy-first** — Runs locally with SQLite, no data sent to external services (except Claude API for cover letter generation)
* **Multi-source** — Aggregates France Travail API, Welcome to the Jungle, Indeed, and company career sites
* **Trackable** — Built-in application tracker with status management, follow-up reminders, and statistics

**What this tool does NOT do:**

* It does not send applications automatically
* It does not log into user accounts on job platforms
* It does not store sensitive data online

---

## Features

### Job Aggregation

* Multi-source collection via official APIs and web scraping
* Keyword-based filtering (title and description matching)
* Location, contract type, and education level filters
* Cross-source duplicate detection
* Daily automated execution via scheduler

### Application Tracker

* Interactive tracking table with per-offer status management
* Checkbox columns: CV sent, follow-up done
* Date fields: date sent, follow-up date
* Status workflow: `New` → `Applied` → `Followed up` → `Interview` → `Accepted` / `Rejected` / `No response`
* Free-text notes per offer
* Filters by status, source, company, and date range
* Column sorting and full-text search
* CSV export

### Cover Letter Generation

* AI-generated draft per offer via Anthropic Claude API
* Personalized based on user CV + job description
* Saved in database to avoid regeneration
* One-click copy to clipboard

### Statistics

* Total offers found and new offers this week
* CVs sent, follow-ups done, interviews obtained
* Response rate tracking

---

## Tech Stack

| Layer | Technology |
| --- | --- |
| Backend | [Flask](https://flask.palletsprojects.com/) with Python 3.11+ |
| Database | SQLite (lightweight, no server required) |
| Scraping | [Requests](https://docs.python-requests.org/) + [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/) |
| Advanced Scraping | [Selenium](https://www.selenium.dev/) (JS-rendered sites) |
| Scheduler | [APScheduler](https://apscheduler.readthedocs.io/) |
| Frontend | HTML/CSS/JS with [Jinja2](https://jinja.palletsprojects.com/) + [DataTables.js](https://datatables.net/) |
| AI | [Anthropic API](https://docs.anthropic.com/) (Claude) |

---

## Job Sources

| Source | Method | Priority |
| --- | --- | --- |
| [France Travail](https://francetravail.io/data/api/offres-emploi) | Official REST API (OAuth2) | High |
| [Welcome to the Jungle](https://www.welcometothejungle.com) | Web scraping | High |
| Company career sites (see below) | Custom scrapers | High |
| [Indeed](https://fr.indeed.com) | Web scraping | Medium |
| [LinkedIn](https://www.linkedin.com/jobs) | Public listings scraping | Low / Optional |

### Target Company Career Sites

| Company | Career Page | Sector |
| --- | --- | --- |
| Thales | https://careers.thalesgroup.com | Defense / Aerospace |
| Safran | https://www.safran-group.com/fr/emplois | Aerospace |
| Capgemini | https://www.capgemini.com/fr-fr/carrieres | IT Services |
| Sopra Steria | https://www.soprasteria.com/rejoignez-nous | IT Services |
| Atos / Eviden | https://jobs.atos.net | IT Services |
| Orange | https://orange.jobs | Telecom |
| Airbus | https://www.airbus.com/en/careers | Aerospace |
| CGI | https://www.cgi.com/france/fr-fr/carrieres | IT Services |
| Alten | https://www.alten.com/rejoignez-nous | IT Services |
| Bouygues Telecom | https://www.bouyguestelecom.fr/groupe/recrutement | Telecom |

---

## Search Criteria

### Keywords

```python
KEYWORDS = [
    "administrateur systèmes et réseaux",
    "administrateur systèmes",
    "administrateur réseaux",
    "admin sys",
    "admin réseau",
    "technicien systèmes et réseaux",
    "ingénieur systèmes",
    "ingénieur infrastructure",
    "technicien infrastructure",
    "technicien informatique",
    "administrateur infrastructure",
    "ingénieur réseaux",
    "sysadmin",
]
```

### Filters

```python
FILTERS = {
    "contract_type": "alternance",
    "location": "Île-de-France",
    "departments": ["75", "78", "91", "92", "93", "94", "95", "77"],
    "min_level": "bac+3",
    "max_level": "bac+5",
    "duration": "24 months",
}
```

### Target Companies (Bonus Scoring)

Offers from major companies receive a higher relevance score:

```python
TARGET_COMPANIES = [
    "Thales", "Safran", "Capgemini", "Sopra Steria", "Atos", "Eviden",
    "Orange", "Airbus", "CGI", "Alten", "Bouygues Telecom", "SFR",
    "Société Générale", "BNP Paribas", "AXA", "Engie", "EDF",
    "Dassault", "Naval Group", "SNCF", "RATP", "Renault", "PSA",
]
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  SCHEDULER (APScheduler)             │
│               Daily execution at 8:00 AM             │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│                   COLLECTORS                        │
│                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │ France   │ │ Welcome  │ │  Career  │ │ Indeed │ │
│  │ Travail  │ │ to the   │ │  Sites   │ │        │ │
│  │  (API)   │ │ Jungle   │ │ (custom) │ │        │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └───┬────┘ │
└───────┼─────────────┼───────────┼────────────┼──────┘
        │             │           │            │
        ▼             ▼           ▼            ▼
┌─────────────────────────────────────────────────────┐
│                   FILTER ENGINE                     │
│                                                     │
│  Keywords · Location · Contract type · Dedup        │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│                 DATABASE (SQLite)                   │
│                                                     │
│  offers ──── tracking ──── cover_letter_drafts      │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│                WEB DASHBOARD (Flask)                │
│                                                     │
│  Offer table · Tracking · Filters · Stats · Export  │
│                                                     │
│  http://localhost:5000                              │
└─────────────────────────────────────────────────────┘
```

---

## Project Structure

```
JobHunter/
├── app/
│   ├── __init__.py              # Flask initialization
│   ├── routes.py                # Dashboard routes
│   ├── models.py                # SQLite models (offers, tracking)
│   ├── database.py              # Database connection and init
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── base_scraper.py      # Abstract base class
│   │   ├── france_travail.py    # France Travail API
│   │   ├── wttj.py              # Welcome to the Jungle
│   │   ├── indeed.py            # Indeed
│   │   ├── linkedin.py          # LinkedIn (optional)
│   │   └── career_sites/
│   │       ├── __init__.py
│   │       ├── thales.py
│   │       ├── safran.py
│   │       ├── capgemini.py
│   │       └── ...
│   ├── services/
│   │   ├── __init__.py
│   │   ├── filter_engine.py     # Offer filtering
│   │   ├── deduplication.py     # Duplicate detection
│   │   ├── cover_letter.py      # Claude API integration
│   │   └── scheduler.py         # Task scheduling
│   ├── templates/
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── offer_detail.html
│   │   └── stats.html
│   └── static/
│       ├── css/
│       │   └── style.css
│       └── js/
│           └── dashboard.js
├── data/
│   ├── jobhunter.db             # SQLite database (gitignored)
│   └── cv.txt                   # CV for cover letter generation
├── scripts/
│   ├── run_scrapers.py          # Manual scraper execution
│   └── init_db.py               # Database initialization
├── tests/
│   ├── test_scrapers.py
│   └── test_filters.py
├── .env.example
├── .gitignore
├── config.py
├── requirements.txt
├── ROADMAP.md
└── README.md
```

---

## Installation

### Prerequisites

* Python 3.11+
* France Travail developer account ([francetravail.io](https://francetravail.io))
* Anthropic API key ([console.anthropic.com](https://console.anthropic.com)) — for cover letter generation

### Setup

```bash
git clone https://github.com/Kiwi6212/JobHunter.git
cd JobHunter

python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your API credentials:

```env
FRANCE_TRAVAIL_CLIENT_ID=your_client_id
FRANCE_TRAVAIL_CLIENT_SECRET=your_client_secret
ANTHROPIC_API_KEY=your_api_key
FLASK_SECRET_KEY=a_random_secret_key
FLASK_DEBUG=true
```

### Running

```bash
# Initialize the database
python scripts/init_db.py

# Run scrapers manually
python scripts/run_scrapers.py

# Launch the dashboard
python -m flask run
```

The dashboard is available at `http://localhost:5000`.

---

## Development Roadmap

### Phase 1 — Foundations
1. Project setup (folder structure, dependencies, configuration)
2. Database models (`offers` and `tracking` tables)
3. Basic Flask dashboard with empty table

### Phase 2 — First Source
4. France Travail API integration (OAuth2, search, parsing)
5. Filter engine (keywords, location, contract type)
6. Offer display in dashboard table

### Phase 3 — Tracking
7. Interactive columns (checkboxes, date fields, status dropdown)
8. AJAX persistence (save changes without page reload)
9. Filters and column sorting

### Phase 4 — Additional Sources
10. Welcome to the Jungle scraper
11. Career site scrapers (Thales, Safran, then others)
12. Cross-source deduplication

### Phase 5 — Intelligence
13. Cover letter generation (Claude API)
14. Relevance scoring based on profile match

### Phase 6 — Automation & Polish
15. APScheduler for daily execution
16. Statistics dashboard header
17. CSV export
18. Indeed scraper
19. LinkedIn scraper (optional)
20. UI/UX improvements

See [ROADMAP.md](ROADMAP.md) for detailed progress.

---

## Security

* **API keys** — Stored in `.env`, never committed to version control
* **Database** — Local SQLite file excluded from Git
* **Scraping** — Respects `robots.txt`, includes delays between requests, realistic user-agent headers
* **Rate limiting** — Built-in delays to avoid IP blocking
* **Personal data** — CV stored locally only, transmitted exclusively to Claude API for cover letter generation

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Credits

**Mathias Quillateau** — [GitHub](https://github.com/Kiwi6212) · [LinkedIn](https://linkedin.com/in/mathias-q-sysadmin)

Code assisted by **Claude Code** (Anthropic).
