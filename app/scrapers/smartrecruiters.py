"""
Scraper for SmartRecruiters public API.
Fetches apprenticeship/alternance offers from target companies that use
SmartRecruiters as their ATS (Applicant Tracking System).

API docs: https://dev.smartrecruiters.com/customer-api/posting-api/
Endpoint: GET /v1/companies/{companyId}/postings?q=&limit=100
"""

import logging
from datetime import datetime

import requests

from app.scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

API_BASE = "https://api.smartrecruiters.com/v1/companies"
JOB_BASE = "https://jobs.smartrecruiters.com"

# Target companies on SmartRecruiters: (companyId slug, display name)
COMPANIES = [
    ("SopraSteria1", "Sopra Steria"),
    ("Devoteam", "Devoteam"),
    ("Alten", "Alten"),
]

# Search queries to find alternance/apprenticeship offers
SEARCH_QUERIES = [
    "alternance",
    "apprentissage",
    "alternance système",
    "alternance réseau",
    "alternance infrastructure",
    "alternance DevOps",
    "alternance support informatique",
]

# Île-de-France region names and department prefixes for filtering
IDF_INDICATORS = {
    "idf", "ile-de-france", "île-de-france",
    "paris", "hauts-de-seine", "seine-saint-denis", "val-de-marne",
    "yvelines", "essonne", "seine-et-marne", "val-d'oise",
}
IDF_POSTAL_PREFIXES = {"75", "77", "78", "91", "92", "93", "94", "95"}


class SmartRecruitersScraper(BaseScraper):
    """
    Scraper for SmartRecruiters public postings API.

    Searches multiple target companies for alternance offers in Île-de-France.
    Uses the public API (no authentication required).
    """

    @property
    def source_name(self):
        return "smartrecruiters"

    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": self.config.USER_AGENT,
        })

    def collect(self):
        """
        Collect alternance offers from all configured SmartRecruiters companies.

        Returns:
            list[dict]: Normalized offer dictionaries.
        """
        all_offers = []

        for company_id, company_name in COMPANIES:
            logger.info(f"[smartrecruiters] Searching {company_name} ({company_id})")
            offers = self._search_company(company_id, company_name)
            all_offers.extend(offers)
            self._delay()

        # Deduplicate by external_id
        seen_ids = set()
        unique_offers = []
        for offer in all_offers:
            eid = offer.get("external_id")
            if eid and eid in seen_ids:
                continue
            if eid:
                seen_ids.add(eid)
            unique_offers.append(offer)

        logger.info(
            f"[smartrecruiters] Total unique offers: {len(unique_offers)} "
            f"(from {len(all_offers)} raw results)"
        )

        return unique_offers

    def _search_company(self, company_id, company_name):
        """Search a single company for alternance offers."""
        all_postings = []

        for query in SEARCH_QUERIES:
            postings = self._fetch_postings(company_id, query)
            all_postings.extend(postings)
            self._delay()

        # Deduplicate within this company
        seen = set()
        unique = []
        for p in all_postings:
            pid = p.get("id")
            if pid in seen:
                continue
            seen.add(pid)
            unique.append(p)

        # Filter for IDF location and parse
        offers = []
        for posting in unique:
            if not self._is_idf(posting):
                continue
            offer = self._parse_posting(posting, company_name)
            if offer:
                offers.append(offer)

        logger.info(
            f"[smartrecruiters] [{company_name}] {len(offers)} IDF offers "
            f"(from {len(unique)} unique postings)"
        )

        return offers

    def _fetch_postings(self, company_id, query):
        """Fetch postings from the SmartRecruiters API."""
        postings = []
        offset = 0
        limit = 100

        while True:
            url = f"{API_BASE}/{company_id}/postings"
            params = {"q": query, "limit": limit, "offset": offset}

            try:
                response = self.session.get(
                    url, params=params, timeout=self.config.TIMEOUT
                )

                if response.status_code != 200:
                    logger.warning(
                        f"[smartrecruiters] HTTP {response.status_code} "
                        f"for {company_id} q='{query}'"
                    )
                    break

                data = response.json()
                content = data.get("content", [])
                total = data.get("totalFound", 0)

                postings.extend(content)

                if len(postings) >= total or not content:
                    break

                offset += limit

            except requests.exceptions.RequestException as e:
                logger.error(f"[smartrecruiters] Request error: {e}")
                break

        return postings

    def _is_idf(self, posting):
        """Check if a posting is located in Île-de-France."""
        location = posting.get("location", {})
        country = (location.get("country") or "").lower()

        # Must be in France
        if country and country != "fr":
            return False

        # Check postal code
        postal = location.get("postalCode", "")
        if postal and postal[:2] in IDF_POSTAL_PREFIXES:
            return True

        # Check region name
        region = (location.get("region") or "").lower()
        if region:
            for indicator in IDF_INDICATORS:
                if indicator in region:
                    return True

        # Check city name
        city = (location.get("city") or "").lower()
        if city in ("paris", "levallois-perret", "bezons", "nanterre",
                     "boulogne-billancourt", "puteaux", "la défense",
                     "courbevoie", "issy-les-moulineaux", "saint-denis"):
            return True

        # No location data — keep it (avoid false negatives)
        if not region and not postal and not city:
            return True

        return False

    def _parse_posting(self, posting, company_name):
        """Parse a SmartRecruiters posting into a normalized offer dict."""
        try:
            title = posting.get("name", "Unknown Title")
            posting_id = posting.get("id", "")
            company_id = posting.get("company", {}).get("identifier", "")

            # Location
            loc = posting.get("location", {})
            city = loc.get("city", "")
            region = loc.get("region", "")
            postal = loc.get("postalCode", "")
            location_parts = [p for p in [city, postal, region] if p]
            location = ", ".join(location_parts) if location_parts else None

            # URL
            url = f"{JOB_BASE}/{company_id}/{posting_id}"

            # Posted date
            posted_date = None
            released = posting.get("releasedDate")
            if released:
                try:
                    posted_date = datetime.fromisoformat(
                        released.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    pass

            # Contract type from customField
            contract_type = "Alternance"
            for cf in posting.get("customField", []):
                label = (cf.get("fieldLabel") or "").lower()
                if "contract" in label or "contrat" in label:
                    contract_type = cf.get("valueLabel", contract_type)
                    break

            # Department as description
            dept = posting.get("department", {}).get("label", "")
            func = posting.get("function", {}).get("label", "")
            desc_parts = [p for p in [dept, func] if p]
            description = " - ".join(desc_parts) if desc_parts else None

            return self._normalize_offer(
                title=title,
                company=company_name,
                location=location,
                contract_type=contract_type,
                description=description,
                url=url,
                external_id=f"sr_{posting_id}",
                posted_date=posted_date,
            )

        except Exception as e:
            logger.warning(f"[smartrecruiters] Error parsing posting: {e}")
            return None
