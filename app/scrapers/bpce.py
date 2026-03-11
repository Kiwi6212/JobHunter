"""
Scraper for BPCE / Natixis job offers via the OpenDataSoft public API.

BPCE publishes all group job offers (including Natixis entities) as open data:
  https://bpce.opendatasoft.com/api/explore/v2.1/catalog/datasets/groupe-bpce-offres-emploi/records

No authentication required. Updated 4x daily. License: Etalab Open Licence v2.0.
"""

import logging
from datetime import datetime

import requests

from app.scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

API_BASE = (
    "https://bpce.opendatasoft.com/api/explore/v2.1"
    "/catalog/datasets/groupe-bpce-offres-emploi/records"
)

# Organizations to scrape (Natixis entities + optionally others)
# Use `like` operator for partial matching across all Natixis sub-entities.
TARGET_ORGANIZATIONS = [
    "Natixis",
]

# Search queries — patched by run_scrapers.py per domain
SEARCH_QUERIES = [
    "alternance",
]



class BpceScraper(BaseScraper):
    """
    Scraper for BPCE group jobs via OpenDataSoft public API.

    Fetches Natixis (and other BPCE entities) alternance offers
    across France.
    """

    @property
    def source_name(self):
        return "bpce"

    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": self.config.USER_AGENT,
        })

    def collect(self):
        all_offers = []

        for org in TARGET_ORGANIZATIONS:
            logger.info(f"[bpce] Fetching offers for organization: {org}")
            offers = self._fetch_organization(org)
            all_offers.extend(offers)
            self._delay()

        # Deduplicate by external_id
        seen_ids = set()
        unique = []
        for offer in all_offers:
            eid = offer.get("external_id")
            if eid and eid in seen_ids:
                continue
            if eid:
                seen_ids.add(eid)
            unique.append(offer)

        logger.info(
            f"[bpce] Total unique offers: {len(unique)} "
            f"(from {len(all_offers)} raw)"
        )
        return unique

    def _fetch_organization(self, org_name):
        """Fetch all matching offers for an organization."""
        all_records = []
        offset = 0
        limit = 100

        # Build WHERE clause: organization (nationwide, no state filter)
        where_parts = [
            f'organization like "{org_name}"',
        ]
        where_clause = " AND ".join(where_parts)

        while True:
            params = {
                "limit": limit,
                "offset": offset,
                "where": where_clause,
                "order_by": "lastmodifieddate DESC",
            }

            try:
                response = self.session.get(
                    API_BASE, params=params, timeout=self.config.TIMEOUT
                )

                if response.status_code != 200:
                    logger.warning(
                        f"[bpce] HTTP {response.status_code} for org='{org_name}'"
                    )
                    break

                data = response.json()
                total = data.get("total_count", 0)
                results = data.get("results", [])

                if not results:
                    break

                all_records.extend(results)

                if len(all_records) >= total:
                    break

                offset += limit
                self._delay()

            except requests.exceptions.RequestException as e:
                logger.error(f"[bpce] Request error: {e}")
                break

        # Filter by search queries and parse
        offers = []
        for record in all_records:
            if self._matches_queries(record):
                offer = self._parse_record(record)
                if offer:
                    offers.append(offer)

        logger.info(
            f"[bpce] [{org_name}] {len(offers)} matching offers "
            f"(from {len(all_records)} records)"
        )
        return offers

    def _matches_queries(self, record):
        """Check if a record matches any of the search queries."""
        title = (record.get("title") or "").lower()
        description = (record.get("description") or "").lower()
        job_type = (record.get("jobtype") or "").lower()
        combined = f"{title} {description} {job_type}"

        for query in SEARCH_QUERIES:
            # Each query may have multiple words; all must match
            words = query.lower().split()
            if all(word in combined for word in words):
                return True

        return False

    def _parse_record(self, record):
        """Parse an OpenDataSoft record into a normalized offer dict."""
        try:
            title = record.get("title", "Unknown Title")
            ref_number = record.get("referencenumber", "")

            # URL: prefer the career site URL, fallback to apply_url
            url = record.get("url") or record.get("apply_url") or ""

            # Organization as company name
            organization = record.get("organization", "Natixis")
            # Clean up: "Natixis CIB France" -> keep as is
            company = organization

            # Location
            city = record.get("city", "")
            state = record.get("state", "")
            country = record.get("country", "")
            location_parts = [p for p in [city, state, country] if p]
            location = ", ".join(location_parts) if location_parts else None

            # Contract type
            job_type = record.get("jobtype", "")
            contract_type = self._extract_contract_type(job_type)

            # Description (strip HTML tags for a clean text preview)
            raw_desc = record.get("description", "")
            # Keep first ~500 chars of raw description as summary
            description = self._strip_html(raw_desc)[:500] if raw_desc else None

            # Posted/modified date
            posted_date = self._parse_date(record.get("lastmodifieddate"))

            # Category / industry as extra context
            category = record.get("category", "")
            industry = record.get("jobindustry", "")
            if category or industry:
                extra = " | ".join(p for p in [category, industry] if p)
                if description:
                    description = f"{extra} — {description}"
                else:
                    description = extra

            return self._normalize_offer(
                title=title,
                company=company,
                location=location,
                contract_type=contract_type,
                description=description,
                url=url,
                external_id=f"bpce_{ref_number}" if ref_number else None,
                posted_date=posted_date,
            )

        except Exception as e:
            logger.warning(f"[bpce] Error parsing record: {e}")
            return None

    def _extract_contract_type(self, job_type):
        """Extract the most relevant contract type from the jobtype field."""
        if not job_type:
            return "Alternance"
        jt_lower = job_type.lower()
        if "alternance" in jt_lower:
            return "Alternance"
        if "stage" in jt_lower:
            return "Stage"
        if "cdi" in jt_lower:
            return "CDI"
        if "cdd" in jt_lower:
            return "CDD"
        return job_type

    def _strip_html(self, html_text):
        """Remove HTML tags from a string."""
        import re
        clean = re.sub(r'<[^>]+>', ' ', html_text)
        clean = re.sub(r'\s+', ' ', clean)
        return clean.strip()

    def _parse_date(self, date_str):
        """Parse date from OpenDataSoft format: DD/MM/YYYY H:MM:SS AM/PM."""
        if not date_str:
            return None
        try:
            # Format: "09/03/2026 2:10:10 PM"
            return datetime.strptime(date_str, "%m/%d/%Y %I:%M:%S %p")
        except (ValueError, TypeError):
            pass
        try:
            # Try ISO format fallback
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass
        return None
