"""
Scraper for Phenom People career sites using Selenium + Brave.
Phenom sites are SPAs that render job cards client-side, so a real
browser is required. Uses undetected-chromedriver to avoid bot detection.

Companies using Phenom: Orange, Bouygues.
"""

import logging
import os
import re
import time

import undetected_chromedriver as uc
from bs4 import BeautifulSoup

from app.scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

BRAVE_PATH = os.getenv(
    "BRAVE_PATH",
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
)
BRAVE_VERSION_MAIN = 145

# (base_url, search_path, lang_prefix, display_name)
# lang_prefix is part of the URL path (e.g. /fr/fr or /global/fr)
COMPANIES = [
    (
        "https://orange.jobs",
        "/fr/fr/search-results",
        "Orange",
    ),
    (
        "https://joining.bouygues.com",
        "/global/fr/search-results",
        "Bouygues",
    ),
]

SEARCH_QUERIES = [
    "alternance système",
    "alternance réseau",
    "alternance infrastructure",
    "alternance DevOps",
]

# Max pages to scrape per query (10 results per page)
MAX_PAGES = 5

# IDF location indicators
IDF_INDICATORS = [
    "paris", "île-de-france", "ile-de-france", "idf",
    "la défense", "la defense",
    "nanterre", "boulogne", "levallois", "puteaux",
    "courbevoie", "issy", "saint-denis", "massy",
    "vélizy", "velizy", "guyancourt", "saclay",
    "versailles", "meudon", "rueil", "noisy",
    "créteil", "roissy", "gennevilliers", "chatillon",
    "arcueil", "montrouge", "malakoff", "clamart",
    "meudon", "sèvres", "bagneux",
]


