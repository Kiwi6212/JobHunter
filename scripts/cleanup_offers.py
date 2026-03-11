"""
Deduplication script for JobHunter offers.
Detects and removes duplicate offers (same title + company, case-insensitive, trimmed).
Keeps the most recent offer (by found_date) and migrates user_offers from duplicates.

Usage:
    python scripts/cleanup_offers.py
"""

import sys
import logging
from pathlib import Path
from collections import defaultdict

# Add project root to Python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import func, text
from app.database import SessionLocal, init_db
from app.models import Offer, UserOffer, Tracking

from config import LOG_LEVEL

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def cleanup_duplicate_offers() -> int:
    """
    Find and remove duplicate offers (same title + company, case-insensitive).
    Keeps the offer with the most recent found_date.
    Migrates user_offers and tracking from duplicates to the kept offer.

    Returns the number of duplicates removed.
    """
    db = SessionLocal()
    total_removed = 0

    try:
        # Find duplicate groups: same (lower(trim(title)), lower(trim(company)))
        dupes = (
            db.query(
                func.lower(func.trim(Offer.title)).label("norm_title"),
                func.lower(func.trim(Offer.company)).label("norm_company"),
                func.count(Offer.id).label("cnt"),
            )
            .group_by(
                func.lower(func.trim(Offer.title)),
                func.lower(func.trim(Offer.company)),
            )
            .having(func.count(Offer.id) > 1)
            .all()
        )

        if not dupes:
            logger.info("[dedup] No duplicate offers found.")
            return 0

        logger.info(f"[dedup] Found {len(dupes)} duplicate group(s) to process.")

        for norm_title, norm_company, cnt in dupes:
            # Get all offers in this group, ordered by found_date descending
            group = (
                db.query(Offer)
                .filter(
                    func.lower(func.trim(Offer.title)) == norm_title,
                    func.lower(func.trim(Offer.company)) == norm_company,
                )
                .order_by(Offer.found_date.desc(), Offer.id.desc())
                .all()
            )

            if len(group) < 2:
                continue

            # Keep the first (most recent found_date)
            keeper = group[0]
            duplicates = group[1:]

            # Get existing user_offer (user_id, offer_id) pairs for the keeper
            existing_uo = set(
                db.query(UserOffer.user_id)
                .filter(UserOffer.offer_id == keeper.id)
                .all()
            )
            existing_user_ids = {row[0] for row in existing_uo}

            for dup in duplicates:
                # Migrate user_offers from duplicate to keeper
                dup_user_offers = (
                    db.query(UserOffer)
                    .filter(UserOffer.offer_id == dup.id)
                    .all()
                )
                for uo in dup_user_offers:
                    if uo.user_id not in existing_user_ids:
                        # Re-point to keeper
                        uo.offer_id = keeper.id
                        existing_user_ids.add(uo.user_id)
                    else:
                        # Already exists for keeper — delete the duplicate user_offer
                        db.delete(uo)

                # Delete tracking entries for the duplicate
                dup_tracking = (
                    db.query(Tracking)
                    .filter(Tracking.offer_id == dup.id)
                    .all()
                )
                for t in dup_tracking:
                    db.delete(t)

                # Delete the duplicate offer
                db.delete(dup)
                total_removed += 1

        db.commit()
        logger.info(f"[dedup] Removed {total_removed} duplicate offer(s).")

    except Exception as e:
        db.rollback()
        logger.error(f"[dedup] Error during deduplication: {e}", exc_info=True)
    finally:
        db.close()

    return total_removed


if __name__ == "__main__":
    init_db()
    removed = cleanup_duplicate_offers()
    print(f"[dedup] Done. {removed} duplicate(s) removed.")
