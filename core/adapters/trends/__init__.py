"""Trend signal adapters (L2 perception). See docs/AGI_STACK.md."""
from core.adapters.trends.google_trends import (
    GoogleTrendsAdapter,
    TrendingSearch,
)

__all__ = ["GoogleTrendsAdapter", "TrendingSearch"]
