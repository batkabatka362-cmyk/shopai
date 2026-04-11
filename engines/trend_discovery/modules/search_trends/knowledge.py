"""Search trends domain knowledge — expert keyword research intelligence.

What veterans know:
  - "Long-tail keywords convert 2.5x better than head terms"
  - "Search volume alone is meaningless without intent"
  - "Rising keywords with low competition = gold"
  - "If CPC is $0, nobody's making money from that keyword"
"""
from __future__ import annotations
from typing import Any

KEYWORD_STRATEGY = {
    "new_store": {
        "focus": "Long-tail keywords (4+ words) with low competition",
        "volume_target": "200-2000 monthly searches",
        "example": "'organic dog joint supplement for senior dogs' (not 'dog supplement')",
        "timeline": "Start ranking in 2-8 weeks",
    },
    "established_store": {
        "focus": "Medium-tail keywords (2-3 words) with medium competition",
        "volume_target": "2000-10000 monthly searches",
        "example": "'organic dog supplement' (broader, more competitive)",
        "timeline": "Start ranking in 2-4 months",
    },
    "authority_store": {
        "focus": "Head terms (1-2 words) and category ownership",
        "volume_target": "10000+ monthly searches",
        "example": "'dog supplement' (category leader positioning)",
        "timeline": "6-12 months to rank on page 1",
    },
}

SEARCH_HEURISTICS = [
    "A keyword with 500 searches/month and 'buy' intent > 5000 searches/month with 'how to' intent",
    "CPC between $0.50-$3.00 = advertisers making money = viable product",
    "CPC = $0 usually means no commercial value (informational only)",
    "CPC > $5.00 = very competitive, need strong margins to afford ads",
    "Google Trends 'breakout' (>5000% growth) = usually a fad, not a trend",
    "Consistent 20-50% YoY growth over 2+ years = real trend",
    "Seasonal keywords: start content 3 months before peak, ads 1 month before",
    "Amazon 'most wished for' + rising Google searches = product-market fit confirmed",
]

def get_keyword_strategy(store_level: str = "new_store") -> dict[str, Any]:
    return KEYWORD_STRATEGY.get(store_level, KEYWORD_STRATEGY["new_store"])

def get_heuristics() -> list[str]:
    return SEARCH_HEURISTICS
