"""
Dead link checker for JobHunter offers.
Verifies offer URLs and marks inactive offers (404, 410, connection refused).
Only checks offers from the last 30 days to limit request volume.

France Travail offers are checked via the official API (not HEAD requests)
because the candidat.francetravail.fr website blocks server connections.

Usage:
    python scripts/check_dead_links.py

Recommended cron (Sunday 3:00 UTC):
    0 3 * * 0 cd /home/ubuntu/JobHunter && /home/ubuntu/JobHunter/venv/bin/python scripts/check_dead_links.py >> /home/ubuntu/logs/dead_links.log 2>&1
"""

import re
import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests

# Add project root to Python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.database import SessionLocal, init_db
from app.models import Offer

from config import LOG_LEVEL, APIKeys

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# HTTP status codes that indicate a dead/expired link
DEAD_STATUSES = {404, 410}
REQUEST_TIMEOUT = 10
MAX_REDIRECTS = 3

# France Travail API
FT_TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
FT_OFFER_API_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/{}"
FT_SCOPE = "api_offresdemploiv2 o2dsoffre"
FT_URL_PATTERN = re.compile(r"candidat\.francetravail\.fr/offres/recherche/detail/(\w+)")

# Domains known to block server-side requests (HEAD/GET).
# Offers from these domains are skipped entirely.
SKIP_DOMAINS: list[str] = []


def _get_ft_token() -> str | None:
    """Obtain an OAuth2 Bearer token for the France Travail API."""
    client_id = APIKeys.FRANCE_TRAVAIL_CLIENT_ID
    client_secret = APIKeys.FRANCE_TRAVAIL_CLIENT_SECRET
    if not client_id or not client_secret:
        logger.warning("[dead-links] France Travail credentials not configured, skipping API checks.")
        return None
    try:
        resp = requests.post(
            FT_TOKEN_URL,
            params={"realm": "/partenaire"},
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": FT_SCOPE,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        resp.raise_for_status()
        token = resp.json()["access_token"]
        logger.info("[dead-links] France Travail OAuth2 token obtained.")
        return token
    except Exception as e:
        logger.error(f"[dead-links] Failed to obtain France Travail token: {e}")
        return None


def _extract_ft_offer_id(url: str) -> str | None:
    """Extract the offer ID from a France Travail candidate URL."""
    match = FT_URL_PATTERN.search(url)
    return match.group(1) if match else None


def _is_skipped_domain(url: str) -> bool:
    """Check if the URL belongs to a domain in the SKIP_DOMAINS list."""
    if not SKIP_DOMAINS:
        return False
    try:
        hostname = urlparse(url).hostname or ""
        return any(hostname == d or hostname.endswith(f".{d}") for d in SKIP_DOMAINS)
    except Exception:
        return False


def _reactivate_ft_offers(db) -> int:
    """
    Reactivate France Travail offers that were wrongly deactivated
    by previous HEAD-based checks.
    """
    wrongly_deactivated = (
        db.query(Offer)
        .filter(
            Offer.is_active == False,
            Offer.url.like("%candidat.francetravail.fr%"),
            Offer.source == "france_travail",
        )
        .all()
    )
    count = len(wrongly_deactivated)
    if count:
        for offer in wrongly_deactivated:
            offer.is_active = True
        db.commit()
        logger.info(f"[dead-links] Reactivated {count} France Travail offer(s) previously deactivated by mistake.")
    return count


def check_dead_links() -> dict:
    """
    Check offer URLs for dead links and mark them inactive.

    Returns a dict with counts: checked, deactivated, errors, already_inactive, skipped, reactivated.
    """
    db = SessionLocal()
    stats = {"checked": 0, "deactivated": 0, "errors": 0, "skipped": 0, "reactivated": 0}

    try:
        # Step 1: Reactivate wrongly deactivated France Travail offers
        stats["reactivated"] = _reactivate_ft_offers(db)

        # Step 2: Obtain France Travail API token
        ft_token = _get_ft_token()

        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        offers = (
            db.query(Offer)
            .filter(Offer.is_active == True, Offer.found_date >= cutoff)
            .all()
        )

        logger.info(f"[dead-links] Checking {len(offers)} active offer(s) from the last 30 days.")

        session = requests.Session()
        session.max_redirects = MAX_REDIRECTS
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        })

        for offer in offers:
            stats["checked"] += 1

            # Skip domains known to block server requests
            if _is_skipped_domain(offer.url):
                stats["skipped"] += 1
                continue

            # France Travail: check via API instead of HEAD request
            ft_offer_id = _extract_ft_offer_id(offer.url)
            if ft_offer_id:
                if not ft_token:
                    stats["skipped"] += 1
                    continue
                try:
                    resp = session.get(
                        FT_OFFER_API_URL.format(ft_offer_id),
                        headers={
                            "Authorization": f"Bearer {ft_token}",
                            "Accept": "application/json",
                        },
                        timeout=REQUEST_TIMEOUT,
                    )
                    if resp.status_code in (204, 404):
                        offer.is_active = False
                        stats["deactivated"] += 1
                        logger.info(
                            f"[dead-links] Deactivated offer #{offer.id} "
                            f"(FT API HTTP {resp.status_code}): {offer.url}"
                        )
                    elif resp.status_code == 200:
                        pass  # Offer is active, nothing to do
                    else:
                        stats["errors"] += 1
                        logger.warning(
                            f"[dead-links] FT API unexpected status {resp.status_code} "
                            f"for offer #{offer.id}: {offer.url}"
                        )
                except requests.exceptions.RequestException as e:
                    stats["errors"] += 1
                    logger.warning(
                        f"[dead-links] FT API error for offer #{offer.id}: {e}"
                    )
                # Commit in batches of 50
                if stats["checked"] % 50 == 0:
                    db.commit()
                continue

            # Other sources: HEAD request
            try:
                resp = session.head(
                    offer.url,
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=True,
                )
                if resp.status_code in DEAD_STATUSES:
                    offer.is_active = False
                    stats["deactivated"] += 1
                    logger.info(
                        f"[dead-links] Deactivated offer #{offer.id} "
                        f"(HTTP {resp.status_code}): {offer.url}"
                    )
            except requests.exceptions.TooManyRedirects:
                offer.is_active = False
                stats["deactivated"] += 1
                logger.info(
                    f"[dead-links] Deactivated offer #{offer.id} "
                    f"(too many redirects): {offer.url}"
                )
            except requests.exceptions.ConnectionError:
                offer.is_active = False
                stats["deactivated"] += 1
                logger.info(
                    f"[dead-links] Deactivated offer #{offer.id} "
                    f"(connection refused): {offer.url}"
                )
            except requests.exceptions.Timeout:
                stats["errors"] += 1
                logger.warning(
                    f"[dead-links] Timeout for offer #{offer.id}: {offer.url}"
                )
            except requests.exceptions.RequestException as e:
                stats["errors"] += 1
                logger.warning(
                    f"[dead-links] Error checking offer #{offer.id}: {e}"
                )

            # Commit in batches of 50
            if stats["checked"] % 50 == 0:
                db.commit()

        db.commit()

    except Exception as e:
        db.rollback()
        logger.error(f"[dead-links] Fatal error: {e}", exc_info=True)
    finally:
        db.close()

    return stats


if __name__ == "__main__":
    init_db()
    results = check_dead_links()
    print(f"\n[dead-links] Results:")
    print(f"  Reactivated:  {results['reactivated']}")
    print(f"  Checked:      {results['checked']}")
    print(f"  Deactivated:  {results['deactivated']}")
    print(f"  Skipped:      {results['skipped']}")
    print(f"  Errors:       {results['errors']}")
