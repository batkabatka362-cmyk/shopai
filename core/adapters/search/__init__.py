"""Web search adapters.

Each adapter wraps a single search vendor in the universal
``BaseAdapter`` interface so the brain can route to it via
``Capability.WEB_SEARCH``:

  * ``ddgs``   — DuckDuckGo HTML scrape, **no API key**, default
  * ``brave``  — Brave Search API, 2,000 free queries/month
  * ``serper`` — Serper.dev (Google SERP proxy), 2,500 free/month

The shared ``SearchBaseAdapter`` (in ``_base.py``) handles HTTP
plumbing and the normalised ``SearchHit`` shape so concrete
adapters become 30-50 lines of vendor-specific URL + parser.

Bootstrap call::

    from core.adapters.search.bootstrap import register_all
    register_all()

Importing this package alone does NOT register anything — call
``bootstrap.register_all()`` so test isolation stays clean.
"""
from ._base import SearchBaseAdapter, SearchHit

__all__ = ["SearchBaseAdapter", "SearchHit"]
