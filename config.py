"""
Configuration for JobHunter application.
Loads environment variables and defines search criteria.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Base paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CV_PATH = DATA_DIR / "cv.txt"

# Flask Configuration
class Config:
    """Flask application configuration."""

    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-in-production")
    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    ENV = os.getenv("FLASK_ENV", "production")

    # Database
    DATABASE_PATH = os.getenv("DATABASE_PATH", str(DATA_DIR / "jobhunter.db"))
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DATABASE_PATH}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Scheduler
    SCHEDULER_API_ENABLED = True
    SCRAPER_SCHEDULE_HOUR = int(os.getenv("SCRAPER_SCHEDULE_HOUR", "8"))
    SCRAPER_SCHEDULE_MINUTE = int(os.getenv("SCRAPER_SCHEDULE_MINUTE", "0"))


# API Credentials
class APIKeys:
    """External API credentials."""

    # France Travail
    FRANCE_TRAVAIL_CLIENT_ID = os.getenv("FRANCE_TRAVAIL_CLIENT_ID")
    FRANCE_TRAVAIL_CLIENT_SECRET = os.getenv("FRANCE_TRAVAIL_CLIENT_SECRET")
    FRANCE_TRAVAIL_API_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
    FRANCE_TRAVAIL_OFFERS_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"

    # Anthropic
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"


# Scraping Configuration
class ScrapingConfig:
    """Web scraping settings."""

    DELAY_MIN = int(os.getenv("SCRAPING_DELAY_MIN", "2"))
    DELAY_MAX = int(os.getenv("SCRAPING_DELAY_MAX", "5"))
    USER_AGENT = os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    TIMEOUT = 30
    MAX_RETRIES = 3

    # Selenium
    SELENIUM_HEADLESS = os.getenv("SELENIUM_HEADLESS", "true").lower() == "true"
    SELENIUM_TIMEOUT = int(os.getenv("SELENIUM_TIMEOUT", "30"))


# Job Search Criteria
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

FILTERS = {
    "contract_type": "alternance",
    "location": "Île-de-France",
    "departments": ["75", "78", "91", "92", "93", "94", "95", "77"],
    "min_level": "bac+3",
    "max_level": "bac+5",
    "duration": "24 months",
}

# Target companies receive bonus relevance score
TARGET_COMPANIES = [
    "Thales", "Safran", "Capgemini", "Sopra Steria", "Atos", "Eviden",
    "Orange", "Airbus", "CGI", "Alten", "Bouygues Telecom", "SFR",
    "Société Générale", "BNP Paribas", "AXA", "Engie", "EDF",
    "Dassault", "Naval Group", "SNCF", "RATP", "Renault", "PSA",
]

# Company Career Sites
CAREER_SITES = {
    "Thales": "https://careers.thalesgroup.com",
    "Safran": "https://www.safran-group.com/fr/emplois",
    "Capgemini": "https://www.capgemini.com/fr-fr/carrieres",
    "Sopra Steria": "https://www.soprasteria.com/rejoignez-nous",
    "Atos": "https://jobs.atos.net",
    "Orange": "https://orange.jobs",
    "Airbus": "https://www.airbus.com/en/careers",
    "CGI": "https://www.cgi.com/france/fr-fr/carrieres",
    "Alten": "https://www.alten.com/rejoignez-nous",
    "Bouygues Telecom": "https://www.bouyguestelecom.fr/groupe/recrutement",
}

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", str(DATA_DIR / "jobhunter.log"))
