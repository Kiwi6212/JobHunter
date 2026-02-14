"""
Scraper for La bonne alternance API (api.apprentissage.beta.gouv.fr).
Fetches apprenticeship/alternance job offers using ROME codes.
"""

import logging
from datetime import datetime

import requests

from app.scrapers.base_scraper import BaseScraper
from config import APIKeys, ROME_CODES, FILTERS

logger = logging.getLogger(__name__)

# Paris center coordinates for geo-search
IDF_CENTER = {
    "latitude": 48.8566,
    "longitude": 2.3522,
}

# 60km radius covers most of Ile-de-France
IDF_RADIUS_KM = 60


class LaBonneAlternanceScraper(BaseScraper):
    """
    Scraper for La bonne alternance API.

    Uses ROME codes (not free-text keywords) to search for alternance offers.
    Results include both posted offers and potential recruiters.
    API returns max 450 jobs + 150 recruiters per request.
    """

    @property
    def source_name(self):
        return "la_bonne_alternance"

    def __init__(self):
        super().__init__()
        self.api_key = APIKeys.LBA_API_KEY
        self.base_url = APIKeys.LBA_API_URL
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        })

    def collect(self):
        """
        Collect alternance offers from La bonne alternance API.
        Searches using ROME codes for Ile-de-France region.

        Returns:
            list[dict]: Normalized offer dictionaries.
        """
        if not self.api_key:
            logger.error("[la_bonne_alternance] No API key configured. Set LBA_API_KEY in .env")
            return []

        all_offers = []

        # Search by ROME codes in batches (API accepts comma-separated)
        rome_codes_str = ",".join(ROME_CODES)
        departments = FILTERS.get("departments", [])

        logger.info(
            f"[la_bonne_alternance] Searching ROME codes: {rome_codes_str} "
            f"in departments: {departments}"
        )

        # Strategy 1: Search by geo (Paris center + radius)
        geo_offers = self._search_by_geo(rome_codes_str)
        all_offers.extend(geo_offers)

        # Strategy 2: Search by departments for broader coverage
        dept_offers = self._search_by_departments(rome_codes_str, departments)
        all_offers.extend(dept_offers)

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
            f"[la_bonne_alternance] Total unique offers: {len(unique_offers)} "
            f"(from {len(all_offers)} raw results)"
        )

        return unique_offers

    def _search_by_geo(self, rome_codes_str):
        """Search offers by geographic coordinates (Paris center)."""
        params = {
            "romes": rome_codes_str,
            "latitude": IDF_CENTER["latitude"],
            "longitude": IDF_CENTER["longitude"],
            "radius": IDF_RADIUS_KM,
        }

        return self._execute_search(params, "geo-search")

    def _search_by_departments(self, rome_codes_str, departments):
        """Search offers by department numbers."""
        if not departments:
            return []

        params = {
            "romes": rome_codes_str,
        }

        # API accepts multiple departements params
        offers = []
        # Search all departments at once
        response = self._api_request("/job/v1/search", params, departments=departments)
        if response:
            offers = self._parse_response(response, "dept-search")

        return offers

    def _execute_search(self, params, label):
        """Execute a search with given parameters and parse results."""
        response = self._api_request("/job/v1/search", params)
        if response:
            return self._parse_response(response, label)
        return []

    def _api_request(self, endpoint, params, departments=None):
        """
        Make an API request with error handling and rate limit awareness.

        Args:
            endpoint: API endpoint path
            params: Query parameters dict
            departments: Optional list of department codes

        Returns:
            dict or None: JSON response data, or None on error
        """
        url = f"{self.base_url}{endpoint}"

        try:
            # Build query string manually for repeated departements params
            if departments:
                dept_params = "&".join(f"departements={d}" for d in departments)
                base_params = "&".join(f"{k}={v}" for k, v in params.items())
                full_url = f"{url}?{base_params}&{dept_params}"
                response = self.session.get(full_url, timeout=self.config.TIMEOUT)
            else:
                response = self.session.get(url, params=params, timeout=self.config.TIMEOUT)

            # Handle rate limiting (API uses 419, not 429)
            if response.status_code == 419:
                logger.warning("[la_bonne_alternance] Rate limited (419). Backing off...")
                self._delay()
                self._delay()  # Double delay on rate limit
                return None

            if response.status_code == 401:
                logger.error("[la_bonne_alternance] Authentication failed. Check LBA_API_KEY.")
                return None

            response.raise_for_status()
            return response.json()

        except requests.exceptions.Timeout:
            logger.error(f"[la_bonne_alternance] Request timeout for {endpoint}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"[la_bonne_alternance] Request error: {e}")
            return None

    def _parse_response(self, data, label=""):
        """
        Parse API response and extract job offers.

        Args:
            data: JSON response from API
            label: Label for logging

        Returns:
            list[dict]: Normalized offer dictionaries
        """
        offers = []

        # Parse job offers
        jobs = data.get("jobs", [])
        for job in jobs:
            offer = self._parse_job(job)
            if offer:
                offers.append(offer)

        # Parse potential recruiters (companies likely to hire)
        recruiters = data.get("recruiters", [])
        for recruiter in recruiters:
            offer = self._parse_recruiter(recruiter)
            if offer:
                offers.append(offer)

        # Log any warnings from the API
        warnings = data.get("warnings", [])
        for warning in warnings:
            logger.warning(
                f"[la_bonne_alternance] API warning ({label}): "
                f"{warning.get('message', 'Unknown warning')}"
            )

        logger.info(
            f"[la_bonne_alternance] [{label}] Parsed {len(jobs)} jobs + "
            f"{len(recruiters)} recruiters"
        )

        return offers

    def _parse_job(self, job):
        """Parse a single job offer from the API response."""
        try:
            identifier = job.get("identifier", {})
            workplace = job.get("workplace", {})
            offer_data = job.get("offer", {})
            contract = job.get("contract", {})
            apply_data = job.get("apply", {})
            location_data = workplace.get("location", {})

            # Build external ID
            external_id = identifier.get("partner_job_id") or identifier.get("id")

            # Build title
            title = offer_data.get("title", "Unknown Title")

            # Build company name (try structured fields only, never descriptions)
            company = (
                workplace.get("brand")
                or workplace.get("name")
                or workplace.get("legal_name")
                or workplace.get("enseigne")
                or identifier.get("partner_label")
                or "Non renseigné"
            )

            # Build location string
            address = location_data.get("address", "")

            # Build URL
            url = apply_data.get("url", "")

            # Parse dates
            publication = offer_data.get("publication", {})
            posted_date = None
            creation_str = publication.get("creation")
            if creation_str:
                try:
                    posted_date = datetime.fromisoformat(
                        creation_str.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    pass

            # Contract type
            contract_types = contract.get("type", [])
            contract_type = ", ".join(contract_types) if contract_types else "Alternance"

            # Build description
            description_parts = []
            if offer_data.get("description"):
                description_parts.append(offer_data["description"])
            if offer_data.get("desired_skills"):
                description_parts.append(
                    "Competences souhaitees: " + ", ".join(offer_data["desired_skills"])
                )
            if offer_data.get("to_be_acquired_skills"):
                description_parts.append(
                    "Competences a acquerir: " + ", ".join(offer_data["to_be_acquired_skills"])
                )
            description = "\n\n".join(description_parts) if description_parts else None

            # Partner label for source tracking
            partner = identifier.get("partner_label", "la_bonne_alternance")

            return self._normalize_offer(
                title=title,
                company=company,
                location=address or None,
                contract_type=contract_type,
                description=description,
                url=url,
                external_id=f"lba_{external_id}" if external_id else None,
                posted_date=posted_date,
            )

        except Exception as e:
            logger.warning(f"[la_bonne_alternance] Error parsing job: {e}")
            return None

    def _parse_recruiter(self, recruiter):
        """Parse a potential recruiter from the API response."""
        try:
            identifier = recruiter.get("identifier", {})
            workplace = recruiter.get("workplace", {})
            apply_data = recruiter.get("apply", {})
            location_data = workplace.get("location", {})

            external_id = identifier.get("id")

            company = (
                workplace.get("brand")
                or workplace.get("name")
                or workplace.get("legal_name")
                or workplace.get("enseigne")
                or "Non renseigné"
            )

            address = location_data.get("address", "")
            url = apply_data.get("url", "")

            # Recruiters don't have specific offer details
            naf = workplace.get("domain", {}).get("naf", {})
            naf_label = naf.get("label", "")

            return self._normalize_offer(
                title=f"Recruteur potentiel - {naf_label}" if naf_label else "Recruteur potentiel en alternance",
                company=company,
                location=address or None,
                contract_type="Alternance",
                description=f"Entreprise susceptible de recruter en alternance. Secteur: {naf_label}" if naf_label else None,
                url=url,
                external_id=f"lba_recruiter_{external_id}" if external_id else None,
                posted_date=None,
                offer_type="recruiter",
            )

        except Exception as e:
            logger.warning(f"[la_bonne_alternance] Error parsing recruiter: {e}")
            return None

