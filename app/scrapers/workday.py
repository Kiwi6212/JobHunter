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
#
# Site name discovery notes:
#   thales.wd3/Careers          → confirmed HTTP 200 (237 results)
#   ag.wd3/Airbus               → confirmed via robots.txt (/Airbus/ disallow)
#   ratp.wd3/RATP_Externe       → confirmed
#   airliquidehr.wd3/AirLiquideExternalCareer → confirmed
#   axa.wd3/AXA_External        → tenant exists; CXS returns 422 (Jibe frontend at
#                                  careers.axa.com; site name unconfirmed — best effort)
#   loreal.wd3/LOrealExternal   → tenant exists; CXS returns 422 (custom protected
#                                  platform at careers.loreal.com; best effort)
COMPANIES = [
    ("thales", 3, "Careers", "Thales"),
    ("ag", 3, "Airbus", "Airbus"),
    ("ratp", 3, "RATP_Externe", "RATP"),
    ("airliquidehr", 3, "AirLiquideExternalCareer", "Air Liquide"),
    # Added — Workday tenants confirmed; site names are best-effort
    # (public career portals use different frontends, but Workday is the backend)
    ("axa", 3, "AXA_External", "AXA"),
    ("loreal", 3, "LOrealExternal", "L'Oréal"),
    # CAC 40 companies
    ("sanofi", 3, "SanofiCareers", "Sanofi"),
    ("stellantis", 3, "External_Career_Site_ID01", "Stellantis"),
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

# France location indicators for filtering (reject non-France locations)
NON_FRANCE_INDICATORS = [
    "united states", "usa", "u.s.", "germany", "deutschland",
    "united kingdom", "uk", "canada", "india", "china",
    "spain", "italia", "italy", "netherlands", "belgium",
    "australia", "singapore", "japan", "brazil",
]


class WorkdayScraper(BaseScraper):
    """
    Scraper for Workday public jobs API.

    Searches multiple target companies for alternance offers,
    filters for France locations.
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

        # Deduplicate by external_id and URL
        seen_ids = set()
        seen_urls = set()
        unique_offers = []
        for offer in all_offers:
            eid = offer.get("external_id")
            if eid and eid in seen_ids:
                continue
            url = offer.get("url", "")
            if not eid and url and url in seen_urls:
                continue
            if eid:
                seen_ids.add(eid)
            if url:
                seen_urls.add(url)
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

        # Filter for France and parse
        base_url = f"https://{slug}.wd{wd_num}.myworkdayjobs.com"
        offers = []
        for job in unique:
            if not self._is_france(job):
                continue
            offer = self._parse_job(job, company_name, base_url)
            if offer:
                offers.append(offer)

        logger.info(
            f"[workday] [{company_name}] {len(offers)} France offers "
            f"(from {len(unique)} unique postings)"
        )

        return offers

    def close(self):
        """Close the HTTP session."""
        self.session.close()

    def _fetch_jobs(self, slug, wd_num, site, query):
        """Fetch jobs from the Workday API with pagination."""
        MAX_PAGES = 50
        all_jobs = []
        offset = 0
        limit = 20
        page = 0

        while True:
            page += 1
            if page > MAX_PAGES:
                logger.warning(f"[workday] Hit pagination cap ({MAX_PAGES}) for {slug}/{site} q='{query}'")
                break
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

    def _is_france(self, job):
        """Check if a job is located in France (reject known non-France locations)."""
        location = (job.get("locationsText") or "").lower()

        if not location:
            return False  # Skip jobs without location

        # Reject if location matches a known non-France country
        for indicator in NON_FRANCE_INDICATORS:
            if indicator in location:
                return False

        # Accept: includes "france", French city names, or unrecognized locations
        # (Workday companies are searched with French queries, so most results are French)
        return True

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
