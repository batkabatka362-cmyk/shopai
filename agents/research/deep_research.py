"""Deep research agent — reviews + sentiment + competitor matrix.

Track 7 of AGI_HARDENING_PLAN. WinnerSearcher finds products
from supplier catalogues; this module enriches each candidate
with *qualitative* signals: review sentiment (happy customers?
product defects mentioned?), competitor pricing (how much does
the same product cost elsewhere?), review volume (how much
aggregate interest?).

Pass 1 is LLM-free: keyword-based sentiment + rule-driven
competitor summarisation. Plenty of signal for ranking without
spending LLM credits per candidate. An LLM can later replace
the sentiment lexicon for edge cases.

Fetch layer is injectable (``review_source``, ``search_source``)
so the module is offline-testable and resilient to any single
provider going down.

Pure stdlib. Deterministic. Thread-safe (RLock).
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("agents.research.deep_research")


# Keyword lexicons — small, deterministic, auditable. LLM can
# replace these when budget allows.
_POS_TOKENS = (
    "love", "great", "excellent", "amazing", "perfect",
    "best", "awesome", "quality", "fast shipping",
    "recommend", "happy", "works", "value", "easy",
    "beautiful", "comfortable", "sturdy", "solid",
    "as described", "exceeded",
)
_NEG_TOKENS = (
    "broke", "broken", "cheap", "flimsy", "defect",
    "defective", "poor quality", "disappointed", "returned",
    "refund", "waste", "terrible", "awful", "scam",
    "fake", "damaged", "slow shipping", "not as described",
    "stopped working", "junk",
)
_DEFECT_TOKENS = (
    "broke", "broken", "defect", "defective", "stopped working",
    "damaged on arrival", "malfunction", "doesn't work",
    "quality control",
)


@dataclass
class ReviewSummary:
    review_count: int
    positive: int
    negative: int
    neutral: int
    defect_mentions: int
    sample_pos_snippets: tuple[str, ...] = ()
    sample_neg_snippets: tuple[str, ...] = ()

    @property
    def sentiment_score(self) -> float:
        total = self.positive + self.negative
        if total == 0:
            return 0.5
        return self.positive / total

    @property
    def defect_rate(self) -> float:
        if self.review_count == 0:
            return 0.0
        return self.defect_mentions / self.review_count

    def as_dict(self) -> dict[str, Any]:
        return {
            "review_count": self.review_count,
            "positive": self.positive,
            "negative": self.negative,
            "neutral": self.neutral,
            "defect_mentions": self.defect_mentions,
            "sentiment_score": round(
                self.sentiment_score, 4,
            ),
            "defect_rate": round(self.defect_rate, 4),
            "sample_pos": list(self.sample_pos_snippets),
            "sample_neg": list(self.sample_neg_snippets),
        }


@dataclass
class CompetitorPrice:
    source: str
    url: str
    price: float
    currency: str = "USD"
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "url": self.url,
            "price": round(self.price, 2),
            "currency": self.currency,
            "note": self.note,
        }


@dataclass
class DeepResearchReport:
    query: str
    review_summary: ReviewSummary | None
    competitor_prices: tuple[CompetitorPrice, ...]
    median_competitor_price: float = 0.0
    ts: float = 0.0
    notes: tuple[str, ...] = ()

    @property
    def verdict(self) -> str:
        if self.review_summary is None:
            return "inconclusive"
        if self.review_summary.review_count < 10:
            return "insufficient_reviews"
        if self.review_summary.defect_rate > 0.10:
            return "avoid_defect_risk"
        if self.review_summary.sentiment_score < 0.55:
            return "mixed_sentiment"
        if (
            self.median_competitor_price > 0
            and self.review_summary.sentiment_score >= 0.70
        ):
            return "competitive_opportunity"
        return "ok"

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "review_summary": (
                self.review_summary.as_dict()
                if self.review_summary else None
            ),
            "competitor_prices": [
                c.as_dict() for c in self.competitor_prices
            ],
            "median_competitor_price": round(
                self.median_competitor_price, 2,
            ),
            "verdict": self.verdict,
            "ts": self.ts,
            "notes": list(self.notes),
        }


# ── Sentiment ──────────────────────────────────────────────


def _count_hits(
    text: str, tokens: Iterable[str],
) -> int:
    t = (text or "").lower()
    return sum(1 for tok in tokens if tok in t)


def classify_review(
    text: str,
) -> tuple[str, int]:
    """Return (label, defect_mentions). Label ∈
    {positive, negative, neutral}."""
    pos = _count_hits(text, _POS_TOKENS)
    neg = _count_hits(text, _NEG_TOKENS)
    defects = _count_hits(text, _DEFECT_TOKENS)
    if pos > neg and pos >= 1:
        return "positive", defects
    if neg > pos and neg >= 1:
        return "negative", defects
    return "neutral", defects


def summarise_reviews(
    reviews: Iterable[dict[str, Any] | str],
    *,
    sample_snippets: int = 3,
) -> ReviewSummary:
    """Classify each review with the keyword lexicon and roll
    up counts + sample snippets."""
    pos_count = neg_count = neu_count = defects = total = 0
    pos_samples: list[str] = []
    neg_samples: list[str] = []
    for r in reviews or []:
        text = (
            r.get("text")
            if isinstance(r, dict)
            else str(r or "")
        )
        if not text:
            continue
        total += 1
        label, d = classify_review(text)
        defects += d
        if label == "positive":
            pos_count += 1
            if len(pos_samples) < sample_snippets:
                pos_samples.append(text[:140])
        elif label == "negative":
            neg_count += 1
            if len(neg_samples) < sample_snippets:
                neg_samples.append(text[:140])
        else:
            neu_count += 1
    return ReviewSummary(
        review_count=total,
        positive=pos_count,
        negative=neg_count,
        neutral=neu_count,
        defect_mentions=defects,
        sample_pos_snippets=tuple(pos_samples),
        sample_neg_snippets=tuple(neg_samples),
    )


# ── Competitor helpers ─────────────────────────────────────


_PRICE_RE = re.compile(r"\$(\d+(?:\.\d{1,2})?)")


def extract_competitor_price(
    *,
    source: str,
    url: str,
    text: str,
) -> CompetitorPrice | None:
    match = _PRICE_RE.search(text or "")
    if not match:
        return None
    try:
        price = float(match.group(1))
    except ValueError:
        return None
    if price <= 0:
        return None
    return CompetitorPrice(
        source=source,
        url=url,
        price=price,
        note=text[:80],
    )


# ── Main agent ─────────────────────────────────────────────


class DeepResearchAgent:
    """Coordinates review fetch + competitor scan for a query."""

    def __init__(
        self,
        *,
        review_source: Any = None,
        search_source: Any = None,
        now_fn: Any = None,
    ) -> None:
        self._review_source = review_source
        self._search_source = search_source
        self._now_fn = now_fn or time.time
        self._lock = threading.RLock()

    def investigate(
        self,
        query: str,
        *,
        review_limit: int = 50,
        competitor_limit: int = 5,
    ) -> DeepResearchReport:
        if not query:
            raise ValueError("query required")
        notes: list[str] = []
        review_summary: ReviewSummary | None = None
        if self._review_source is not None:
            try:
                reviews = self._review_source(
                    query, limit=review_limit,
                ) or []
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "review_source raised: %s", exc,
                )
                reviews = []
                notes.append(f"review_source error: {exc}")
            review_summary = summarise_reviews(reviews)
        competitors: list[CompetitorPrice] = []
        if self._search_source is not None:
            try:
                hits = self._search_source(
                    query, limit=competitor_limit,
                ) or []
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "search_source raised: %s", exc,
                )
                hits = []
                notes.append(
                    f"search_source error: {exc}",
                )
            for h in hits:
                if not isinstance(h, dict):
                    continue
                cp = extract_competitor_price(
                    source=str(h.get("source", "web")),
                    url=str(h.get("url", "")),
                    text=str(
                        h.get("snippet")
                        or h.get("text", ""),
                    ),
                )
                if cp is not None:
                    competitors.append(cp)
        prices = sorted(
            c.price for c in competitors if c.price > 0
        )
        median = (
            prices[len(prices) // 2] if prices else 0.0
        )
        return DeepResearchReport(
            query=str(query),
            review_summary=review_summary,
            competitor_prices=tuple(competitors),
            median_competitor_price=median,
            ts=float(self._now_fn()),
            notes=tuple(notes),
        )
