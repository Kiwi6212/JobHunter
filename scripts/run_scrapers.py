"""
Manual scraper execution script for JobHunter.
Runs all configured scrapers for every active domain in the database,
filters results per-domain, and saves offers with the correct domain_id.

Usage:
    python scripts/run_scrapers.py
"""

import sys
import hashlib
import hmac
import html as _html
import logging
from pathlib import Path
from datetime import datetime, timezone

# Add project root to Python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# ── Import scraper/service MODULES by reference so we can patch their
#    module-level globals (ROME_CODES, SEARCH_QUERIES, KEYWORDS …) before
#    each domain run without touching the individual scraper files.
import app.scrapers.france_travail as _ft_mod
import app.scrapers.lba as _lba_mod
import app.scrapers.wttj as _wttj_mod
import app.scrapers.indeed as _indeed_mod
import app.scrapers.smartrecruiters as _sr_mod
import app.scrapers.workday as _wd_mod
import app.scrapers.lever as _lever_mod
import app.scrapers.talentbrew as _tb_mod
import app.scrapers.phenom as _phenom_mod
import app.scrapers.place_emploi_public as _pep_mod
import app.scrapers.safran as _safran_mod
import app.scrapers.bpce as _bpce_mod
import app.services.filter_engine as _fe_mod

from app.database import SessionLocal, init_db
from app.models import Offer, Tracking, Domain, User, UserOffer
from config import Config, LOG_LEVEL

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Per-domain scraping configuration ────────────────────────────────────────
#
# Keys must match the Domain.name values stored in the DB.
# If a domain name from the DB is not found here, it is skipped with a warning.
#
# rome_codes        → France Travail & La Bonne Alternance ROME code lists
# keywords          → FilterEngine keyword list (and WTTJ keyword matching)
# search_queries    → WTTJ / Indeed / SmartRecruiters / Workday / TalentBrew / Phenom
# wttj_subcategory  → WTTJ Algolia subcategory slug; "" disables sub-category filter

