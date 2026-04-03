"""Search Optimization Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the search optimization engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class ProductRecord(TypedDict, total=False):
    """Product record for SEO analysis."""
    id: str
    title: str
    description: str
    category: str
    tags: list[str]
    url: str


class SearchQuery(TypedDict, total=False):
    """On-site search query record."""
    query: str
    count: int
    results_count: int
    click_through_rate: float
    zero_results: bool


class MetaRecord(TypedDict, total=False):
    """Current meta tag record for a product/page."""
    product_id: str
    title: str
    description: str
    keywords: list[str]
    url: str


class CompetitorRecord(TypedDict, total=False):
    """Competitor data."""
    name: str
    domain: str
    top_keywords: list[str]
    domain_authority: float


class SearchOptimizationInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    products: list[ProductRecord]
    search_queries: list[SearchQuery]
    current_meta: list[MetaRecord]
    competitors: list[CompetitorRecord]


# ---------------------------------------------------------------------------
# Intermediate types — keyword analysis
# ---------------------------------------------------------------------------

class KeywordAnalysisResult(TypedDict):
    """Keyword analysis for a single query/keyword."""
    keyword: str
    search_volume: int
    competition: str
    relevance_score: float
    gap: bool
    opportunity_score: float


# ---------------------------------------------------------------------------
# Intermediate types — meta generation
# ---------------------------------------------------------------------------

class MetaRecommendation(TypedDict):
    """Meta tag recommendation for a product."""
    product_id: str
    title: str
    description: str
    keywords: list[str]
    improvements: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — content scoring
# ---------------------------------------------------------------------------

class ContentScore(TypedDict):
    """Content SEO score for a product page."""
    product_id: str
    overall_score: float
    title_score: float
    description_score: float
    keyword_density: float
    readability: float
    issues: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — sitemap building
# ---------------------------------------------------------------------------

class SitemapEntry(TypedDict):
    """Single entry in the sitemap."""
    url: str
    priority: float
    change_frequency: str
    last_modified: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class SearchOptimizationData(TypedDict):
    """The 'data' block of engine output."""
    keyword_analysis: list[KeywordAnalysisResult]
    meta_recommendations: list[MetaRecommendation]
    content_scores: list[ContentScore]
    sitemap: list[SitemapEntry]


class SearchOptimizationMeta(TypedDict):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class SearchOptimizationOutput(TypedDict):
    """Final output of the search optimization engine."""
    status: str
    data: SearchOptimizationData | None
    meta: SearchOptimizationMeta
    error: str | None
