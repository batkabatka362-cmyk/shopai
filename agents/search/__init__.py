"""Multi-source search agent — web + supplier catalogs + intel.

Owner-facing "ask anything about a product, competitor, or
trend" layer. Fans out a single query across the adapter
surfaces that can answer it, then merges the results into
one ranked envelope so the caller doesn't have to juggle
source-specific shapes.
"""
from agents.search.agent import SearchAgent, SearchResult

__all__ = ["SearchAgent", "SearchResult"]