DOMAIN_SCRAPER_CONFIG = {
    "Sysadmin / Infrastructure": {
        "rome_codes": ["M1801", "M1810", "I1401", "M1802"],
        "keywords": [
            "administrateur systèmes",
            "sysadmin",
            "system administrator",
            "administrateur linux",
            "administrateur windows",
            "infrastructure",
            "virtualisation",
            "vmware",
            "proxmox",
            "hyper-v",
            "active directory",
            "ansible",
            "puppet",
            "chef",
            "nagios",
            "zabbix",
            "supervision",
            "bash",
            "powershell",
            "alternance",
            "apprentissage",
        ],
        "search_queries": [
            "",
            "alternance administrateur systèmes",
            "apprentissage infrastructure",
            "administrateur linux alternance",
            "sysadmin apprentissage",
        ],
        "wttj_subcategory": "network-engineering-and-administration-yZjhm",
    },
    "Développement": {
        "rome_codes": ["M1805", "M1806", "M1807", "M1809"],
        "keywords": [
            "développeur",
            "developer",
            "software engineer",
            "ingénieur logiciel",
            "python",
            "javascript",
            "typescript",
            "java",
            "golang",
            "rust",
            "c++",
            "react",
            "vue",
            "angular",
            "backend",
            "frontend",
            "full stack",
            "fullstack",
            "api",
            "rest",
            "microservices",
            "alternance",
            "apprentissage",
        ],
        "search_queries": [
            "",
            "alternance développeur",
            "apprentissage software engineer",
            "développeur python alternance",
            "développeur javascript apprentissage",
        ],
        "wttj_subcategory": "",
    },
    "Data / IA": {
        "rome_codes": ["M1805", "M1809", "M1803", "M1810"],
        "keywords": [
            "data scientist",
            "data engineer",
            "data analyst",
            "machine learning",
            "deep learning",
            "intelligence artificielle",
            "artificial intelligence",
            "NLP",
            "LLM",
            "MLOps",
            "python",
            "spark",
            "hadoop",
            "SQL",
            "databricks",
            "airflow",
            "tensorflow",
            "pytorch",
            "alternance",
            "apprentissage",
        ],
        "search_queries": [
            "",
            "alternance data scientist",
            "apprentissage data engineer",
            "machine learning alternance",
            "data analyst apprentissage",
        ],
        "wttj_subcategory": "",
    },
    "Cybersécurité": {
        "rome_codes": ["M1801", "M1802", "M1810", "M1706"],
        "keywords": [
            "cybersécurité",
            "cybersecurity",
            "sécurité informatique",
            "SOC",
            "SIEM",
            "pentester",
            "pentest",
            "red team",
            "blue team",
            "analyste sécurité",
            "security analyst",
            "RSSI",
            "CISO",
            "ISO 27001",
            "ANSSI",
            "EDR",
            "XDR",
            "forensique",
            "forensics",
            "vulnerability",
            "alternance",
            "apprentissage",
        ],
        "search_queries": [
            "",
            "alternance cybersécurité",
            "apprentissage sécurité informatique",
            "SOC analyst alternance",
            "pentester apprentissage",
        ],
        "wttj_subcategory": "",
    },
    "Cloud / DevOps": {
        "rome_codes": ["M1801", "M1810", "M1802", "M1805"],
        "keywords": [
            "devops",
            "cloud",
            "AWS",
            "Azure",
            "GCP",
            "Google Cloud",
            "kubernetes",
            "docker",
            "terraform",
            "helm",
            "CI/CD",
            "gitlab CI",
            "github actions",
            "jenkins",
            "SRE",
            "site reliability",
            "infrastructure as code",
            "alternance",
            "apprentissage",
        ],
        "search_queries": [
            "",
            "alternance devops",
            "apprentissage cloud engineer",
            "kubernetes alternance",
            "AWS apprentissage",
        ],
        "wttj_subcategory": "",
    },
    "Droit": {
        "rome_codes": ["K1903", "K1901", "K1904"],
        "keywords": [
            "juriste",
            "avocat",
            "droit",
            "juridique",
            "contentieux",
            "compliance",
            "RGPD",
            "notaire",
            "paralegal",
            "contrat",
            "propriété intellectuelle",
            "droit des affaires",
            "droit social",
            "alternance",
            "apprentissage",
        ],
        "search_queries": [
            "",
            "juriste alternance",
            "droit alternance",
            "compliance alternance",
        ],
        "wttj_subcategory": "",
    },
    "Commerce / Marketing": {
        "rome_codes": ["D1406", "M1705", "E1103"],
        "keywords": [
            "commercial",
            "marketing",
            "vente",
            "CRM",
            "business",
            "business developer",
            "chef de produit",
            "community manager",
            "e-commerce",
            "prospection",
            "négociation",
            "trade marketing",
            "digital marketing",
            "alternance",
            "apprentissage",
        ],
        "search_queries": [
            "",
            "commercial alternance",
            "marketing alternance",
            "business developer alternance",
        ],
        "wttj_subcategory": "",
    },
    "Santé": {
        "rome_codes": ["J1506", "J1502", "J1501"],
        "keywords": [
            "infirmier",
            "médecin",
            "santé",
            "hôpital",
            "soins",
            "pharmacie",
            "aide-soignant",
            "kiné",
            "kinésithérapeute",
            "paramédical",
            "clinique",
            "médical",
            "alternance",
            "apprentissage",
        ],
        "search_queries": [
            "",
            "santé alternance",
            "infirmier alternance",
            "médical alternance",
        ],
        "wttj_subcategory": "",
    },
    "Ingénierie": {
        "rome_codes": ["H1206", "H1402", "H2502"],
        "keywords": [
            "ingénieur",
            "conception",
            "calcul",
            "industriel",
            "mécanique",
            "électronique",
            "production",
            "qualité",
            "bureau d'études",
            "CAO",
            "CATIA",
            "SolidWorks",
            "process",
            "R&D",
            "alternance",
            "apprentissage",
        ],
        "search_queries": [
            "",
            "ingénieur alternance",
            "mécanique alternance",
            "production alternance",
        ],
        "wttj_subcategory": "",
    },
}


def _apply_domain_config(cfg: dict) -> None:
    """Patch module-level globals in all scraper/service modules for this domain."""
    _ft_mod.ROME_CODES = cfg["rome_codes"]
    _lba_mod.ROME_CODES = cfg["rome_codes"]
    _wttj_mod.SEARCH_QUERIES = cfg["search_queries"]
    _wttj_mod.SYSADMIN_SUBCATEGORY = cfg.get("wttj_subcategory", "")
    _indeed_mod.SEARCH_QUERIES = cfg["search_queries"]
    _sr_mod.SEARCH_QUERIES = cfg["search_queries"]
    _wd_mod.SEARCH_QUERIES = cfg["search_queries"]
    _tb_mod.SEARCH_QUERIES = cfg["search_queries"]
    _phenom_mod.SEARCH_QUERIES = cfg["search_queries"]
    _safran_mod.SEARCH_QUERIES = cfg["search_queries"]
    _bpce_mod.SEARCH_QUERIES = cfg["search_queries"]
    # FilterEngine reads KEYWORDS at __init__ time; patch before instantiation
    _fe_mod.KEYWORDS = cfg["keywords"]


