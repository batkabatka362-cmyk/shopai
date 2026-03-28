"""Crawler — discovers and crawls pages systematically."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger
from .scraper import Scraper

logger = get_logger("data.crawler")


class Crawler:
    """Systematically crawls websites to discover products and data."""

    def __init__(self, max_pages: int = 100) -> None:
        self._scraper = Scraper()
        self._max_pages = max_pages
        self._visited: set[str] = set()

    def crawl(self, start_url: str) -> list[dict[str, Any]]:
        logger.info("Starting crawl from: %s (max=%d)", start_url, self._max_pages)
        results: list[dict[str, Any]] = []
        # Placeholder: actual crawl logic with queue
        return results

    def get_visited_count(self) -> int:
        return len(self._visited)
