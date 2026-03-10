"""
Scraper for the France Travail Offres d'emploi v2 API.

Authentication: OAuth2 client_credentials
  POST https://entreprise.francetravail.fr/connexion/oauth2/access_token
  with scope "api_offresdemploiv2 o2dsoffre"

Search endpoint:
  GET https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search

Coverage: Île-de-France departments, alternance (typeContrat=E), sysadmin ROME codes.
Pagination via the `range` query parameter (max 150 per page).
"""

import logging
from datetime import datetime

import requests

from app.scrapers.base_scraper import BaseScraper
from config import APIKeys, ROME_CODES, FILTERS

logger = logging.getLogger(__name__)

TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
OFFER_URL = "https://candidat.francetravail.fr/offres/recherche/detail/{}"

SCOPE = "api_offresdemploiv2 o2dsoffre"
PAGE_SIZE = 150   # Maximum per request
MAX_PAGES = 10    # Safety cap: 1 500 offers per ROME+dept combo at most


class FranceTravailScraper(BaseScraper):
    """
    Fetches alternance job offers from the France Travail v2 API.

    Iterates over every (ROME code, IDF department) pair and paginates
    through results using the `range` header / query parameter.
    Deduplicates by external_id across all pages and pairs.
    """

    @property
    def source_name(self):
        return "france_travail"

    def __init__(self):
        super().__init__()
        self.client_id = APIKeys.FRANCE_TRAVAIL_CLIENT_ID
        self.client_secret = APIKeys.FRANCE_TRAVAIL_CLIENT_SECRET
        self._token = None

    # ── Authentication ────────────────────────────────────────────────

    def _get_token(self):
        """Obtain (and cache for this run) an OAuth2 Bearer token."""
        if self._token:
            return self._token
        try:
            resp = requests.post(
                TOKEN_URL,
                params={"realm": "/partenaire"},
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": SCOPE,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
            resp.raise_for_status()
            self._token = resp.json()["access_token"]
            logger.info("[france_travail] OAuth2 token obtained.")
            return self._token
        except Exception as e:
            logger.error(f"[france_travail] Failed to obtain OAuth2 token: {e}")
            return None

    # ── Collection ────────────────────────────────────────────────────

    def collect(self):
        if not self.client_id or not self.client_secret:
            logger.error(
                "[france_travail] Missing credentials. "
                "Set FRANCE_TRAVAIL_CLIENT_ID and FRANCE_TRAVAIL_CLIENT_SECRET in .env"
            )
            return []

        token = self._get_token()
        if not token:
            return []

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        departments = FILTERS.get("departments", ["75", "77", "78", "91", "92", "93", "94", "95"])
        all_offers = []
        seen_ids = set()
        seen_urls = set()

        for rome in ROME_CODES:
            for dept in departments:
                offers = self._search_page(headers, rome, dept, seen_ids, seen_urls)
                all_offers.extend(offers)
                if offers:
                    logger.info(
                        f"[france_travail] ROME={rome} dept={dept}: {len(offers)} offers"
                    )

        logger.info(f"[france_travail] Total unique offers: {len(all_offers)}")
        return all_offers

    def _search_page(self, headers, rome_code, departement, seen_ids, seen_urls):
        """Paginate through all results for one (ROME, department) pair."""
        offers = []
        start = 0

        for _ in range(MAX_PAGES):
            end = start + PAGE_SIZE - 1
            params = {
                "codeROME": rome_code,
                "departement": departement,
                "natureContrat": "E1",       # E1 = Apprentissage
                "range": f"{start}-{end}",
            }

            try:
                resp = requests.get(
                    SEARCH_URL,
                    headers=headers,
                    params=params,
                    timeout=self.config.TIMEOUT,
                )
            except requests.exceptions.RequestException as e:
                logger.error(
                    f"[france_travail] Request error "
                    f"(ROME={rome_code}, dept={departement}): {e}"
                )
                break

            if resp.status_code == 204:
                break   # No results
            if resp.status_code in (400, 401, 403):
                logger.error(
                    f"[france_travail] HTTP {resp.status_code} "
                    f"(ROME={rome_code}, dept={departement})"
                )
                break
            if resp.status_code not in (200, 206):
                logger.warning(
                    f"[france_travail] Unexpected status {resp.status_code}, skipping page."
                )
                break

            try:
                data = resp.json()
            except ValueError:
                break

            results = data.get("resultats", [])
            if not results:
                break

            for item in results:
                offer = self._parse_offer(item)
                if not offer:
                    continue
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
                offers.append(offer)

            # Determine total from Content-Range: "offres 0-149/320"
            total = _parse_content_range_total(resp.headers.get("Content-Range", ""))
            next_start = end + 1
            if total is not None and next_start >= total:
                break
            if len(results) < PAGE_SIZE:
                break

            start = next_start
            self._delay()

        return offers

    # ── Parsing ───────────────────────────────────────────────────────

    def _parse_offer(self, item):
        """Convert a single API result dict to a normalized offer dict."""
        try:
            offer_id = item.get("id", "")
            title = item.get("intitule") or "Unknown Title"

            entreprise = item.get("entreprise") or {}
            company = entreprise.get("nom") or "Non renseigné"

            lieu = item.get("lieuTravail") or {}
            location = lieu.get("libelle")

            description = item.get("description")

            origine = item.get("origineOffre") or {}
            url = origine.get("urlOrigine")
            if not url and offer_id:
                url = OFFER_URL.format(offer_id)
            if not url:
                return None

            posted_date = _parse_date(item.get("dateCreation"))
            contract_type = item.get("typeContratLibelle") or item.get("typeContrat")
            external_id = f"ft_{offer_id}" if offer_id else None

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
            logger.warning(f"[france_travail] Error parsing offer: {e}")
            return None


# ── Helpers ───────────────────────────────────────────────────────────

def _parse_date(date_str):
    """Parse an ISO 8601 date string, return datetime or None."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _parse_content_range_total(header):
    """
    Extract total from a Content-Range header like "offres 0-149/320".
    Returns int or None.
    """
    if "/" not in header:
        return None
    try:
        return int(header.split("/")[1].strip())
    except (ValueError, IndexError):
        return None