def load_domains() -> list[tuple[int, str]]:
    """Return list of (domain_id, domain_name) for all domains in the DB."""
    db = SessionLocal()
    try:
        domains = db.query(Domain.id, Domain.name).all()
        return [(d.id, d.name) for d in domains]
    finally:
        db.close()


def save_offers_to_db(
    offers: list[dict],
    domain_id: int,
    seen_urls: set,
    seen_ext_ids: set,
    new_offer_ids: list[int] | None = None,
) -> tuple[int, int]:
    """
    Save filtered offers to the database for a specific domain.

    Args:
        offers         – filtered offer dicts from FilterEngine
        domain_id      – domain to associate with new offers
        seen_urls      – global set of URLs already saved (updated in-place)
        seen_ext_ids   – global set of external_ids already saved (updated in-place)
        new_offer_ids  – if provided, newly created offer IDs are appended here

    Returns:
        (new_count, duplicate_count)
    """
    db = SessionLocal()
    new_count = 0
    duplicate_count = 0

    try:
        for offer_data in offers:
            url = offer_data["url"]
            ext_id = offer_data.get("external_id")

            # Global dedup: skip if already seen in this run or in DB
            if url in seen_urls:
                duplicate_count += 1
                continue
            if ext_id and ext_id in seen_ext_ids:
                duplicate_count += 1
                continue

            # Check DB for existing URL
            if db.query(Offer.id).filter(Offer.url == url).first():
                seen_urls.add(url)
                duplicate_count += 1
                continue

            # Check DB for existing external_id
            if ext_id and db.query(Offer.id).filter(Offer.external_id == ext_id).first():
                seen_ext_ids.add(ext_id)
                duplicate_count += 1
                continue

            # Create new offer
            new_offer = Offer(
                title=offer_data["title"],
                company=offer_data["company"],
                location=offer_data.get("location"),
                contract_type=offer_data.get("contract_type"),
                description=offer_data.get("description"),
                url=url,
                source=offer_data["source"],
                external_id=ext_id,
                posted_date=offer_data.get("posted_date"),
                relevance_score=offer_data.get("relevance_score", 0.0),
                offer_type=offer_data.get("offer_type", "job"),
                found_date=datetime.utcnow(),
                domain_id=domain_id,
            )
            db.add(new_offer)
            db.flush()  # get offer.id before creating tracking entry

            tracking = Tracking(offer_id=new_offer.id, status="New")
            db.add(tracking)

            seen_urls.add(url)
            if ext_id:
                seen_ext_ids.add(ext_id)
            new_count += 1

            if new_offer_ids is not None:
                new_offer_ids.append(new_offer.id)

        db.commit()
        logger.info(f"[db] Saved {new_count} new offers, {duplicate_count} duplicates skipped")

    except Exception as e:
        db.rollback()
        logger.error(f"[db] Error saving offers: {e}", exc_info=True)
    finally:
        db.close()

    return new_count, duplicate_count


