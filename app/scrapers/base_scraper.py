"""
Abstract base class for all job scrapers.
All scrapers must implement the collect() method.
"""

import logging
import time
import random
from abc import ABC, abstractmethod
from datetime import datetime

from config import ScrapingConfig

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """
    Abstract base class that all job source scrapers must inherit from.

    Each scraper must implement:
        - source_name: property returning the scraper's identifier
        - collect(): method that fetches and returns raw job offers
    """

    def __init__(self):
        self.config = ScrapingConfig()

    @property
    @abstractmethod
    def source_name(self):
        """Return the unique identifier for this scraper source."""
        pass

    @abstractmethod
    def collect(self):
        """
        Collect job offers from the source.

        Returns:
            list[dict]: List of normalized offer dictionaries with keys:
                - title (str)
                - company (str)
                - location (str or None)
                - contract_type (str or None)
                - description (str or None)
                - url (str)
                - source (str)
                - external_id (str or None)
                - posted_date (datetime or None)
        """
        pass

    def _delay(self):
        """Apply a random delay between requests to avoid rate limiting."""
        delay = random.uniform(self.config.DELAY_MIN, self.config.DELAY_MAX)
        logger.debug(f"[{self.source_name}] Waiting {delay:.1f}s before next request")
        time.sleep(delay)

    def _normalize_offer(self, **kwargs):
        """
        Create a normalized offer dictionary from scraper-specific data.

        Args:
            **kwargs: Offer fields (title, company, location, etc.)

        Returns:
            dict: Normalized offer dictionary
        """
        return {
            "title": kwargs.get("title", "Unknown Title"),
            "company": kwargs.get("company", "Unknown Company"),
            "location": kwargs.get("location"),
            "contract_type": kwargs.get("contract_type"),
            "description": kwargs.get("description"),
            "url": kwargs.get("url", ""),
            "source": self.source_name,
            "external_id": kwargs.get("external_id"),
            "posted_date": kwargs.get("posted_date"),
            "relevance_score": kwargs.get("relevance_score", 0.0),
            "offer_type": kwargs.get("offer_type", "job"),
        }

    def run(self):
        """
        Execute the scraper with logging and error handling.

        Returns:
            list[dict]: Collected and normalized offers, or empty list on error.
        """
        logger.info(f"[{self.source_name}] Starting collection...")
        start_time = time.time()

        try:
            offers = self.collect()
            elapsed = time.time() - start_time
            logger.info(
                f"[{self.source_name}] Collected {len(offers)} offers in {elapsed:.1f}s"
            )
            return offers
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                f"[{self.source_name}] Error after {elapsed:.1f}s: {e}", exc_info=True
            )
            return []
