"""
Scraper for TalentBrew (Radancy) career sites.
Uses the AJAX search results API that returns HTML fragments in JSON.

Companies using TalentBrew: Veolia, Vinci.
"""

import html
import logging
import re
from datetime import datetime

import requests

from app.scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

# (base_url, search_path, display_name)
COMPANIES = [
    ("https://jobs.veolia.com", "/fr/search-jobs/results", "Veolia"),
    ("https://jobs.vinci.com", "/fr/search-jobs/results", "Vinci"),
]

SEARCH_QUERIES = [
    "alternance système",
    "alternance réseau",
    "alternance infrastructure",
    "alternance informatique",
    "alternance DevOps",
    "alternance support",
    "apprentissage système",
    "apprentissage réseau",
    "apprentissage informatique",
]

# IDF location indicators for filtering results
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
]


class TalentBrewScraper(BaseScraper):
    """
    Scraper for TalentBrew/Radancy career sites.

    Uses the AJAX search endpoint that returns HTML fragments wrapped in JSON.
    Parses job listings from the HTML and filters for IDF locations.
    """

    @property
    def source_name(self):
        return "talentbrew"

    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.config.USER_AGENT,
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        })

    def collect(self):
        all_offers = []

        for base_url, search_path, company_name in COMPANIES:
            logger.info(f"[talentbrew] Searching {company_name}")
            offers = self._search_company(base_url, search_path, company_name)
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
            f"[talentbrew] Total unique offers: {len(unique)} "
            f"(from {len(all_offers)} raw)"
        )
        return unique

    def _search_company(self, base_url, search_path, company_name):
        """Search a single company across all queries."""
        all_jobs = {}  # job_id -> parsed dict

        for query in SEARCH_QUERIES:
            page = 1
            while page <= 10:  # max 10 pages per query
                jobs, total_pages = self._fetch_page(
                    base_url, search_path, query, page
                )
                for job in jobs:
                    jid = job.get("job_id")
                    if jid and jid not in all_jobs:
                        all_jobs[jid] = job
                if page >= total_pages:
                    break
                page += 1
                self._delay()
            self._delay()

        # Filter for IDF
        idf_offers = []
        for job in all_jobs.values():
            if self._is_idf(job.get("location", "")):
                offer = self._to_offer(job, company_name, base_url)
                if offer:
                    idf_offers.append(offer)

        logger.info(
            f"[talentbrew] [{company_name}] {len(idf_offers)} IDF offers "
            f"(from {len(all_jobs)} unique postings)"
        )
        return idf_offers

    def _fetch_page(self, base_url, search_path, query, page):
        """Fetch one page of search results."""
        params = {
            "ActiveFacetID": "0",
            "CurrentPage": str(page),
            "RecordsPerPage": "25",
            "Keywords": query,
            "Location": "France",
            "Latitude": "46.227638",
            "Longitude": "2.213749",
            "ShowRadius": "False",
            "IsPagination": "True" if page > 1 else "False",
            "SearchResultsModuleName": "Search Results",
            "SearchFiltersModuleName": "Search Filters",
            "SortCriteria": "0",
            "SortDirection": "0",
            "SearchType": "5",
            "FacetFilters[0].ID": "Country",
            "FacetFilters[0].FacetType": "2",
            "FacetFilters[0].Count": "1",
            "FacetFilters[0].Display": "France",
            "FacetFilters[0].IsApplied": "true",
        }

        try:
            url = f"{base_url}{search_path}"
            response = self.session.get(url, params=params, timeout=self.config.TIMEOUT)

            if response.status_code != 200:
                logger.warning(
                    f"[talentbrew] HTTP {response.status_code} for {base_url}"
                )
                return [], 0

            data = response.json()
            results_html = data.get("results", "")
            if not results_html:
                return [], 0

            # Extract total pages
            total_pages_match = re.search(
                r'data-total-pages="(\d+)"', results_html
            )
            total_pages = int(total_pages_match.group(1)) if total_pages_match else 1

            # Parse jobs from HTML
            jobs = self._parse_html(results_html)
            return jobs, total_pages

        except requests.exceptions.RequestException as e:
            logger.error(f"[talentbrew] Request error: {e}")
            return [], 0

    def _parse_html(self, results_html):
        """Parse job listings from TalentBrew HTML fragment."""
        jobs = []

        # Pattern 1: Veolia-style
        # <a href="/fr/emploi/..." data-job-id="123"><h2>Title</h2>
        # <span class="job-location">...\n  Location\n</span>
        pattern1 = re.findall(
            r'<a\s+href="(/[^"]+)"\s*data-job-id="([^"]+)"[^>]*>'
            r'\s*<h2>([^<]+)</h2>'
            r'.*?class="job-location[^"]*"[^>]*>'
            r'(?:<span[^>]*></span>)?\s*([^<]+)',
            results_html,
            re.DOTALL,
        )

        # Pattern 2: Vinci-style
        # <a href="/fr/emploi/..." data-job-id="123" class="search-results--link">
        # <span class="search-results--link-jobtitle">Title</span>
        # <span class="...search-results--link-location">Location</span>
        pattern2 = re.findall(
            r'<a\s+href="(/[^"]+)"\s*data-job-id="([^"]+)"[^>]*>'
            r'.*?link-jobtitle[^>]*>([^<]+)</span>'
            r'.*?link-location[^>]*>([^<]+)</span>',
            results_html,
            re.DOTALL,
        )

        for url_path, job_id, title, location in pattern1 + pattern2:
            jobs.append({
                "job_id": job_id.strip(),
                "title": html.unescape(title.strip()),
                "location": html.unescape(location.strip()),
                "url_path": url_path.strip(),
            })

        return jobs

    def _is_idf(self, location):
        """Check if location is in Île-de-France."""
        loc_lower = location.lower()
        return any(ind in loc_lower for ind in IDF_INDICATORS)

    def _to_offer(self, job, company_name, base_url):
        """Convert parsed job dict to normalized offer."""
        try:
            return self._normalize_offer(
                title=job["title"],
                company=company_name,
                location=job["location"],
                contract_type="Alternance",
                url=f"{base_url}{job['url_path']}",
                external_id=f"tb_{job['job_id']}",
                posted_date=None,
            )
        except Exception as e:
            logger.warning(f"[talentbrew] Error converting job: {e}")
            return None