def run_domain(
    domain_id: int,
    domain_name: str,
    seen_urls: set,
    seen_ext_ids: set,
    new_offer_ids: list[int] | None = None,
) -> tuple[int, int]:
    """
    Run all scrapers for a single domain.

    Patches module globals, runs scrapers, filters results, and saves to DB.

    Returns:
        (new_count, duplicate_count) totals for this domain
    """
    cfg = DOMAIN_SCRAPER_CONFIG.get(domain_name)
    if cfg is None:
        logger.warning(
            f"[domain] No scraper config for domain '{domain_name}' (id={domain_id}) — skipping"
        )
        return 0, 0

    print(f"\n{'─' * 60}")
    print(f"  Domain: {domain_name}  (id={domain_id})")
    print(f"{'─' * 60}")

    # Patch all module globals for this domain
    _apply_domain_config(cfg)

    # Instantiate scrapers AFTER patching so they pick up the new globals
    scrapers = [
        _ft_mod.FranceTravailScraper(),
        _lba_mod.LaBonneAlternanceScraper(),
        _wttj_mod.WTTJScraper(),
        _indeed_mod.IndeedScraper(),
        _sr_mod.SmartRecruitersScraper(),
        _wd_mod.WorkdayScraper(),
        _lever_mod.LeverScraper(),
        _tb_mod.TalentBrewScraper(),
        _phenom_mod.PhenomScraper(),
        _pep_mod.PlaceEmploiPublicScraper(),
        _safran_mod.SafranScraper(),
        _bpce_mod.BpceScraper(),
    ]

    # Collect raw offers from all scrapers
    all_raw = []
    for scraper in scrapers:
        logger.info(f"  [{domain_name}] Running {scraper.source_name}")
        try:
            offers = scraper.run()
            all_raw.extend(offers)
            logger.info(f"  [{domain_name}]   → {len(offers)} raw offers")
        except Exception as e:
            logger.error(f"  [{domain_name}] Scraper {scraper.source_name} failed: {e}", exc_info=True)

    print(f"  Raw offers collected: {len(all_raw)}")

    if not all_raw:
        print(f"  [!] No raw offers for '{domain_name}'")
        return 0, 0

    # Filter — FilterEngine reads KEYWORDS from _fe_mod (already patched)
    filter_engine = _fe_mod.FilterEngine()
    filtered = filter_engine.filter_offers(all_raw)
    print(f"  After filtering: {len(filtered)} offers")

    if not filtered:
        print(f"  [!] No offers passed filter for '{domain_name}'")
        return 0, 0

    # Save with domain_id (global dedup via seen_urls / seen_ext_ids)
    new_count, dup_count = save_offers_to_db(filtered, domain_id, seen_urls, seen_ext_ids, new_offer_ids)
    print(f"  Saved: {new_count} new, {dup_count} duplicates skipped")

    return new_count, dup_count


def main():
    """Main entry point: scrape all active domains from the DB."""
    print("=" * 60)
    print("JobHunter — Multi-Domain Scraper Runner")
    print("=" * 60)

    # Ensure DB schema exists
    init_db()

    # Load all domains from DB
    domains = load_domains()
    if not domains:
        print("[!] No domains found in the database. Run init_saas.py first.")
        return

    print(f"\n[+] Found {len(domains)} domain(s): {', '.join(name for _, name in domains)}")

    # Global dedup sets — shared across all domain runs
    seen_urls: set = set()
    seen_ext_ids: set = set()
    new_offer_ids: list[int] = []

    total_new = 0
    total_dup = 0

    for domain_id, domain_name in domains:
        new_count, dup_count = run_domain(domain_id, domain_name, seen_urls, seen_ext_ids, new_offer_ids)
        total_new += new_count
        total_dup += dup_count

    # ── Post-scraping deduplication ──────────────────────────────────
    from scripts.cleanup_offers import cleanup_duplicate_offers
    logger.info("[dedup] Running post-scraping deduplication...")
    dedup_removed = cleanup_duplicate_offers()

    # ── Instant email alerts for high-match offers ───────────────────
    if new_offer_ids:
        logger.info(f"[alert] Checking {len(new_offer_ids)} new offer(s) for instant alerts...")
        try:
            send_instant_alerts(new_offer_ids)
        except Exception as exc:
            logger.error(f"[alert] Instant alerts failed: {exc}", exc_info=True)

    print(f"\n{'=' * 60}")
    print(f"[OK] All domains processed.")
    print(f"     Total new offers saved : {total_new}")
    print(f"     Total duplicates skipped: {total_dup}")
    print(f"     Dedup pass removed      : {dedup_removed}")
    print(f"[OK] Launch dashboard: python run.py")
    print(f"{'=' * 60}")


# ── Instant email alerts ────────────────────────────────────────────────────

ALERT_MIN_SCORE = 80
ALERT_MAX_PER_DAY = 3
ALERT_BASE_URL = Config.BASE_URL if hasattr(Config, "BASE_URL") else "https://myjobhunter.fr"

# Allowed CV extensions (mirrors routes.py)
_CV_EXTS = {".pdf", ".docx", ".doc", ".txt", ".rtf", ".odt"}


