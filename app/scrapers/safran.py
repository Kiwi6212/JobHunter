"""
Scraper for Safran Group career portal.
Fetches job offers from the Drupal-based site at safran-group.com/fr/offres.

The site returns standard HTML pages with job listings rendered as
`.c-offer-item` elements. We use BeautifulSoup to parse them.

Filters:
  - contracts[]=39-alternance  (alternance only)
  - countries[]=1002-france    (France only)
"""

import logging
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from app.scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.safran-group.com"
OFFERS_PATH = "/fr/offres"

# Search queries — patched by run_scrapers.py per domain
SEARCH_QUERIES = [
    "alternance",
]

# IDF location indicators for filtering
IDF_INDICATORS = [
    "paris", "île-de-france", "ile-de-france", "idf",
    "la défense", "la defense",
    "nanterre", "boulogne", "levallois", "puteaux",
    "courbevoie", "issy", "saint-denis", "massy",
    "vélizy", "velizy", "guyancourt", "saclay",
    "versailles", "meudon", "rueil", "noisy",
    "créteil", "roissy", "gennevilliers",
    "hauts-de-seine", "val-de-marne", "seine-saint-denis",
    "yvelines", "essonne", "val-d'oise", "seine-et-marne",
    "moissy", "villaroche", "corbeil", "evry", "melun",
    "argenteuil", "colombes", "montrouge",
]

MAX_PAGES = 30  # safety cap per query


class SafranScraper(BaseScraper):
    """
    Scraper for Safran Group Drupal career portal.

    Fetches alternance offers in France, parses HTML listings,
    and filters for Île-de-France locations.
    """

    @property
    def source_name(self):
        return "safran"

    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        })

    def collect(self):
        all_offers = []

        for query in SEARCH_QUERIES:
            logger.info(f"[safran] Searching query='{query}'")
            offers = self._search(query)
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
            f"[safran] Total unique offers: {len(unique)} "
            f"(from {len(all_offers)} raw)"
        )
        return unique

    def _search(self, query):
        """Search with pagination, filtered for alternance + France."""
        all_jobs = {}  # ref_id -> parsed dict
        page = 0

        while page < MAX_PAGES:
            jobs, has_next = self._fetch_page(query, page)
            for job in jobs:
                rid = job.get("ref_id")
                if rid and rid not in all_jobs:
                    all_jobs[rid] = job
            if not has_next or not jobs:
                break
            page += 1
            self._delay()

        # Filter for IDF
        idf_offers = []
        for job in all_jobs.values():
            if self._is_idf(job.get("location", "")):
                offer = self._to_offer(job)
                if offer:
                    idf_offers.append(offer)

        logger.info(
            f"[safran] q='{query}': {len(idf_offers)} IDF offers "
            f"(from {len(all_jobs)} unique)"
        )
        return idf_offers

    def _fetch_page(self, query, page):
        """Fetch one page of offers from the Safran career site."""
        params = {
            "search": query,
            "contracts[]": "39-alternance",
            "countries[]": "1002-france",
            "page": page,
        }

        try:
            url = f"{BASE_URL}{OFFERS_PATH}"
            response = self.session.get(
                url, params=params, timeout=self.config.TIMEOUT
            )

            if response.status_code != 200:
                logger.warning(f"[safran] HTTP {response.status_code} page={page}")
                return [], False

            soup = BeautifulSoup(response.text, "html.parser")
            items = soup.select(".c-offer-item")

            if not items:
                return [], False

            jobs = []
            for item in items:
                job = self._parse_item(item)
                if job:
                    jobs.append(job)

            # Check if there's a next page
            has_next = self._has_next_page(soup)

            return jobs, has_next

        except requests.exceptions.RequestException as e:
            logger.error(f"[safran] Request error page={page}: {e}")
            return [], False

    def _parse_item(self, item):
        """Parse a single .c-offer-item element."""
        try:
            # Title and URL from the link
            title_link = item.select_one(".c-offer-item__title a")
            if not title_link:
                title_link = item.select_one("a")
            if not title_link:
                return None

            title = title_link.get_text(strip=True)
            href = title_link.get("href", "")
            url = href if href.startswith("http") else f"{BASE_URL}{href}"

            # Extract reference ID from URL (e.g., /fr/offres/france/.../title-149651)
            ref_match = re.search(r'-(\d{4,})$', href)
            ref_id = ref_match.group(1) if ref_match else None

            # Date
            date_el = item.select_one(".c-offer-item__date")
            posted_date = None
            if date_el:
                date_text = date_el.get_text(strip=True)
                posted_date = self._parse_date(date_text)

            # Info items (company, location, status, contract, field)
            info_items = item.select(".c-offer-item__infos__item")
            company = "Safran"
            location = ""
            contract_type = "Alternance"

            if len(info_items) >= 1:
                company = info_items[0].get_text(strip=True) or "Safran"
            if len(info_items) >= 2:
                # Location is typically city, region, country
                location = info_items[1].get_text(strip=True)
            if len(info_items) >= 4:
                contract_type = info_items[3].get_text(strip=True) or "Alternance"

            # Build description from remaining info items
            desc_parts = [it.get_text(strip=True) for it in info_items if it.get_text(strip=True)]
            description = " | ".join(desc_parts) if desc_parts else None

            return {
                "ref_id": ref_id,
                "title": title,
                "url": url,
                "company": company,
                "location": location,
                "contract_type": contract_type,
                "description": description,
                "posted_date": posted_date,
            }

        except Exception as e:
            logger.warning(f"[safran] Error parsing item: {e}")
            return None

    def _parse_date(self, text):
        """Parse date in DD.MM.YYYY format."""
        if not text:
            return None
        # Try DD.MM.YYYY
        match = re.search(r'(\d{2})[./](\d{2})[./](\d{4})', text)
        if match:
            try:
                return datetime(
                    int(match.group(3)),
                    int(match.group(2)),
                    int(match.group(1)),
                )
            except ValueError:
                pass
        return None

    def _has_next_page(self, soup):
        """Check if there's a next page link in the pagination."""
        # Look for a "next" pagination link
        next_link = soup.select_one('.pager__item--next a, .pagination .next a, a[rel="next"]')
        if next_link:
            return True
        # Also check: if there are pagination items, see if current is last
        pager_items = soup.select('.pager__item a, .pagination a')
        return len(pager_items) > 1

    def _is_idf(self, location):
        """Check if location is in Île-de-France."""
        if not location:
            return False
        loc_lower = location.lower()
        return any(ind in loc_lower for ind in IDF_INDICATORS)

    def _to_offer(self, job):
        """Convert parsed job dict to normalized offer."""
        try:
            return self._normalize_offer(
                title=job["title"],
                company=job["company"],
                location=job["location"],
                contract_type=job["contract_type"],
                description=job.get("description"),
                url=job["url"],
                external_id=f"safran_{job['ref_id']}" if job.get("ref_id") else None,
                posted_date=job.get("posted_date"),
            )
        except Exception as e:
            logger.warning(f"[safran] Error converting job: {e}")
            return None
