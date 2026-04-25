"""Competitor intelligence — study other Shopify stores.

Scrapes the public-surface of any Shopify store (``/products.json``,
``/collections.json``, homepage HTML, script tags, Meta Ads Library)
and fuses the data into a single ``CompetitorReport`` with
strategic LLM insights.

No private-API access, no account, no login. Everything in this
module reads from the public domain of the target store — the
same data Google sees when indexing the shop.

Usage:

    >>> from agents.competitor_intel import analyze_competitor
    >>> report = analyze_competitor("allbirds.com")
    >>> report.summary     # dict of findings
    >>> report.insights    # LLM-generated strategic take

    >>> from agents.competitor_intel import (
    ...     save_report, diff_vs_last, load_history,
    ... )
    >>> save_report(report)
    >>> history = load_history("allbirds.com", limit=2)
    >>> prev = history[-2] if len(history) > 1 else None
    >>> diff_vs_last(report, prev)     # what changed

Pure stdlib. Dependency-injected HTTP + LLM for offline tests.
"""
from agents.competitor_intel.agent import (
    CompetitorReport,
    analyze_competitor,
    analyze_competitors,
    diff_vs_last,
    load_history,
    save_report,
)

__all__ = [
    "CompetitorReport",
    "analyze_competitor",
    "analyze_competitors",
    "diff_vs_last",
    "load_history",
    "save_report",
]