def _find_cv_text_for_user(user_id: int) -> str | None:
    """Find and extract CV text for a user from data/documents/{user_id}/."""
    docs_dir = Path(project_root) / "data" / "documents" / str(user_id)
    if not docs_dir.exists():
        return None

    files = [f for f in docs_dir.iterdir() if f.is_file() and f.suffix.lower() in _CV_EXTS]
    if not files:
        return None

    # Priority: files whose stem contains 'cv', most recent first
    cv_named = sorted(
        [f for f in files if "cv" in f.stem.lower()],
        key=lambda f: f.stat().st_mtime, reverse=True,
    )
    target = cv_named[0] if cv_named else sorted(
        [f for f in files if f.suffix.lower() in (".pdf", ".docx")],
        key=lambda f: f.stat().st_mtime, reverse=True,
    )[0] if any(f.suffix.lower() in (".pdf", ".docx") for f in files) else None

    if target is None:
        return None

    try:
        ext = target.suffix.lower()
        if ext == ".pdf":
            import pdfplumber
            with pdfplumber.open(target) as pdf:
                return "\n".join(p.extract_text() or "" for p in pdf.pages)
        elif ext == ".docx":
            import docx
            doc = docx.Document(target)
            return "\n".join(p.text for p in doc.paragraphs)
        elif ext in (".txt", ".rtf"):
            return target.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.warning(f"[alert] Cannot extract CV text for user {user_id}: {exc}")
    return None


