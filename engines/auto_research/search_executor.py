"""Search Executor — runs search queries and returns raw results.

Responsibility: take a list of ``SearchQuery`` dicts, execute them against
one or more search back-ends, and return unified ``RawSearchResult`` lists.

The actual HTTP / API layer is **simulated** here with deterministic
placeholder data so the rest of the pipeline can function end-to-end.
In production this module would call Google, Bing, or an internal index.

Model note: no model usage — pure I/O layer.
"""
from __future__ import annotations

import copy
import hashlib
import time
from typing import Any

from .types import SearchQuery, RawSearchResult


# ---------------------------------------------------------------------------
# Simulated search corpus (deterministic, reproducible)
# ---------------------------------------------------------------------------

_SIMULATED_CORPUS: list[dict[str, str]] = [
    {
        "title": "Market Overview: Key Industry Trends",
        "url": "https://example.com/market-overview",
        "snippet": "The market has experienced significant growth over the past year, "
                   "driven by shifts in consumer behaviour and increased digital adoption.",
        "source": "example.com",
    },
    {
        "title": "Consumer Spending Report 2025",
        "url": "https://example.com/spending-report-2025",
        "snippet": "Consumer spending rose 4.2 % year-over-year, with notable increases "
                   "in the e-commerce sector across all demographics.",
        "source": "example.com",
    },
    {
        "title": "Competitive Landscape Analysis",
        "url": "https://reports.example.org/competitive-landscape",
        "snippet": "Top players continue to consolidate market share through aggressive "
                   "pricing and product diversification strategies.",
        "source": "reports.example.org",
    },
    {
        "title": "Product Innovation in Retail",
        "url": "https://retailnews.example.net/innovation",
        "snippet": "Innovative product design and sustainability-focused features are "
                   "becoming table stakes for retail brands targeting Gen Z.",
        "source": "retailnews.example.net",
    },
    {
        "title": "Pricing Strategy Guide",
        "url": "https://biz.example.com/pricing-strategy",
        "snippet": "Dynamic pricing models outperform flat-rate strategies by 15-20 % in "
                   "conversion rate across mid-tier e-commerce stores.",
        "source": "biz.example.com",
    },
    {
        "title": "Customer Satisfaction Benchmarks",
        "url": "https://data.example.com/csat-benchmarks",
        "snippet": "Average CSAT scores in online retail sit at 78, with top performers "
                   "reaching 92 through personalised post-purchase flows.",
        "source": "data.example.com",
    },
    {
        "title": "Supply Chain Resilience Report",
        "url": "https://logistics.example.com/resilience",
        "snippet": "Brands with diversified supply chains recovered 3x faster from "
                   "disruptions compared to single-source competitors.",
        "source": "logistics.example.com",
    },
    {
        "title": "Social Commerce Growth Tracker",
        "url": "https://social.example.com/commerce-growth",
        "snippet": "Social commerce transactions grew 28 % in Q4, with short-form video "
                   "driving the largest share of attributed revenue.",
        "source": "social.example.com",
    },
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def execute_searches(
    queries: list[SearchQuery],
    *,
    max_results_per_query: int = 5,
) -> list[RawSearchResult]:
    """Execute a batch of search queries and return raw results.

    Never mutates *queries* — works on a deep copy.
    Results are deduplicated by URL.
    """
    safe_queries: list[SearchQuery] = copy.deepcopy(queries)

    if not safe_queries:
        return []

    all_results: list[RawSearchResult] = []
    seen_urls: set[str] = set()
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for query in safe_queries:
        query_text: str = query.get("text", "")
        if not query_text:
            continue

        hits = _simulate_search(query_text, max_results_per_query)

        for hit in hits:
            url = hit["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)

            all_results.append(
                RawSearchResult(
                    title=hit["title"],
                    url=url,
                    snippet=hit["snippet"],
                    source=hit["source"],
                    retrieved_at=now_iso,
                )
            )

    return all_results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _simulate_search(query_text: str, max_results: int) -> list[dict[str, str]]:
    """Deterministically select corpus entries relevant to *query_text*.

    Uses a simple token-overlap heuristic so the results are query-dependent
    rather than random, giving downstream modules meaningful variation.
    """
    query_tokens = set(query_text.lower().split())

    scored: list[tuple[float, dict[str, str]]] = []
    for entry in _SIMULATED_CORPUS:
        entry_tokens = set(
            (entry["title"] + " " + entry["snippet"]).lower().split()
        )
        overlap = len(query_tokens & entry_tokens)
        # Use hash for stable tie-breaking
        tie = int(hashlib.md5(
            (query_text + entry["url"]).encode()
        ).hexdigest()[:8], 16) / 0xFFFFFFFF
        scored.append((overlap + tie, entry))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [entry for _, entry in scored[:max_results]]
