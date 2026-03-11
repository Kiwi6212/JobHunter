"""
Dead link checker for JobHunter offers.
Verifies offer URLs and marks inactive offers (404, 410, connection refused).
Only checks offers from the last 30 days to limit request volume.

Usage:
    python scripts/check_dead_links.py

Recommended cron (Sunday 3:00 UTC):
    0 3 * * 0 cd /home/ubuntu/JobHunter && /home/ubuntu/JobHunter/venv/bin/python scripts/check_dead_links.py >> /home/ubuntu/logs/dead_links.log 2>&1
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone

import requests

# Add project root to Python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.database import SessionLocal, init_db
from app.models import Offer

from config import LOG_LEVEL

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


def check_dead_links() -> dict:
    """
    Check offer URLs for dead links and mark them inactive.

    Returns a dict with counts: checked, deactivated, errors, already_inactive.
    """
    db = SessionLocal()
    stats = {"checked": 0, "deactivated": 0, "errors": 0, "already_inactive": 0}

    try:
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
                # Timeout is not a dead link — skip without deactivating
                stats["errors"] += 1
                logger.warning(
                    f"[dead-links] Timeout for offer #{offer.id}: {offer.url}"
                )
            except requests.exceptions.RequestException as e:
                stats["errors"] += 1
                logger.warning(
                    f"[dead-links] Error checking offer #{offer.id}: {e}"
                )

            # Commit in batches of 50 to avoid long transactions
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
    print(f"  Checked:      {results['checked']}")
    print(f"  Deactivated:  {results['deactivated']}")
    print(f"  Errors:       {results['errors']}")