def _build_alert_email_html(username: str, offer, score: float) -> str:
    """Build instant alert HTML email for a single high-match offer."""
    safe_user = _html.escape(username)
    safe_title = _html.escape(offer.title or "Sans titre")
    safe_company = _html.escape(offer.company or "Entreprise inconnue")
    safe_location = _html.escape(offer.location or "France")
    detail_url = _html.escape(f"{ALERT_BASE_URL}/offer/{offer.id}")
    dashboard_url = _html.escape(f"{ALERT_BASE_URL}/dashboard")

    score_bg = "#dcfce7" if score >= 90 else "#fef9c3"
    score_fg = "#15803d" if score >= 90 else "#854d0e"

    return f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;padding:40px 0;">
    <tr><td align="center">
      <table width="580" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:12px;box-shadow:0 4px 24px rgba(0,0,0,.08);overflow:hidden;">
        <tr>
          <td style="background:linear-gradient(135deg,#2563eb,#1d4ed8);padding:28px 40px;text-align:center;">
            <span style="font-size:2.2rem;">&#128640;</span>
            <h1 style="margin:8px 0 0;color:#ffffff;font-size:1.4rem;font-weight:700;letter-spacing:-.3px;">
              MyJobHunter
            </h1>
          </td>
        </tr>
        <tr>
          <td style="padding:36px 40px;">
            <h2 style="margin:0 0 12px;font-size:1.15rem;color:#0f172a;">
              Nouvelle offre \u00e0 {score:.0f}% pour vous !
            </h2>
            <p style="margin:0 0 20px;color:#475569;font-size:.95rem;line-height:1.6;">
              Bonjour <strong>{safe_user}</strong>,<br>
              Une offre vient d\u2019\u00eatre d\u00e9couverte avec un excellent score
              de correspondance avec votre CV.
            </p>
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;margin-bottom:24px;">
              <tr style="background:#f1f5f9;">
                <th style="padding:10px 12px;text-align:left;font-size:.82rem;color:#475569;font-weight:600;
                           border-bottom:1px solid #e2e8f0;">Offre</th>
                <th style="padding:10px 12px;text-align:center;font-size:.82rem;color:#475569;font-weight:600;
                           border-bottom:1px solid #e2e8f0;width:80px;">Match</th>
              </tr>
              <tr>
                <td style="padding:12px;">
                  <a href="{detail_url}" style="color:#2563eb;text-decoration:none;font-weight:600;font-size:.95rem;">
                    {safe_title}
                  </a>
                  <div style="color:#64748b;font-size:.82rem;margin-top:4px;">
                    {safe_company} &middot; {safe_location}
                  </div>
                </td>
                <td style="padding:12px;text-align:center;">
                  <span style="display:inline-block;background:{score_bg};color:{score_fg};
                               padding:4px 12px;border-radius:12px;font-size:.88rem;font-weight:700;">
                    {score:.0f}%
                  </span>
                </td>
              </tr>
            </table>
            <table cellpadding="0" cellspacing="0" width="100%" style="margin-bottom:24px;">
              <tr><td align="center">
                <a href="{detail_url}"
                   style="display:inline-block;background:#2563eb;color:#ffffff;
                          text-decoration:none;padding:14px 36px;border-radius:8px;
                          font-size:1rem;font-weight:600;letter-spacing:-.2px;">
                  Voir l\u2019offre &#8594;
                </a>
              </td></tr>
            </table>
            <p style="margin:0;color:#94a3b8;font-size:.82rem;line-height:1.5;">
              Vous recevez cet email car vous avez activ\u00e9 les alertes instantan\u00e9es
              sur MyJobHunter. Vous pouvez les d\u00e9sactiver dans
              <a href="{dashboard_url}" style="color:#64748b;">votre profil</a>.
            </p>
          </td>
        </tr>
        <tr>
          <td style="background:#f8fafc;padding:20px 40px;text-align:center;
                     border-top:1px solid #e2e8f0;">
            <p style="margin:0;color:#94a3b8;font-size:.78rem;">
              &copy; 2026 MyJobHunter &middot; Cet email est automatique, ne pas r\u00e9pondre.
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_instant_alerts(new_offer_ids: list[int]):
    """Send instant alert emails to eligible users for new high-match offers.

    For each eligible user (active, email confirmed, alerts enabled, has CV),
    compute TF-IDF scores against new offers in their domain. Send an alert
    for each offer scoring >= 80%, up to 3 emails/user/day.
    """
    if not new_offer_ids:
        logger.info("[alert] No new offers — skipping instant alerts.")
        return

    from app.services.cv_matcher import CVMatcher
    from app import create_app, mail
    from flask_mail import Message

    app = create_app()
    db = SessionLocal()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        # Eligible users
        users = db.query(User).filter(
            User.is_active.is_(True),
            User.email.isnot(None),
            User.email != "",
            User.email_confirmed.is_(True),
            User.email_alerts.is_(True),
        ).all()

        if not users:
            logger.info("[alert] No eligible users for instant alerts.")
            return

        # Load new offers
        new_offers = db.query(Offer).filter(Offer.id.in_(new_offer_ids)).all()
        if not new_offers:
            return

        # Group new offers by domain_id
        offers_by_domain: dict[int | None, list] = {}
        for o in new_offers:
            offers_by_domain.setdefault(o.domain_id, []).append(o)

        total_sent = 0

        for user in users:
            # Reset daily counter if date changed
            if user.daily_alert_date != today_str:
                user.daily_alert_count = 0
                user.daily_alert_date = today_str

            # Check daily limit
            if user.daily_alert_count >= ALERT_MAX_PER_DAY:
                continue

            # Get new offers for the user's domain
            domain_offers = offers_by_domain.get(user.domain_id, [])
            if not domain_offers:
                continue

            # Extract CV text
            cv_text = _find_cv_text_for_user(user.id)
            if not cv_text or not cv_text.strip():
                continue

            # Score offers against CV
            try:
                matcher = CVMatcher(cv_text)
                scores = matcher.score_offers(domain_offers)
            except Exception as exc:
                logger.warning(f"[alert] CV matching failed for user {user.username}: {exc}")
                continue

            # Find offers above threshold, sorted by score desc
            high_matches = sorted(
                [(oid, sc) for oid, sc in scores.items() if sc >= ALERT_MIN_SCORE],
                key=lambda x: x[1],
                reverse=True,
            )

            if not high_matches:
                continue

            # Build offer lookup
            offer_map = {o.id: o for o in domain_offers}

            remaining = ALERT_MAX_PER_DAY - user.daily_alert_count
            to_send = high_matches[:remaining]

            for offer_id, score in to_send:
                offer = offer_map.get(offer_id)
                if not offer:
                    continue

                html_body = _build_alert_email_html(user.username, offer, score)

                with app.app_context():
                    try:
                        msg = Message(
                            subject=f"MyJobHunter \u2014 Nouvelle offre \u00e0 {score:.0f}% pour vous !",
                            recipients=[user.email],
                            html=html_body,
                        )
                        mail.send(msg)
                        user.daily_alert_count += 1
                        total_sent += 1
                        logger.info(
                            f"[alert] Sent alert to {user.username} ({user.email}): "
                            f"offer #{offer_id} '{offer.title}' at {score:.0f}%"
                        )
                    except Exception as exc:
                        logger.error(f"[alert] Failed to send alert to {user.email}: {exc}")

            # Also store match scores in user_offers for these offers
            for offer_id, score in high_matches:
                existing = db.query(UserOffer).filter(
                    UserOffer.user_id == user.id,
                    UserOffer.offer_id == offer_id,
                ).first()
                if existing:
                    existing.cv_match_score = score
                else:
                    db.add(UserOffer(
                        user_id=user.id,
                        offer_id=offer_id,
                        cv_match_score=score,
                    ))

        db.commit()
        logger.info(f"[alert] Instant alerts done: {total_sent} email(s) sent.")

    except Exception:
        db.rollback()
        logger.exception("[alert] Error during instant alerts.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
