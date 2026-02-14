"""
Scraper for Workday public job posting API.
Fetches apprenticeship/alternance offers from target companies that use
Workday as their ATS.

Endpoint: POST https://{slug}.wd{N}.myworkdayjobs.com/wday/cxs/{slug}/{site}/jobs
Body: {"limit": 20, "offset": 0, "searchText": "alternance"}
"""

import logging
import re
from datetime import datetime, timedelta

import requests

from app.scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

# Target companies on Workday: (subdomain_slug, wd_number, site_name, display_name)
COMPANIES = [
    ("thales", 3, "Careers", "Thales"),
    ("ag", 3, "Airbus", "Airbus"),
    ("ratp", 3, "RATP_Externe", "RATP"),
    ("airliquidehr", 3, "AirLiquideExternalCareer", "Air Liquide"),
]

# Search queries combining alternance + domain keywords
SEARCH_QUERIES = [
    "alternance système",
    "alternance réseau",
    "alternance infrastructure",
    "alternance DevOps",
    "alternance support informatique",
    "alternance sysadmin",
    "apprentissage système",
    "apprentissage réseau",
    "apprentissage informatique",
]

# IDF location indicators for filtering
IDF_INDICATORS = [
    "paris", "île-de-france", "ile-de-france", "idf",
    "la défense", "la defense",
    "nanterre", "boulogne", "levallois", "puteaux",
    "courbevoie", "issy", "saint-denis", "massy",
    "vélizy", "velizy", "guyancourt", "saclay",
    "palaiseau", "roissy", "noisy", "créteil",
    "versailles", "meudon", "rueil",
    "elancourt", "limours", "gennevilliers",
]


class WorkdayScraper(BaseScraper):
    """
    Scraper for Workday public jobs API.

    Searches multiple target companies for alternance offers,
    filters for Île-de-France locations.
    """

    @property
    def source_name(self):
        return "workday"

    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": self.config.USER_AGENT,
        })

    def collect(self):
        """
        Collect alternance offers from all configured Workday companies.

        Returns:
            list[dict]: Normalized offer dictionaries.
        """
        all_offers = []

        for slug, wd_num, site, company_name in COMPANIES:
            logger.info(f"[workday] Searching {company_name} ({slug}.wd{wd_num}/{site})")
            offers = self._search_company(slug, wd_num, site, company_name)
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
            f"[workday] Total unique offers: {len(unique_offers)} "
            f"(from {len(all_offers)} raw results)"
        )

        return unique_offers

    def _search_company(self, slug, wd_num, site, company_name):
        """Search a single company for alternance offers."""
        all_jobs = []

        for query in SEARCH_QUERIES:
            jobs = self._fetch_jobs(slug, wd_num, site, query)
            all_jobs.extend(jobs)
            self._delay()

        # Deduplicate by externalPath within this company
        seen = set()
        unique = []
        for job in all_jobs:
            path = job.get("externalPath", "")
            if path in seen:
                continue
            seen.add(path)
            unique.append(job)

        # Filter for IDF and parse
        base_url = f"https://{slug}.wd{wd_num}.myworkdayjobs.com"
        offers = []
        for job in unique:
            if not self._is_idf(job):
                continue
            offer = self._parse_job(job, company_name, base_url)
            if offer:
                offers.append(offer)

        logger.info(
            f"[workday] [{company_name}] {len(offers)} IDF offers "
            f"(from {len(unique)} unique postings)"
        )

        return offers

    def _fetch_jobs(self, slug, wd_num, site, query):
        """Fetch jobs from the Workday API with pagination."""
        all_jobs = []
        offset = 0
        limit = 20

        while True:
            url = (
                f"https://{slug}.wd{wd_num}.myworkdayjobs.com"
                f"/wday/cxs/{slug}/{site}/jobs"
            )
            payload = {
                "limit": limit,
                "offset": offset,
                "searchText": query,
            }

            try:
                response = self.session.post(
                    url, json=payload, timeout=self.config.TIMEOUT
                )

                if response.status_code != 200:
                    logger.warning(
                        f"[workday] HTTP {response.status_code} for "
                        f"{slug}/{site} q='{query}'"
                    )
                    break

                data = response.json()
                jobs = data.get("jobPostings", [])
                total = data.get("total", 0)

                all_jobs.extend(jobs)

                if len(all_jobs) >= total or not jobs:
                    break

                offset += limit

            except requests.exceptions.RequestException as e:
                logger.error(f"[workday] Request error: {e}")
                break

        return all_jobs

    def _is_idf(self, job):
        """Check if a job is located in Île-de-France."""
        location = (job.get("locationsText") or "").lower()

        if not location:
            return False  # Skip jobs without location

        for indicator in IDF_INDICATORS:
            if indicator in location:
                return True

        return False

    def _parse_job(self, job, company_name, base_url):
        """Parse a Workday job posting into a normalized offer dict."""
        try:
            title = job.get("title", "Unknown Title")
            external_path = job.get("externalPath", "")

            # URL
            url = f"{base_url}{external_path}" if external_path else ""

            # Location
            location = job.get("locationsText")

            # External ID from path (e.g., /job/Paris/Title_R0304980-1)
            ext_id = ""
            path_match = re.search(r'_([A-Z0-9]+-?\d*)$', external_path)
            if path_match:
                ext_id = path_match.group(1)

            # Posted date from relative text (e.g., "Posted 3 Days Ago")
            posted_date = self._parse_posted_on(job.get("postedOn", ""))

            # Contract type and other info from bulletFields
            bullet_fields = job.get("bulletFields", [])
            contract_type = "Alternance"
            description_parts = []
            for field in bullet_fields:
                if field:
                    description_parts.append(field)
                    field_lower = field.lower()
                    if "apprenti" in field_lower or "alternance" in field_lower:
                        contract_type = field

            description = " | ".join(description_parts) if description_parts else None

            return self._normalize_offer(
                title=title,
                company=company_name,
                location=location,
                contract_type=contract_type,
                description=description,
                url=url,
                external_id=f"wd_{ext_id}" if ext_id else None,
                posted_date=posted_date,
            )

        except Exception as e:
            logger.warning(f"[workday] Error parsing job: {e}")
            return None

    def _parse_posted_on(self, text):
        """Parse Workday relative date like 'Posted 3 Days Ago'."""
        if not text:
            return None

        text = text.lower().strip()
        now = datetime.utcnow()

        if "today" in text or "aujourd" in text:
            return now

        match = re.search(r"(\d+)\s*day", text)
        if match:
            return now - timedelta(days=int(match.group(1)))

        # "Posted 30+ Days Ago"
        match = re.search(r"(\d+)\+?\s*day", text)
        if match:
            return now - timedelta(days=int(match.group(1)))

        # French: "il y a X jours"
        match = re.search(r"(\d+)\s*jour", text)
        if match:
            return now - timedelta(days=int(match.group(1)))

        return None
