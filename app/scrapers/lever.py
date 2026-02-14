"""
Scraper for Lever public job posting API.
Fetches apprenticeship/alternance offers from companies using Lever as their ATS.

Endpoint: GET https://api.lever.co/v0/postings/{company}?mode=json
"""

import logging
from datetime import datetime

import requests

from app.scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

# Target companies on Lever: (company_slug, display_name)
COMPANIES = [
    ("scaleway", "Scaleway"),
]

# IDF location indicators
IDF_INDICATORS = [
    "paris", "île-de-france", "ile-de-france", "idf",
    "la défense", "la defense",
    "nanterre", "boulogne", "levallois", "puteaux",
    "courbevoie", "issy", "saint-denis", "massy",
    "vélizy", "velizy", "guyancourt", "saclay",
]


class LeverScraper(BaseScraper):
    """
    Scraper for Lever public postings API.

    Fetches all postings for each configured company,
    filters for IDF + alternance/apprentissage.
    """

    @property
    def source_name(self):
        return "lever"

    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": self.config.USER_AGENT,
        })

    def collect(self):
        all_offers = []

        for slug, company_name in COMPANIES:
            logger.info(f"[lever] Searching {company_name} ({slug})")
            offers = self._fetch_company(slug, company_name)
            all_offers.extend(offers)
            self._delay()

        logger.info(f"[lever] Total offers: {len(all_offers)}")
        return all_offers

    def _fetch_company(self, slug, company_name):
        """Fetch and filter postings for a single company."""
        url = f"https://api.lever.co/v0/postings/{slug}?mode=json"

        try:
            response = self.session.get(url, timeout=self.config.TIMEOUT)
            if response.status_code != 200:
                logger.warning(f"[lever] HTTP {response.status_code} for {slug}")
                return []

            postings = response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"[lever] Request error for {slug}: {e}")
            return []

        offers = []
        for posting in postings:
            if not self._is_relevant(posting):
                continue
            offer = self._parse_posting(posting, company_name)
            if offer:
                offers.append(offer)

        logger.info(
            f"[lever] [{company_name}] {len(offers)} IDF alternance offers "
            f"(from {len(postings)} total postings)"
        )
        return offers

    def _is_relevant(self, posting):
        """Check if posting is in IDF and related to alternance."""
        # Check location
        categories = posting.get("categories", {})
        locations = categories.get("allLocations", [])
        location_str = " ".join(locations).lower() if locations else ""
        if not location_str:
            location_str = (categories.get("location") or "").lower()

        is_idf = any(ind in location_str for ind in IDF_INDICATORS)
        if not is_idf:
            return False

        # Check alternance/apprentissage in text, description, or commitment
        searchable = " ".join([
            posting.get("text", ""),
            posting.get("descriptionPlain", ""),
            categories.get("commitment", ""),
        ]).lower()

        return "alternance" in searchable or "apprenti" in searchable

    def _parse_posting(self, posting, company_name):
        """Parse a Lever posting into a normalized offer dict."""
        try:
            categories = posting.get("categories", {})
            locations = categories.get("allLocations", [])
            location = ", ".join(locations) if locations else categories.get("location")

            # Parse createdAt (milliseconds timestamp)
            created_at = posting.get("createdAt")
            posted_date = None
            if created_at:
                posted_date = datetime.utcfromtimestamp(created_at / 1000)

            # Build description from commitment + team
            desc_parts = []
            if categories.get("commitment"):
                desc_parts.append(categories["commitment"])
            if categories.get("team"):
                desc_parts.append(categories["team"])
            if categories.get("department"):
                desc_parts.append(categories["department"])

            return self._normalize_offer(
                title=posting.get("text", "Unknown Title"),
                company=company_name,
                location=location,
                contract_type="Alternance",
                description=" | ".join(desc_parts) if desc_parts else None,
                url=posting.get("hostedUrl", ""),
                external_id=f"lever_{posting.get('id', '')}",
                posted_date=posted_date,
            )

        except Exception as e:
            logger.warning(f"[lever] Error parsing posting: {e}")
            return None
