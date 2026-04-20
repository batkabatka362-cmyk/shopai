"""Trend scorer — turns a Google Trends adapter into a niche
multiplier.

Sprint 3 S3-3 follow-up (iter 4b). ``NicheDiscoverer`` optionally
accepts a ``trend_scorer`` callable that, given a niche label and
its keyword tokens, returns a score in [0, 1] measuring how strongly
external trending searches match the niche.

This module provides the default factory:

  >>> from core.adapters.trends import GoogleTrendsAdapter
  >>> scorer = make_google_trends_scorer(GoogleTrendsAdapter())
  >>> discoverer = NicheDiscoverer(trend_scorer=scorer)

The scorer counts how many of the top-N trending searches contain
any of the niche's tokens as a substring, divided by N. A niche
with 5/20 matches gets 0.25; 0 matches gets 0.0; all 20 get 1.0.

Failure handling: adapter fetch errors or empty results degrade
silently to 0.0 so niche ranking is never blocked by a Google
Trends outage.

Pure stdlib. LLM-free.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

from utils.logger import get_logger


logger = get_logger("agents.research.trend_scorer")


TrendScorer = Callable[[str, tuple[str, ...]], float]


def make_google_trends_scorer(
    adapter: Any,
    *,
    geo: str = "US",
    top_n: int = 20,
    eu_weight: float = 0.0,
) -> TrendScorer:
    """Return a trend scorer that uses Google Trends daily-search.

    If ``eu_weight`` > 0 the final score is a weighted blend of the
    US score and an EU score (useful when targeting both markets):

        score = (1 - eu_weight) * us_score + eu_weight * eu_score
    """
    eu = max(0.0, min(1.0, float(eu_weight)))

    def _ratio(trends: Iterable[Any], tokens: set[str]) -> float:
        trends_list = list(trends or [])
        if not trends_list:
            return 0.0
        hits = 0
        for t in trends_list:
            kw = str(getattr(t, "keyword", "") or "").lower()
            if not kw:
                continue
            if any(tok in kw for tok in tokens):
                hits += 1
        return min(1.0, hits / len(trends_list))

    def score(label: str, tokens: tuple[str, ...]) -> float:
        toks = {
            t.strip().lower() for t in (tokens or ())
            if t and t.strip()
        }
        if not toks:
            return 0.0
        try:
            us = _ratio(
                adapter.top_searches(geo=geo, limit=top_n),
                toks,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "google trends US score failed: %s", exc,
            )
            us = 0.0
        if eu <= 0:
            return us
        try:
            eu_score = _ratio(
                adapter.top_searches(geo="EU", limit=top_n),
                toks,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "google trends EU score failed: %s", exc,
            )
            eu_score = 0.0
        return (1.0 - eu) * us + eu * eu_score

    return score
