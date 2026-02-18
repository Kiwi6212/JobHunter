"""
Scraper for choisirleservicepublic.gouv.fr (Place de l'emploi public).
Fetches public sector Numérique/IT job offers in Île-de-France.

API: POST /wp-json/api/offer-list — returns paginated list, no server-side filtering.
Filtering is done client-side by domain (Numérique) and IDF department code.
"""

import logging
import re
from datetime import datetime

import requests
import urllib3

from app.scrapers.base_scraper import BaseScraper

# Suppress SSL warnings — the site has a cert issue
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

BASE_URL = "https://choisirleservicepublic.gouv.fr"
API_URL = f"{BASE_URL}/wp-json/api/offer-list"

# Number of API pages to fetch per run (20 offers per page)
MAX_PAGES = 60

# Île-de-France department codes
IDF_DEPT_CODES = {"75", "77", "78", "91", "92", "93", "94", "95"}

# French month names for date parsing
FR_MONTHS = {
    "janvier": 1, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
}


class PlaceEmploiPublicScraper(BaseScraper):
    """
    Scraper for the French public sector job portal.

    Strategy:
    1. Paginate through the offer-list API (no server-side filtering available).
    2. Keep only offers with domain="Numérique" and an IDF department code.
    3. Use the list-level data; no detail-page fetching needed.
    """

    @property
    def source_name(self):
        return "place_emploi_public"

    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update({
            "User-Agent": self.config.USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": f"{BASE_URL}/nos-offres/",
            "Origin": BASE_URL,
        })

    def collect(self):
        """
        Collect public sector Numérique/IT offers in Île-de-France.

        Returns:
            list[dict]: Normalized offer dictionaries.
        """
        all_offers = []
        seen_refs = set()

        for page in range(1, MAX_PAGES + 1):
            try:
                response = self.session.post(
                    API_URL,
                    json={"page": page},
                    timeout=self.config.TIMEOUT,
                )

                if response.status_code != 200:
                    logger.warning(
                        f"[place_emploi_public] API returned {response.status_code} on page {page}"
                    )
                    break

                data = response.json()
                items = data.get("items", [])

                if not items:
                    logger.info(f"[place_emploi_public] No items on page {page}, stopping.")
                    break

                pagination = data.get("pagination", {})
                nb_pages = pagination.get("nb_page", 1)

                logger.debug(
                    f"[place_emploi_public] page {page}/{nb_pages} "
                    f"({pagination.get('total_elements_count', '?')} total)"
                )

                for item in items:
                    offer = self._filter_and_parse(item, seen_refs)
                    if offer:
                        all_offers.append(offer)

                if page >= nb_pages:
                    break

                self._delay()

            except requests.exceptions.RequestException as e:
                logger.error(f"[place_emploi_public] Request error on page {page}: {e}")
                break
            except Exception as e:
                logger.error(f"[place_emploi_public] Unexpected error on page {page}: {e}", exc_info=True)
                break

        logger.info(f"[place_emploi_public] Collected {len(all_offers)} Numérique/IDF offers")
        return all_offers

    def _filter_and_parse(self, item, seen_refs):
        """
        Apply client-side filters and build a normalized offer dict.
        Returns None if the item should be skipped.
        """
        # Domain filter — only IT/Digital offers
        if item.get("domain") != "Numérique":
            return None

        # Location filter — only Île-de-France
        raw_loc = item.get("localisation", "")
        dept_match = re.search(r"\((\d{2,3})\)", raw_loc)
        if not dept_match or dept_match.group(1) not in IDF_DEPT_CODES:
            return None

        # Deduplicate by internal reference number
        ref = item.get("reference", "")
        if ref:
            if ref in seen_refs:
                return None
            seen_refs.add(ref)

        url = item.get("url", "").strip()
        if not url:
            return None

        # Clean location string (strip HTML like <strong>)
        clean_loc = re.sub(r"<[^>]+>", "", raw_loc).strip()
        dept_code = dept_match.group(1)
        location = f"Île-de-France ({dept_code})"

        # Company / employer name
        company = (item.get("employeur") or "Administration publique").strip()

        # External ID
        external_id = f"pep_{ref}" if ref else None

        # Posted date
        posted_date = self._parse_date(item.get("publication_date", ""))

        # Title
        title = (item.get("title") or "Offre sans titre").strip()

        # Build description from available metadata
        desc_parts = []
        if item.get("fonction_public"):
            desc_parts.append(f"Versant: {item['fonction_public']}")
        if clean_loc:
            desc_parts.append(f"Lieu: {clean_loc}")
        if item.get("domain"):
            desc_parts.append(f"Domaine: {item['domain']}")
        description = "\n".join(desc_parts) if desc_parts else None

        return self._normalize_offer(
            title=title,
            company=company,
            location=location,
            contract_type=None,
            description=description,
            url=url,
            external_id=external_id,
            posted_date=posted_date,
        )

    def _parse_date(self, date_str):
        """Parse French date strings like '18 février 2026'."""
        if not date_str:
            return None
        try:
            parts = date_str.strip().split()
            if len(parts) == 3:
                day = int(parts[0])
                month = FR_MONTHS.get(parts[1].lower(), 0)
                year = int(parts[2])
                if month:
                    return datetime(year, month, day)
        except (ValueError, IndexError):
            pass
        return None
