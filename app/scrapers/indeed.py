"""
Scraper for Indeed France (fr.indeed.com).
Fetches apprenticeship/alternance job offers via HTML scraping with BeautifulSoup.

Indeed uses aggressive anti-bot protection (Cloudflare). This scraper:
1. Establishes a session by visiting the homepage first (gets cookies)
2. Uses realistic browser headers and referer chains
3. Applies longer delays between requests
4. Gracefully handles 403/CAPTCHA blocks
"""

import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup

from app.scrapers.base_scraper import BaseScraper
from config import ScrapingConfig

logger = logging.getLogger(__name__)

# Indeed France base URL
BASE_URL = "https://fr.indeed.com"
SEARCH_URL = f"{BASE_URL}/jobs"

# Search queries (alternance keywords for sysadmin/infra roles)
SEARCH_QUERIES = [
    "administrateur système alternance",
    "technicien réseau alternance",
    "infrastructure IT alternance",
    "DevOps alternance",
    "support informatique alternance",
]

# Location filter
LOCATION = "Île-de-France"

# Max pages per query (15 results per page on Indeed France)
MAX_PAGES = 3


class IndeedScraper(BaseScraper):
    """
    Scraper for Indeed France via HTML parsing.

    Searches for alternance offers in Île-de-France using keyword queries.
    Parses job cards from search result pages using BeautifulSoup.

    Note: Indeed may block requests despite mitigation measures.
    The scraper handles blocks gracefully and returns whatever it can collect.
    """

    @property
    def source_name(self):
        return "indeed"

    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": ScrapingConfig.USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        })
        self._session_ready = False

    def _init_session(self):
        """Visit the Indeed homepage to establish cookies and session."""
        if self._session_ready:
            return True

        try:
            logger.info("[indeed] Initializing session (visiting homepage)...")
            response = self.session.get(BASE_URL, timeout=self.config.TIMEOUT)

            if response.status_code == 200:
                self._session_ready = True
                logger.info(
                    f"[indeed] Session initialized "
                    f"({len(self.session.cookies)} cookies set)"
                )
                return True

            logger.warning(
                f"[indeed] Homepage returned {response.status_code}. "
                f"Scraping may be blocked."
            )
            # Still try to continue
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"[indeed] Failed to initialize session: {e}")
            return False

    def collect(self):
        """
        Collect alternance offers from Indeed France.

        Establishes a browser-like session first, then searches multiple
        keyword queries with pagination and deduplication.

        Returns:
            list[dict]: Normalized offer dictionaries.
        """
        # Establish session with cookies
        if not self._init_session():
            return []

        self._delay()  # Wait after homepage visit

        all_offers = []
        blocked = False

        for query in SEARCH_QUERIES:
            if blocked:
                logger.warning("[indeed] Skipping remaining queries due to blocking.")
                break

            logger.info(f"[indeed] Searching: '{query}'")
            offers, was_blocked = self._search_query(query)
            all_offers.extend(offers)
            blocked = was_blocked
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
            f"[indeed] Total unique offers: {len(unique_offers)} "
            f"(from {len(all_offers)} raw results)"
        )

        return unique_offers

    def _search_query(self, query):
        """
        Run a search query across multiple pages.

        Returns:
            tuple: (offers_list, was_blocked)
        """
        offers = []

        for page in range(MAX_PAGES):
            start = page * 10  # Indeed uses 10 results per page

            params = {
                "q": query,
                "l": LOCATION,
                "start": start,
            }

            page_offers, was_blocked = self._fetch_page(params, query, page + 1)

            if was_blocked:
                return offers, True

            if not page_offers:
                break

            offers.extend(page_offers)

            if page < MAX_PAGES - 1:
                self._delay()

        return offers, False

    def _fetch_page(self, params, query, page_num):
        """
        Fetch and parse a single search results page.

        Returns:
            tuple: (offers_list_or_None, was_blocked)
        """
        url = f"{SEARCH_URL}?{urlencode(params)}"

        # Update referer to look like natural browsing
        self.session.headers["Referer"] = (
            BASE_URL if page_num == 1
            else f"{SEARCH_URL}?{urlencode({**params, 'start': (page_num - 2) * 10})}"
        )
        self.session.headers["Sec-Fetch-Site"] = "same-origin"

        try:
            response = self.session.get(url, timeout=self.config.TIMEOUT)

            if response.status_code == 403:
                logger.warning(
                    f"[indeed] Blocked (403) on q='{query}' page {page_num}. "
                    f"Indeed anti-bot protection active."
                )
                return None, True

            if response.status_code != 200:
                logger.error(
                    f"[indeed] HTTP {response.status_code} on q='{query}' page {page_num}"
                )
                return None, False

            # Check for CAPTCHA/block page
            text_lower = response.text.lower()
            if "captcha" in text_lower or "unusual traffic" in text_lower:
                logger.warning(
                    f"[indeed] CAPTCHA detected on q='{query}' page {page_num}. "
                    f"Stopping all Indeed queries."
                )
                return None, True

            soup = BeautifulSoup(response.text, "lxml")
            offers = self._parse_results(soup)

            logger.info(
                f"[indeed] [q='{query}'] page {page_num}: {len(offers)} offers"
            )

            return offers, False

        except requests.exceptions.RequestException as e:
            logger.error(f"[indeed] Request error: {e}")
            return None, False

    def _parse_results(self, soup):
        """Parse job cards from an Indeed search results page."""
        offers = []

        # Indeed job cards: look for elements with data-jk (job key)
        job_cards = soup.find_all(attrs={"data-jk": True})

        if not job_cards:
            # Fallback: try finding job cards by common class patterns
            job_cards = soup.select(
                "div.job_seen_beacon, div.cardOutline, "
                "div.result, li.css-5lfssm"
            )

        for card in job_cards:
            offer = self._parse_card(card)
            if offer:
                offers.append(offer)

        return offers

    def _parse_card(self, card):
        """Parse a single job card into a normalized offer dict."""
        try:
            # Extract job key for external_id
            job_key = card.get("data-jk", "")
            if not job_key:
                jk_el = card.find(attrs={"data-jk": True})
                if jk_el:
                    job_key = jk_el.get("data-jk", "")

            # Title
            title_el = (
                card.select_one("h2.jobTitle a span")
                or card.select_one("h2.jobTitle span")
                or card.select_one("h2.jobTitle a")
                or card.select_one("h2.jobTitle")
                or card.select_one("a.jcs-JobTitle span")
                or card.select_one("a.jcs-JobTitle")
            )
            title = title_el.get_text(strip=True) if title_el else None
            if not title:
                return None

            # URL from title link
            link_el = (
                card.select_one("h2.jobTitle a")
                or card.select_one("a.jcs-JobTitle")
                or card.select_one("a[data-jk]")
            )
            if link_el and link_el.get("href"):
                href = link_el["href"]
                url = urljoin(BASE_URL, href)
            elif job_key:
                url = f"{BASE_URL}/viewjob?jk={job_key}"
            else:
                url = ""

            # Company name
            company_el = (
                card.select_one("[data-testid='company-name']")
                or card.select_one("span.companyName")
                or card.select_one("span.company")
            )
            company = company_el.get_text(strip=True) if company_el else "Non renseigné"

            # Location
            location_el = (
                card.select_one("[data-testid='text-location']")
                or card.select_one("div.companyLocation")
                or card.select_one("span.companyLocation")
            )
            location = location_el.get_text(strip=True) if location_el else None

            # Description snippet
            snippet_el = (
                card.select_one("div.job-snippet")
                or card.select_one("div.heading6")
                or card.select_one("table.jobCardShelfContainer")
            )
            description = snippet_el.get_text(strip=True) if snippet_el else None

            # Posted date (relative text like "il y a 3 jours")
            date_el = (
                card.select_one("span.date")
                or card.select_one("[data-testid='myJobsStateDate']")
            )
            posted_date = None
            if date_el:
                posted_date = self._parse_relative_date(date_el.get_text(strip=True))

            external_id = f"indeed_{job_key}" if job_key else None

            return self._normalize_offer(
                title=title,
                company=company,
                location=location,
                contract_type="Alternance",
                description=description,
                url=url,
                external_id=external_id,
                posted_date=posted_date,
            )

        except Exception as e:
            logger.warning(f"[indeed] Error parsing card: {e}")
            return None

    def _parse_relative_date(self, text):
        """Parse French relative date strings like 'il y a 3 jours'."""
        if not text:
            return None

        text = text.lower().strip()
        now = datetime.utcnow()

        # "aujourd'hui" / "à l'instant"
        if "aujourd" in text or "instant" in text:
            return now

        # "il y a X jours"
        match = re.search(r"(\d+)\s*jour", text)
        if match:
            days = int(match.group(1))
            return now - timedelta(days=days)

        # "il y a X heures"
        match = re.search(r"(\d+)\s*heure", text)
        if match:
            hours = int(match.group(1))
            return now - timedelta(hours=hours)

        return None