class PhenomScraper(BaseScraper):
    """
    Selenium-based scraper for Phenom People career sites.

    Launches Brave browser (minimized) to render the SPA,
    parses job cards from the DOM, and paginates via URL params.
    """

    @property
    def source_name(self):
        return "phenom"

    def __init__(self):
        super().__init__()
        self.driver = None

    def _create_driver(self):
        """Create an undetected Chrome driver using Brave browser."""
        if not os.path.exists(BRAVE_PATH):
            logger.error(f"[phenom] Brave not found at {BRAVE_PATH}")
            return None

        options = uc.ChromeOptions()
        options.binary_location = BRAVE_PATH
        options.add_argument("--start-minimized")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--lang=fr-FR")

        try:
            driver = uc.Chrome(
                options=options,
                headless=False,
                use_subprocess=True,
                version_main=BRAVE_VERSION_MAIN,
            )
            driver.set_page_load_timeout(30)
            driver.minimize_window()
            logger.info("[phenom] Brave browser started (minimized)")
            return driver
        except Exception as e:
            logger.error(f"[phenom] Failed to start Brave: {e}")
            return None

    def _quit_driver(self):
        """Safely quit the browser driver."""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("[phenom] Browser closed")
            except Exception:
                pass
            self.driver = None

    def collect(self):
        self.driver = self._create_driver()
        if not self.driver:
            return []

        try:
            all_offers = []

            for base_url, search_path, company_name in COMPANIES:
                logger.info(f"[phenom] Searching {company_name} ({base_url})")
                offers = self._search_company(base_url, search_path, company_name)
                all_offers.extend(offers)
                self._delay()

            # Deduplicate by external_id
            seen = set()
            unique = []
            for offer in all_offers:
                eid = offer.get("external_id")
                if eid and eid in seen:
                    continue
                if eid:
                    seen.add(eid)
                unique.append(offer)

            logger.info(
                f"[phenom] Total unique offers: {len(unique)} "
                f"(from {len(all_offers)} raw)"
            )
            return unique

        finally:
            self._quit_driver()

    def _search_company(self, base_url, search_path, company_name):
        """Search one company across all queries."""
        all_jobs = {}  # job_id -> parsed dict

        for query in SEARCH_QUERIES:
            for page in range(MAX_PAGES):
                offset = page * 10
                url = (
                    f"{base_url}{search_path}"
                    f"?keywords={query.replace(' ', '+')}"
                    f"&from={offset}&s=1"
                )

                jobs = self._fetch_page(url, company_name, base_url)

                if jobs is None:
                    break  # error or blocked

                for job in jobs:
                    jid = job.get("job_id")
                    if jid and jid not in all_jobs:
                        all_jobs[jid] = job

                if len(jobs) < 10:
                    break  # last page

                self._delay()
            self._delay()

        # Filter for IDF
        idf_offers = []
        for job in all_jobs.values():
            if self._is_idf(job.get("location", "")):
                offer = self._to_offer(job, company_name)
                if offer:
                    idf_offers.append(offer)

        logger.info(
            f"[phenom] [{company_name}] {len(idf_offers)} IDF offers "
            f"(from {len(all_jobs)} unique postings)"
        )
        return idf_offers

    def _fetch_page(self, url, company_name, base_url):
        """Navigate to a search page and parse job cards."""
        try:
            self.driver.get(url)
            # Wait for SPA to render job cards
            time.sleep(6)

            # Check for blocked / error pages
            title = self.driver.title.lower()
            if "blocked" in title or "error" in title:
                logger.warning(f"[phenom] Blocked on {company_name}")
                return None

            soup = BeautifulSoup(self.driver.page_source, "lxml")
            return self._parse_cards(soup, base_url)

        except Exception as e:
            logger.error(f"[phenom] Error fetching {url}: {e}")
            return None

    def _parse_cards(self, soup, base_url):
        """Parse Phenom job cards from rendered DOM."""
        jobs = []

        # Job cards are marked with data-ph-at-id="jobs-list-item"
        cards = soup.select('[data-ph-at-id="jobs-list-item"]')

        for card in cards:
            job = self._parse_single_card(card, base_url)
            if job:
                jobs.append(job)

        return jobs

    def _parse_single_card(self, card, base_url):
        """Parse a single Phenom job card."""
        try:
            # Title and link from job-link element
            link_el = card.select_one('[data-ph-at-id="job-link"]')
            if not link_el:
                return None

            title = (
                link_el.get("data-ph-at-job-title-text")
                or link_el.get_text(strip=True)
            )
            job_id = link_el.get("data-ph-at-job-id-text", "")

            href = link_el.get("href", "")
            if href and not href.startswith("http"):
                href = f"{base_url}{href}"

            if not title:
                return None

            # Location — try multiple Phenom field names
            location = self._get_field_text(card, [
                "job-location",
                "job-cityCountry",
                "job-multi_location",
                "job-addressLine",
            ])

            # Contract type
            contract = self._get_field_text(card, [
                "job-contractType",
                "job-type",
                "job-hiringType",
            ])

            # Category / department
            category = self._get_field_text(card, [
                "job-category",
                "job-multi_category",
            ])

            # Company (for multi-brand sites like Bouygues)
            company = self._get_field_text(card, [
                "job-company",
                "job-businessSegment",
            ])

            # Build description
            desc_parts = []
            if contract:
                desc_parts.append(contract)
            if category:
                desc_parts.append(category)
            if company:
                desc_parts.append(company)

            return {
                "job_id": job_id,
                "title": title,
                "location": location or "",
                "url": href,
                "description": " | ".join(desc_parts) if desc_parts else None,
            }

        except Exception as e:
            logger.warning(f"[phenom] Error parsing card: {e}")
            return None

    def _get_field_text(self, card, at_ids):
        """Get text from the first matching data-ph-at-id element."""
        for at_id in at_ids:
            el = card.select_one(f'[data-ph-at-id="{at_id}"]')
            if el:
                text = el.get_text(strip=True)
                # Remove label prefix like "City, Country :" or "Catégorie :"
                if ":" in text:
                    text = text.split(":", 1)[1].strip()
                if text:
                    return text
        return None

    def _is_idf(self, location):
        """Check if location is in Île-de-France."""
        loc_lower = location.lower()
        return any(ind in loc_lower for ind in IDF_INDICATORS)

    def _to_offer(self, job, company_name):
        """Convert parsed job dict to normalized offer."""
        try:
            return self._normalize_offer(
                title=job["title"],
                company=company_name,
                location=job["location"],
                contract_type="Alternance",
                description=job.get("description"),
                url=job["url"],
                external_id=f"phenom_{job['job_id']}" if job.get("job_id") else None,
                posted_date=None,
            )
        except Exception as e:
            logger.warning(f"[phenom] Error converting job: {e}")
            return None
