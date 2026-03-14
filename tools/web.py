"""
Web search tools for retrieving documentation from the internet.

This module provides web search functionality using DuckDuckGo and
HTML scraping with BeautifulSoup. All operations are designed for
graceful failure — errors return empty results without raising exceptions.
"""

import logging
import time
from dataclasses import dataclass
from typing import List, Optional

import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)


@dataclass
class WebResult:
    """Result from a web search and page scrape."""
    title: str
    url: str
    summary: str
    content: str


class WebTools:
    """
    Provides web search and HTML scraping capabilities.

    Web search queries DuckDuckGo for results and scrapes page content.
    Rate limiting enforces max 5 searches per instance with a 2 second
    delay between searches. All errors are handled gracefully — the
    web_search method never raises exceptions.
    """

    MAX_SEARCHES_PER_SESSION = 5
    DELAY_BETWEEN_SEARCHES = 2  # seconds
    SCRAPE_TIMEOUT = 5  # seconds per page
    SUMMARY_MAX_CHARS = 500
    CONTENT_MAX_CHARS = 5000
    MAX_RESULTS = 3

    def __init__(self, config: Optional[dict] = None):
        """
        Initialize web tools with configuration.

        Args:
            config: Optional configuration dictionary. Expects
                    'web_search_enabled' key (default False).
        """
        self.config = config or {}
        self._search_count = 0
        self._last_search_time: Optional[float] = None

    @property
    def web_search_enabled(self) -> bool:
        """Check if web search is enabled in config."""
        return self.config.get("web_search_enabled", False)

    def web_search(self, query: str) -> List[WebResult]:
        """
        Search DuckDuckGo and scrape top results.

        Returns empty list on any failure (graceful degradation).
        Enforces rate limiting: max 5 searches per session with
        2 second delay between searches.

        Args:
            query: Search query string

        Returns:
            List of WebResult objects (may be empty)
        """
        if not self.web_search_enabled:
            return []

        # Rate limiting: max searches per session
        if self._search_count >= self.MAX_SEARCHES_PER_SESSION:
            logger.warning("Rate limit reached: %d/%d searches used",
                           self._search_count, self.MAX_SEARCHES_PER_SESSION)
            return []

        # Rate limiting: delay between searches
        if self._last_search_time is not None:
            elapsed = time.time() - self._last_search_time
            if elapsed < self.DELAY_BETWEEN_SEARCHES:
                time.sleep(self.DELAY_BETWEEN_SEARCHES - elapsed)

        try:
            results = DDGS().text(query, max_results=self.MAX_RESULTS)

            self._search_count += 1
            self._last_search_time = time.time()

            web_results: List[WebResult] = []
            for result in results:
                try:
                    response = requests.get(
                        result["href"], timeout=self.SCRAPE_TIMEOUT
                    )
                    soup = BeautifulSoup(response.text, "html.parser")
                    content = soup.get_text(separator="\n", strip=True)
                    summary = content[: self.SUMMARY_MAX_CHARS]

                    web_results.append(
                        WebResult(
                            title=result["title"],
                            url=result["href"],
                            summary=summary,
                            content=content[: self.CONTENT_MAX_CHARS],
                        )
                    )
                except Exception as e:
                    logger.warning("Failed to scrape %s: %s", result.get("href", "unknown"), e)
                    continue

            return web_results

        except Exception as e:
            logger.error("Web search failed: %s", e)
            return []
