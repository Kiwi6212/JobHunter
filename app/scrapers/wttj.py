"""
Scraper for Welcome to the Jungle (WTTJ) via Algolia Search API.
Fetches apprenticeship/alternance job offers for sysadmin/infrastructure roles.
"""

import logging
from datetime import datetime

import requests

from app.scrapers.base_scraper import BaseScraper
from config import KEYWORDS

logger = logging.getLogger(__name__)

# Algolia public credentials (client-side search-only key from WTTJ frontend)
ALGOLIA_APP_ID = "CSEKHVMS53"
ALGOLIA_API_KEY = "4bd8f6215d0cc52b26430765769e65a0"
ALGOLIA_URL = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/wttj_jobs_production_fr/query"

# Paris center for geo-search
IDF_CENTER_LAT = 48.8566
IDF_CENTER_LNG = 2.3522
IDF_RADIUS_M = 60000  # 60km in meters

# WTTJ sub-category for network/sysadmin roles
SYSADMIN_SUBCATEGORY = "network-engineering-and-administration-yZjhm"

# Search queries covering our domain
SEARCH_QUERIES = [
    "",  # Empty query with sub-category filter catches all sysadmin roles
    "administrateur systèmes",
    "technicien infrastructure",
    "ingénieur réseaux",
]


class WTTJScraper(BaseScraper):
    """
    Scraper for Welcome to the Jungle via Algolia.

    Uses Algolia's search API with WTTJ's public credentials to find
    alternance offers in Ile-de-France for sysadmin/infrastructure roles.
    """

    @property
    def source_name(self):
        return "welcome_to_the_jungle"

    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.headers.update({
            "x-algolia-application-id": ALGOLIA_APP_ID,
            "x-algolia-api-key": ALGOLIA_API_KEY,
            "Content-Type": "application/json",
            "Referer": "https://www.welcometothejungle.com/",
            "Origin": "https://www.welcometothejungle.com",
        })

    def collect(self):
        """
        Collect alternance offers from WTTJ via Algolia.

        Strategy:
        1. Search with sub-category filter (sysadmin) + no query → broad coverage
        2. Search with keyword queries → catch offers in other categories

        Returns:
            list[dict]: Normalized offer dictionaries.
        """
        all_offers = []

        for query in SEARCH_QUERIES:
            facet_filters = [["contract_type:apprenticeship"]]

            # For empty query, add sub-category filter for precision
            if not query:
                facet_filters.append(
                    [f"new_profession.sub_category_reference:{SYSADMIN_SUBCATEGORY}"]
                )

            offers = self._search(query, facet_filters)
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
            f"[wttj] Total unique offers: {len(unique_offers)} "
            f"(from {len(all_offers)} raw results)"
        )

        return unique_offers

    def _search(self, query, facet_filters):
        """Run a single Algolia search and return parsed offers."""
        all_hits = []
        page = 0
        max_pages = 10  # Safety limit

        while page < max_pages:
            payload = {
                "query": query,
                "hitsPerPage": 50,
                "page": page,
                "facetFilters": facet_filters,
                "aroundLatLng": f"{IDF_CENTER_LAT}, {IDF_CENTER_LNG}",
                "aroundRadius": IDF_RADIUS_M,
            }

            try:
                response = self.session.post(
                    ALGOLIA_URL, json=payload, timeout=self.config.TIMEOUT
                )

                if response.status_code != 200:
                    logger.error(
                        f"[wttj] Algolia returned {response.status_code}: "
                        f"{response.text[:200]}"
                    )
                    break

                data = response.json()
                hits = data.get("hits", [])
                nb_pages = data.get("nbPages", 0)

                label = f"q='{query}'" if query else "sub-category"
                logger.info(
                    f"[wttj] [{label}] page {page + 1}/{nb_pages}: "
                    f"{len(hits)} hits"
                )

                all_hits.extend(hits)

                page += 1
                if page >= nb_pages:
                    break

                self._delay()

            except requests.exceptions.RequestException as e:
                logger.error(f"[wttj] Request error: {e}")
                break

        # Parse all hits into normalized offers
        offers = []
        for hit in all_hits:
            offer = self._parse_hit(hit)
            if offer:
                offers.append(offer)

        return offers

    def _parse_hit(self, hit):
        """Parse a single Algolia hit into a normalized offer dict."""
        try:
            # Title
            title = hit.get("name", "Unknown Title")

            # Company
            org = hit.get("organization", {})
            company = org.get("name") or "Non renseigné"

            # Location
            offices = hit.get("offices", [])
            if offices:
                office = offices[0]
                city = office.get("city", "")
                state = office.get("state", "")
                location = f"{city}, {state}" if city and state else city or state
            else:
                location = None

            # URL
            org_slug = org.get("slug", "")
            job_slug = hit.get("slug", "")
            url = (
                f"https://www.welcometothejungle.com/fr/companies/"
                f"{org_slug}/jobs/{job_slug}"
            )

            # External ID
            external_id = f"wttj_{hit.get('objectID', '')}"

            # Posted date
            posted_date = None
            published_at = hit.get("published_at")
            if published_at:
                try:
                    posted_date = datetime.fromisoformat(
                        published_at.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    pass

            # Contract type
            contract_type = hit.get("contract_type", "apprenticeship")
            if contract_type == "apprenticeship":
                contract_type = "Alternance"

            # Description (combine available fields)
            parts = []
            if hit.get("summary"):
                parts.append(hit["summary"])
            missions = hit.get("key_missions")
            if missions:
                parts.append("Missions: " + "; ".join(missions))
            if hit.get("profile"):
                parts.append("Profil: " + hit["profile"])
            description = "\n\n".join(parts) if parts else None

            return self._normalize_offer(
                title=title,
                company=company,
                location=location,
                contract_type=contract_type,
                description=description,
                url=url,
                external_id=external_id,
                posted_date=posted_date,
            )

        except Exception as e:
            logger.warning(f"[wttj] Error parsing hit: {e}")
            return None
