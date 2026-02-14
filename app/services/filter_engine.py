"""
Filter engine for JobHunter.
Filters and scores job offers based on keywords, location, contract type,
and target company matching.
"""

import logging
import re
import unicodedata
from datetime import datetime

from config import KEYWORDS, FILTERS, TARGET_COMPANIES

logger = logging.getLogger(__name__)

# Sources that are already pre-filtered by relevance criteria (e.g. ROME codes).
# These bypass the keyword filter and only go through location filtering.
PREFILTERED_SOURCES = {"la_bonne_alternance"}

# Accent mapping for French characters
ACCENT_MAP = str.maketrans(
    "àâäéèêëïîôùûüÿçœæÀÂÄÉÈÊËÏÎÔÙÛÜŸÇŒÆ",
    "aaaeeeeiioouuycoeAAAEEEEIIOOUUYCOE",
)


def normalize_text(text):
    """Remove accents and normalize text for matching."""
    return text.lower().translate(ACCENT_MAP)


class FilterEngine:
    """
    Filters and scores job offers based on configured criteria.

    Filtering steps:
        1. Keyword matching (title + description) with accent-insensitive search
        2. Location filtering (Ile-de-France departments)
        3. Contract type filtering (alternance)
        4. Relevance scoring (keyword density + target company bonus)
    """

    def __init__(self):
        self.keywords = [kw.lower() for kw in KEYWORDS]
        self.filters = FILTERS
        self.target_companies = [normalize_text(c) for c in TARGET_COMPANIES]

        # Departments that are part of Ile-de-France
        self.idf_departments = set(FILTERS.get("departments", []))

        # Pre-compile keyword patterns WITH accent-normalized versions
        # This matches both "systèmes" and "systemes"
        self.keyword_patterns = []
        for kw in KEYWORDS:
            # Original pattern (with accents)
            self.keyword_patterns.append(re.compile(re.escape(kw), re.IGNORECASE))
            # Normalized pattern (without accents)
            normalized = normalize_text(kw)
            if normalized != kw.lower():
                self.keyword_patterns.append(
                    re.compile(re.escape(normalized), re.IGNORECASE)
                )

    def filter_offers(self, offers):
        """
        Apply all filters to a list of raw offers.

        Args:
            offers: list[dict] - Raw offers from scrapers

        Returns:
            list[dict]: Filtered and scored offers, sorted by relevance
        """
        logger.info(f"[filter] Processing {len(offers)} raw offers...")

        filtered = []
        rejected_count = 0

        for offer in offers:
            # Skip offers without URL (can't track them)
            if not offer.get("url"):
                rejected_count += 1
                continue

            # Apply filters
            if not self._passes_filters(offer):
                rejected_count += 1
                continue

            # Calculate relevance score
            offer["relevance_score"] = self._calculate_score(offer)
            filtered.append(offer)

        # Sort by relevance score (highest first)
        filtered.sort(key=lambda o: o.get("relevance_score", 0), reverse=True)

        logger.info(
            f"[filter] Results: {len(filtered)} accepted, "
            f"{rejected_count} rejected"
        )

        return filtered

    def _passes_filters(self, offer):
        """
        Check if an offer passes all configured filters.

        Returns True if the offer should be kept, False if rejected.
        """
        source = offer.get("source", "")

        # Sources pre-filtered by ROME codes skip keyword matching
        if source not in PREFILTERED_SOURCES:
            if not self._matches_keywords(offer):
                return False

        # Check location (if location data is available)
        if offer.get("location") and not self._matches_location(offer):
            return False

        return True

    def _matches_keywords(self, offer):
        """
        Check if at least one keyword matches the offer title or description.
        Searches both original text and accent-normalized text.

        Returns True if any keyword is found.
        """
        title = offer.get("title") or ""
        description = offer.get("description") or ""

        # Search both original and accent-normalized text
        text = f"{title} {description}".lower()
        text_normalized = normalize_text(f"{title} {description}")

        for pattern in self.keyword_patterns:
            if pattern.search(text) or pattern.search(text_normalized):
                return True

        return False

    def _matches_location(self, offer):
        """
        Check if the offer location is in Ile-de-France.

        Uses department numbers extracted from the address.
        If no department can be extracted, the offer is kept (no false negative).
        """
        location = (offer.get("location") or "").strip()

        if not location:
            return True  # No location data, keep the offer

        # Try to extract department number from postal code
        # Match 5-digit French postal code (e.g., 75001, 92100)
        postal_match = re.search(r'\b(\d{5})\b', location)
        if postal_match:
            postal_code = postal_match.group(1)
            department = postal_code[:2]

            # Handle Corsica (2A, 2B)
            if department == "20":
                return False  # Corsica is not IDF

            if department in self.idf_departments:
                return True
            else:
                return False

        # Check for IDF department names or common identifiers
        idf_indicators = [
            "paris", "ile-de-france", "ile de france", "idf",
            "hauts-de-seine", "seine-saint-denis", "val-de-marne",
            "val-d'oise", "yvelines", "essonne", "seine-et-marne",
        ]

        location_lower = location.lower()
        for indicator in idf_indicators:
            if indicator in location_lower:
                return True

        # If we can't determine the location, keep the offer
        return True

    def _calculate_score(self, offer):
        """
        Calculate a relevance score for the offer (0-100).

        Scoring criteria:
            - Keyword matches in title: +15 per keyword (max 45)
            - Keyword matches in description: +5 per keyword (max 20)
            - Target company match: +30 (partial, case/accent insensitive)
            - Has description: +5
            - Has posted date: +5
        """
        score = 0.0
        title = (offer.get("title") or "").lower()
        title_norm = normalize_text(offer.get("title") or "")
        description = (offer.get("description") or "").lower()
        desc_norm = normalize_text(offer.get("description") or "")
        company = (offer.get("company") or "").lower()

        # Keyword matches in title (high value)
        title_matches = 0
        for pattern in self.keyword_patterns:
            if pattern.search(title) or pattern.search(title_norm):
                title_matches += 1
        # Divide by 2 to avoid double-counting accented + non-accented patterns
        title_matches = (title_matches + 1) // 2
        score += min(title_matches * 15, 45)

        # Keyword matches in description (lower value)
        desc_matches = 0
        for pattern in self.keyword_patterns:
            if pattern.search(description) or pattern.search(desc_norm):
                desc_matches += 1
        desc_matches = (desc_matches + 1) // 2
        score += min(desc_matches * 5, 20)

        # Target company bonus (partial, accent-insensitive)
        company_norm = normalize_text(offer.get("company") or "")
        for target in self.target_companies:
            if target in company_norm:
                score += 30
                break

        # Completeness bonuses
        if description:
            score += 5
        if offer.get("posted_date"):
            score += 5

        return min(score, 100.0)

    def score_offer(self, offer):
        """
        Calculate and return the relevance score for a single offer.
        Useful for rescoring offers without re-filtering.
        """
        return self._calculate_score(offer)
