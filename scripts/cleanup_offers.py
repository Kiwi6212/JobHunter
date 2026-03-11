"""
Deduplication script for JobHunter offers.
Detects and removes duplicate offers using fuzzy matching on normalized
title + company. Handles cross-source duplicates (e.g. 'SOPRA STERIA GROUP'
vs 'Sopra Steria', titles with 'H/F' suffixes, accents, etc.).

When duplicates span multiple sources, the offer from the highest-priority
source is kept (career sites > aggregators).

Usage:
    python scripts/cleanup_offers.py
"""

import re
import sys
import logging
import unicodedata
from pathlib import Path
from collections import defaultdict

# Add project root to Python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.database import SessionLocal, init_db
from app.models import Offer, UserOffer, Tracking

from config import LOG_LEVEL

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Source priority (lower = higher priority) ─────────────────────────────
# Direct career sites are most reliable, then specialized boards, then aggregators.
SOURCE_PRIORITY = {
    "safran": 0,
    "bpce": 0,
    "smartrecruiters": 1,
    "workday": 2,
    "france_travail": 3,
    "la_bonne_alternance": 4,
    "welcome_to_the_jungle": 5,
    "indeed": 6,
    "lever": 7,
    "talentbrew": 8,
    "phenom": 9,
    "place_emploi_public": 10,
}

# Words to strip from company names before comparison
# Applied AFTER special chars are removed, so 'S.A.' becomes 'sa' first
_COMPANY_NOISE = re.compile(
    r"\b(group|groupe|france|sas|sa|sarl|eurl|inc|ltd|gmbh|se)\b",
    re.IGNORECASE,
)

# Title suffixes to remove (gender markers, etc.)
_TITLE_SUFFIXES = re.compile(
    r"\s*[-–—/]\s*[HFMhfm]\s*/\s*[HFMhfm]"  # - H/F, – F/H, / M/F …
    r"|\s*\(\s*[HFMhfm]\s*/\s*[HFMhfm]\s*\)"  # (H/F), (F/H), (M/F) …
    r"|\s*[HFhf]\s*/\s*[HFhf]\s*$",            # trailing H/F without parens
)

# Collapse multiple whitespace / special chars
_MULTI_SPACE = re.compile(r"\s+")
_SPECIAL_CHARS = re.compile(r"[^\w\s]", re.UNICODE)


def _strip_accents(text: str) -> str:
    """Remove diacritics: é→e, è→e, ü→u, etc."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_company(raw: str) -> str:
    """Normalize a company name for duplicate comparison.

    'SOPRA STERIA GROUP' → 'sopra steria'
    'Sopra Steria'       → 'sopra steria'
    'Thales S.A.'        → 'thales'
    """
    s = raw.strip().lower()
    s = _strip_accents(s)
    # Remove dots/special before noise removal so 'S.A.S' → 'sas', 'S.A.' → 'sa'
    s = re.sub(r"\.(?=\S)", "", s)       # Remove dots between chars: S.A. → SA.
    s = _SPECIAL_CHARS.sub(" ", s)
    s = _COMPANY_NOISE.sub("", s)
    # Remove isolated single-letter fragments (leftover from e.g. 'S. A.')
    s = re.sub(r"\b[a-z]\b", "", s)
    s = _MULTI_SPACE.sub(" ", s).strip()
    return s


def normalize_title(raw: str) -> str:
    """Normalize a job title for duplicate comparison.

    'Administrateur Systèmes (H/F)'  → 'administrateur systemes'
    'Admin Systèmes - H/F'           → 'admin systemes'
    """
    s = raw.strip()
    s = _TITLE_SUFFIXES.sub("", s)
    s = s.lower()
    s = _strip_accents(s)
    s = _SPECIAL_CHARS.sub(" ", s)
    s = _MULTI_SPACE.sub(" ", s).strip()
    return s


def _source_priority(source: str) -> int:
    """Return priority rank for a source (lower = better)."""
    return SOURCE_PRIORITY.get(source, 99)


def cleanup_duplicate_offers() -> int:
    """
    Find and remove duplicate offers using normalized title + company.
    When duplicates come from different sources, keeps the highest-priority source.
    Migrates user_offers from removed offers to the kept offer.

    Returns the number of duplicates removed.
    """
    db = SessionLocal()
    total_removed = 0

    try:
        # Load all offers into memory for Python-side normalization
        all_offers = db.query(Offer).all()
        logger.info(f"[dedup] Loaded {len(all_offers)} offer(s) for deduplication.")

        # Group by (normalized_title, normalized_company)
        groups: dict[tuple[str, str], list[Offer]] = defaultdict(list)
        for offer in all_offers:
            key = (normalize_title(offer.title), normalize_company(offer.company))
            groups[key].append(offer)

        # Process groups with more than one offer
        dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
        if not dup_groups:
            logger.info("[dedup] No duplicate offers found.")
            return 0

        logger.info(f"[dedup] Found {len(dup_groups)} duplicate group(s) to process.")

        for (norm_title, norm_company), group in dup_groups.items():
            # Sort: best source priority first, then most recent found_date, then highest id
            group.sort(
                key=lambda o: (
                    _source_priority(o.source),
                    -(o.found_date.timestamp() if o.found_date else 0),
                    -o.id,
                )
            )

            keeper = group[0]
            duplicates = group[1:]

            # Collect existing user_offer user_ids for the keeper
            existing_user_ids = {
                row[0]
                for row in db.query(UserOffer.user_id)
                .filter(UserOffer.offer_id == keeper.id)
                .all()
            }

            for dup in duplicates:
                # Migrate user_offers from duplicate to keeper
                dup_user_offers = (
                    db.query(UserOffer)
                    .filter(UserOffer.offer_id == dup.id)
                    .all()
                )
                for uo in dup_user_offers:
                    if uo.user_id not in existing_user_ids:
                        uo.offer_id = keeper.id
                        existing_user_ids.add(uo.user_id)
                    else:
                        db.delete(uo)

                # Delete tracking entries for the duplicate
                for t in db.query(Tracking).filter(Tracking.offer_id == dup.id).all():
                    db.delete(t)

                logger.debug(
                    f"[dedup] Removing #{dup.id} ({dup.source}) "
                    f"→ keeping #{keeper.id} ({keeper.source}) "
                    f"| '{norm_title}' @ '{norm_company}'"
                )

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
