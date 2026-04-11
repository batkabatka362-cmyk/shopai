"""Web scraping / page extraction adapter family.

Concrete adapters live here (Firecrawl today; Jina Reader,
Apify, Bright Data later). They share the
:class:`ScraperBaseAdapter` skeleton and wire into the router
through :func:`core.adapters.scraper.bootstrap.register_all`.
"""
from __future__ import annotations

from ._base import ScraperBaseAdapter
from .firecrawl import FirecrawlAdapter

__all__ = [
    "ScraperBaseAdapter",
    "FirecrawlAdapter",
]
