"""
Manual scraper execution script for JobHunter.
Runs all configured scrapers, filters results, and saves to database.

Usage:
    python scripts/run_scrapers.py
"""

import sys
import logging
from pathlib import Path
from datetime import datetime

# Add project root to Python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.database import SessionLocal, init_db
from app.models import Offer, Tracking
from app.scrapers.lba import LaBonneAlternanceScraper
from app.services.filter_engine import FilterEngine
from config import LOG_LEVEL

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def save_offers_to_db(offers):
    """
    Save filtered offers to the database.
    Skips duplicates based on URL or external_id.

    Args:
        offers: list[dict] - Filtered offer dictionaries

    Returns:
        tuple: (new_count, duplicate_count)
    """
    db = SessionLocal()
    new_count = 0
    duplicate_count = 0

    try:
        for offer_data in offers:
            # Check for duplicates by URL
            existing = db.query(Offer).filter(Offer.url == offer_data["url"]).first()
            if existing:
                duplicate_count += 1
                continue

            # Check for duplicates by external_id
            if offer_data.get("external_id"):
                existing = db.query(Offer).filter(
                    Offer.external_id == offer_data["external_id"]
                ).first()
                if existing:
                    duplicate_count += 1
                    continue

            # Create new offer
            new_offer = Offer(
                title=offer_data["title"],
                company=offer_data["company"],
                location=offer_data.get("location"),
                contract_type=offer_data.get("contract_type"),
                description=offer_data.get("description"),
                url=offer_data["url"],
                source=offer_data["source"],
                external_id=offer_data.get("external_id"),
                posted_date=offer_data.get("posted_date"),
                relevance_score=offer_data.get("relevance_score", 0.0),
                offer_type=offer_data.get("offer_type", "job"),
                found_date=datetime.utcnow(),
            )

            db.add(new_offer)

            # Create initial tracking entry
            db.flush()  # Get the offer ID
            tracking = Tracking(
                offer_id=new_offer.id,
                status="New",
            )
            db.add(tracking)

            new_count += 1

        db.commit()
        logger.info(f"[db] Saved {new_count} new offers, {duplicate_count} duplicates skipped")

    except Exception as e:
        db.rollback()
        logger.error(f"[db] Error saving offers: {e}", exc_info=True)
    finally:
        db.close()

    return new_count, duplicate_count


def main():
    """Main entry point for scraper execution."""
    print("=" * 60)
    print("JobHunter - Scraper Runner")
    print("=" * 60)
    print()

    # Ensure database exists
    init_db()
    print()

    # Initialize scrapers
    scrapers = [
        LaBonneAlternanceScraper(),
        # FranceTravailScraper(),  # TODO: Add when API keys available
        # WTTJScraper(),           # TODO: Phase 4
        # IndeedScraper(),         # TODO: Phase 4
    ]

    # Collect from all sources
    all_raw_offers = []
    for scraper in scrapers:
        logger.info(f"Running scraper: {scraper.source_name}")
        offers = scraper.run()
        all_raw_offers.extend(offers)
        logger.info(f"  -> {len(offers)} raw offers collected")

    print(f"\n[+] Total raw offers collected: {len(all_raw_offers)}")

    if not all_raw_offers:
        print("[!] No offers collected. Check your API keys in .env")
        return

    # Filter offers
    filter_engine = FilterEngine()
    filtered_offers = filter_engine.filter_offers(all_raw_offers)

    print(f"[+] After filtering: {len(filtered_offers)} offers")

    if not filtered_offers:
        print("[!] No offers passed the filters.")
        print("    Tip: Check keywords and location settings in config.py")
        return

    # Show top 5 offers
    print(f"\n{'='*60}")
    print("Top 5 offers by relevance:")
    print(f"{'='*60}")
    for i, offer in enumerate(filtered_offers[:5], 1):
        print(f"\n  {i}. {offer['title']}")
        print(f"     Company:   {offer['company']}")
        print(f"     Location:  {offer.get('location', 'N/A')}")
        print(f"     Source:    {offer['source']}")
        print(f"     Score:     {offer.get('relevance_score', 0):.0f}/100")

    # Save to database
    print(f"\n{'='*60}")
    print("Saving to database...")
    new_count, dup_count = save_offers_to_db(filtered_offers)

    print(f"\n{'='*60}")
    print(f"[OK] Done! {new_count} new offers saved, {dup_count} duplicates skipped")
    print(f"[OK] Launch dashboard: python run.py")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
