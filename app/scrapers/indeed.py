"""
Scraper for Indeed France (fr.indeed.com).
Fetches apprenticeship/alternance job offers using Selenium with Brave browser
and undetected-chromedriver to bypass Cloudflare anti-bot protection.

Note: Indeed blocks headless browsers, so Brave runs in visible (minimized)
mode. A browser window will briefly appear during scraping.
"""

import logging
import os
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode, urljoin

import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from app.scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

# Indeed France base URL
BASE_URL = "https://fr.indeed.com"
SEARCH_URL = f"{BASE_URL}/jobs"

# Brave browser path
BRAVE_PATH = os.getenv(
    "BRAVE_PATH",
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
)

# Brave Chromium major version (update when Brave updates)
BRAVE_VERSION_MAIN = 145

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

# Max pages per query (10 results per page)
MAX_PAGES = 1

# Max seconds to wait for Cloudflare challenge to resolve
CLOUDFLARE_WAIT = 15


class IndeedScraper(BaseScraper):
    """
    Scraper for Indeed France via Selenium + undetected-chromedriver.

    Uses Brave browser (minimized window) to bypass Cloudflare protection.
    Indeed blocks headless browsers, so a visible window is required.
    Searches for alternance offers in Île-de-France, parses job cards,
    and deduplicates by job key.
    """

    @property
    def source_name(self):
        return "indeed"

    def __init__(self):
        super().__init__()
        self.driver = None

    def _create_driver(self):
        """Create an undetected Chrome driver using Brave browser."""
        if not os.path.exists(BRAVE_PATH):
            logger.error(f"[indeed] Brave not found at {BRAVE_PATH}")
            return None

        options = uc.ChromeOptions()
        options.binary_location = BRAVE_PATH

        # NO headless — Indeed blocks it. Use minimized window instead.
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
            # Minimize window immediately
            driver.minimize_window()
            logger.info("[indeed] Brave browser started (minimized)")
            return driver
        except Exception as e:
            logger.error(f"[indeed] Failed to start Brave: {e}")
            return None

    def _wait_for_cloudflare(self):
        """Wait for Cloudflare 'Un instant...' challenge to resolve."""
        for i in range(CLOUDFLARE_WAIT):
            title = self.driver.title.lower()
            if "instant" not in title and "blocked" not in title and title:
                return True
            time.sleep(1)

        title = self.driver.title
        if "blocked" in title.lower():
            logger.error("[indeed] Blocked by Indeed after Cloudflare challenge.")
            return False
        if "instant" in title.lower():
            logger.warning("[indeed] Cloudflare challenge did not resolve in time.")
            return False

        return True

    def collect(self):
        """
        Collect alternance offers from Indeed France.

        Launches Brave via undetected-chromedriver, waits for Cloudflare
        challenge, then searches each keyword query with pagination.

        Returns:
            list[dict]: Normalized offer dictionaries.
        """
        self.driver = self._create_driver()
        if not self.driver:
            return []

        try:
            # Visit homepage and wait for Cloudflare challenge
            logger.info("[indeed] Visiting homepage (waiting for Cloudflare)...")
            self.driver.get(BASE_URL)

            if not self._wait_for_cloudflare():
                return []

            logger.info(f"[indeed] Homepage loaded: '{self.driver.title}'")
            self._delay()

            all_offers = []
            blocked = False

            for query in SEARCH_QUERIES:
                if blocked:
                    logger.warning(
                        "[indeed] Skipping remaining queries due to blocking."
                    )
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

        finally:
            self._quit_driver()

    def _quit_driver(self):
        """Safely quit the browser driver."""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("[indeed] Browser closed")
            except Exception:
                pass
            self.driver = None

    def _search_query(self, query):
        """
        Run a search query across multiple pages.

        Returns:
            tuple: (offers_list, was_blocked)
        """
        offers = []

        for page in range(MAX_PAGES):
            start = page * 10

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
        Navigate to a search results page and parse it.

        Returns:
            tuple: (offers_list_or_None, was_blocked)
        """
        url = f"{SEARCH_URL}?{urlencode(params)}"

        try:
            self.driver.get(url)

            # Always wait for Cloudflare challenge to resolve
            if not self._wait_for_cloudflare():
                return None, True

            # Wait for job results to appear
            try:
                WebDriverWait(self.driver, 10).until(
                    lambda d: (
                        d.find_elements(By.CSS_SELECTOR, "div.job_seen_beacon")
                        or d.find_elements(By.CSS_SELECTOR, "[data-jk]")
                        or d.find_elements(By.ID, "mosaic-jobResults")
                    )
                )
            except Exception:
                pass  # Timeout waiting, try to parse anyway

            # Final block check on resolved page
            title_lower = self.driver.title.lower()
            if "blocked" in title_lower:
                logger.warning(
                    f"[indeed] Blocked on q='{query}' page {page_num}. Stopping."
                )
                return None, True

            soup = BeautifulSoup(self.driver.page_source, "lxml")
            offers = self._parse_results(soup)

            logger.info(
                f"[indeed] [q='{query}'] page {page_num}: {len(offers)} offers"
            )

            return offers, False

        except Exception as e:
            logger.error(f"[indeed] Error fetching page: {e}")
            return None, False

    def _parse_results(self, soup):
        """Parse job cards from an Indeed search results page."""
        offers = []

        # Indeed card container: div.job_seen_beacon holds all job info
        job_cards = soup.select("div.job_seen_beacon")

        if not job_cards:
            # Fallback selectors
            job_cards = soup.select(
                "div.cardOutline, div.result, li.css-5lfssm"
            )

        for card in job_cards:
            offer = self._parse_card(card)
            if offer:
                offers.append(offer)

        return offers

    def _parse_card(self, card):
        """Parse a single job card into a normalized offer dict."""
        try:
            # Extract job key from the title link's data-jk attribute
            jk_el = card.find(attrs={"data-jk": True})
            job_key = jk_el.get("data-jk", "") if jk_el else ""

            # Title (inside h2.jobTitle > a > span)
            title_el = (
                card.select_one("h2.jobTitle a span")
                or card.select_one("a.jcs-JobTitle span")
                or card.select_one("h2.jobTitle a")
                or card.select_one("h2.jobTitle")
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

            # Company name (span with data-testid="company-name")
            company_el = (
                card.select_one("[data-testid='company-name']")
                or card.select_one("span.companyName")
                or card.select_one("span.company")
            )
            company = (
                company_el.get_text(strip=True) if company_el else "Non renseigné"
            )

            # Location (div with data-testid="text-location")
            location_el = (
                card.select_one("[data-testid='text-location']")
                or card.select_one("div.companyLocation")
            )
            location = location_el.get_text(strip=True) if location_el else None

            # Description snippet (from metadata list items)
            snippet_el = (
                card.select_one("div.job-snippet")
                or card.select_one("ul.jobCardShelfContainer")
                or card.select_one("table.jobCardShelfContainer")
            )
            description = (
                snippet_el.get_text(strip=True) if snippet_el else None
            )

            # Posted date (span.date or data-testid)
            date_el = (
                card.select_one("span.date")
                or card.select_one("[data-testid='myJobsStateDate']")
            )
            posted_date = None
            if date_el:
                posted_date = self._parse_relative_date(
                    date_el.get_text(strip=True)
                )

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
