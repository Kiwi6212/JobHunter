"""
Configuration for JobHunter application.
Loads environment variables and defines search criteria.
"""

import os
import sys
from datetime import timedelta
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

    _raw_key = os.getenv("FLASK_SECRET_KEY", "")
    if not _raw_key:
        # Block startup with the insecure default key in non-debug mode
        _fallback = "dev-secret-key-change-in-production"
        _debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
        if not _debug_mode:
            print(
                "[SECURITY] FLASK_SECRET_KEY is not set. "
                "Set it to a random 32-byte hex string before running in production.",
                file=sys.stderr,
            )
        SECRET_KEY = _fallback
    else:
        SECRET_KEY = _raw_key

    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    ENV = os.getenv("FLASK_ENV", "production")

    # Session cookie hardening
    SESSION_COOKIE_HTTPONLY = True           # JS cannot read the cookie
    SESSION_COOKIE_SAMESITE = "Lax"         # CSRF mitigation for cross-site requests
    SESSION_COOKIE_SECURE = os.getenv("FLASK_ENV") == "production"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    # CSRF (Flask-WTF)
    WTF_CSRF_TIME_LIMIT = 3600              # Token valid for 1 hour

    # Database
    DATABASE_PATH = os.getenv("DATABASE_PATH", str(DATA_DIR / "jobhunter.db"))
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DATABASE_PATH}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Request size limit (10 MB)
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024

    # Monitoring
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
    ERROR_LOG_PATH = str(DATA_DIR / "errors.log")

    # TOTP secret encryption key (Fernet — generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    TOTP_ENCRYPTION_KEY = os.getenv("TOTP_ENCRYPTION_KEY")

    # Email / SMTP (Flask-Mail)
    MAIL_SERVER = os.getenv("MAIL_SERVER", "ssl0.ovh.net")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "noreply@myjobhunter.fr")

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

    # La bonne alternance
    LBA_API_KEY = os.getenv("LBA_API_KEY")
    LBA_API_URL = "https://api.apprentissage.beta.gouv.fr/api"

    # Anthropic
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"


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

# Target companies receive bonus relevance score (+30)
# Matching is case-insensitive and partial (e.g. "Orange" matches "ORANGE BUSINESS SERVICES")
TARGET_COMPANIES = [
    # ESN & Intégrateurs (Infra/Cloud/Réseau)
    "Claranet", "Linkbynet", "Cheops Technology", "Oxalide", "Saitis",
    "Axians", "Spie Infoservices", "I-Tracing",
    "Capgemini", "Sopra Steria", "Atos", "CGI", "Accenture", "Devoteam",
    "SII", "Neurones", "Econocom", "Inetum", "Aubay",
    "Alten", "Altran", "Scalian",
    # Opérateurs & Cloud Providers
    "Scaleway", "Iliad", "OVHcloud", "Jaguar Network", "Free Pro",
    "Hub One", "3DS Outscale", "Equinix",
    "Bouygues Telecom", "SFR Business", "Orange", "SFR",
    # Grands Groupes (DSI fortes contraintes Infra/Système)
    "Air France-KLM", "CMA CGM", "Natixis", "BPCE",
    "Veolia", "Schneider Electric", "Air Liquide", "Vinci",
    "Thales", "Airbus", "Dassault Systèmes",
    "EDF", "Engie", "TotalEnergies", "SNCF", "RATP", "La Poste",
    # Banques & Assurances
    "BNP Paribas", "Société Générale", "Crédit Agricole", "AXA",
    "Banque de France",
    # Secteur public & organismes gouvernementaux
    "ANSSI", "DINUM", "DGSI", "Ministère des Armées", "Ministère de l'Intérieur",
    "CNES", "CEA", "CNRS", "AP-HP",
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

# ROME codes for sysadmin/network admin job searches
# Used by La bonne alternance API (no free-text search, ROME codes only)
ROME_CODES = [
    "M1801",  # Administration de systemes d'information
    "M1810",  # Production et exploitation de systemes d'information
    "I1401",  # Maintenance informatique et bureautique
    "M1802",  # Expertise et support en systemes d'information
]

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", str(DATA_DIR / "jobhunter.log"))
