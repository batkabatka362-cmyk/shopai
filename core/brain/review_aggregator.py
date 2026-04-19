"""Review aggregator — normalise + dedup multi-source reviews.

Shopify native + Judge.me + Loox + imported CSV all talk about
the same product but output different shapes, different rating
scales, different timestamp formats. Without a normaliser the
brain can't answer 'what's the real product sentiment?' or
detect fake-review patterns across sources.

ReviewAggregator ingests reviews from any number of source
feeds, normalises the record into a common shape, dedupes across
sources (same customer + product + day + near-identical body),
and surfaces aggregates per product.

APIs:

  add_source(name, scale_max)   — declare the scale (5, 10, ...)
  ingest(source, records)       — raw dicts in that source's shape
  for_product(product_id)       → list[Review] sorted newest first
  aggregate(product_id)         → ProductReviewStats
  sentiment_flagged(product_id) → products with many low stars
  detect_fakes()                → review rows that look duplicated
  reset()

Pure stdlib. Normalises stars to the 0-5 scale. Deterministic.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class Review:
    review_id: str
    product_id: str
    customer_id: str
    stars: float                     # normalised 0..5
    body: str
    source: str
    created_at: float
    fingerprint: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "product_id": self.product_id,
            "customer_id": self.customer_id,
            "stars": round(self.stars, 2),
            "body": self.body,
            "source": self.source,
            "created_at": self.created_at,
            "fingerprint": self.fingerprint,
        }


@dataclass
class ProductReviewStats:
    product_id: str
    count: int = 0
    avg_stars: float = 0.0
    stdev_stars: float = 0.0
    low_count: int = 0          # <= 2 stars
    high_count: int = 0         # >= 4 stars
    sources: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "count": self.count,
            "avg_stars": round(self.avg_stars, 3),
            "stdev_stars": round(self.stdev_stars, 3),
            "low_count": self.low_count,
            "high_count": self.high_count,
            "sources": list(self.sources),
        }


# ── Helpers ────────────────────────────────────────────────

def _parse_ts(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        # Try ISO 8601 parsing; fall through to 0.0 on unparseable.
        try:
            return dt.datetime.fromisoformat(
                v.replace("Z", "+00:00"),
            ).timestamp()
        except ValueError:
            return 0.0
    return 0.0


_WS_RE = re.compile(r"\s+")


def _body_key(body: str) -> str:
    """Collapse whitespace and take first 80 chars for near-dup check."""
    cleaned = _WS_RE.sub(" ", (body or "").strip().lower())
    return cleaned[:80]


def _fingerprint(
    customer_id: str, product_id: str,
    created_at: float, body: str,
) -> str:
    day = int(created_at // 86_400) if created_at else 0
    key = f"{customer_id}|{product_id}|{day}|{_body_key(body)}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


# ── Aggregator ──────────────────────────────────────────────

class ReviewAggregator:
    def __init__(self) -> None:
        self._reviews: dict[str, Review] = {}
        self._scales: dict[str, float] = {}

    def add_source(self, name: str, scale_max: float) -> None:
        if not name or scale_max <= 0:
            raise ValueError("source name + positive scale required")
        self._scales[name] = float(scale_max)

    def sources(self) -> dict[str, float]:
        return dict(self._scales)

    def reset(self) -> None:
        self._reviews.clear()

    # ── Ingest ─────────────────────────────────────────────

    def ingest(
        self, source: str, records: Iterable[dict[str, Any]],
    ) -> int:
        if source not in self._scales:
            raise KeyError(f"source {source!r} not declared")
        scale = self._scales[source]
        n_added = 0
        for r in records:
            review = self._normalise(source, scale, r)
            if review is None:
                continue
            # Dedup on fingerprint: later writes lose to older records
            if review.fingerprint in self._reviews:
                continue
            self._reviews[review.fingerprint] = review
            n_added += 1
        return n_added

    def _normalise(
        self, source: str, scale: float, raw: dict[str, Any],
    ) -> Review | None:
        product_id = str(raw.get("product_id")
                           or raw.get("sku")
                           or "").strip()
        if not product_id:
            return None
        customer_id = str(
            raw.get("customer_id")
            or raw.get("email")
            or raw.get("author", ""),
        ).strip()
        body = str(
            raw.get("body")
            or raw.get("content")
            or raw.get("text", ""),
        )
        stars_raw = raw.get("stars") or raw.get("rating") or raw.get("score")
        try:
            stars = (float(stars_raw) / scale) * 5.0 if stars_raw else 0.0
        except (TypeError, ValueError):
            stars = 0.0
        stars = max(0.0, min(5.0, stars))
        created_at = _parse_ts(
            raw.get("created_at")
            or raw.get("timestamp")
            or raw.get("date"),
        )
        if created_at == 0.0:
            created_at = time.time()
        fingerprint = _fingerprint(
            customer_id, product_id, created_at, body,
        )
        review_id = str(
            raw.get("review_id") or raw.get("id")
            or fingerprint,
        )
        return Review(
            review_id=review_id,
            product_id=product_id,
            customer_id=customer_id,
            stars=stars,
            body=body,
            source=source,
            created_at=created_at,
            fingerprint=fingerprint,
        )

    # ── Queries ────────────────────────────────────────────

    def for_product(self, product_id: str) -> list[Review]:
        out = [
            r for r in self._reviews.values()
            if r.product_id == product_id
        ]
        out.sort(key=lambda r: -r.created_at)
        return out

    def aggregate(self, product_id: str) -> ProductReviewStats:
        reviews = self.for_product(product_id)
        stats = ProductReviewStats(product_id=product_id)
        if not reviews:
            return stats
        stats.count = len(reviews)
        stars = [r.stars for r in reviews]
        stats.avg_stars = sum(stars) / len(stars)
        if len(stars) >= 2:
            m = stats.avg_stars
            stats.stdev_stars = (
                sum((s - m) ** 2 for s in stars) / (len(stars) - 1)
            ) ** 0.5
        stats.low_count = sum(1 for s in stars if s <= 2)
        stats.high_count = sum(1 for s in stars if s >= 4)
        stats.sources = sorted({r.source for r in reviews})
        return stats

    def sentiment_flagged(
        self, min_reviews: int = 5, low_ratio: float = 0.3,
    ) -> list[ProductReviewStats]:
        by_product: dict[str, list[Review]] = defaultdict(list)
        for r in self._reviews.values():
            by_product[r.product_id].append(r)
        out: list[ProductReviewStats] = []
        for pid, rs in by_product.items():
            if len(rs) < min_reviews:
                continue
            stats = self.aggregate(pid)
            if stats.low_count / stats.count >= low_ratio:
                out.append(stats)
        out.sort(key=lambda s: -s.low_count / max(1, s.count))
        return out

    def detect_fakes(
        self, min_body_match: int = 2,
    ) -> list[list[Review]]:
        """Group reviews by body_key across (customer, product) pairs.
        Groups with ≥ min_body_match distinct customers using an
        identical body are flagged as coordinated-fake candidates."""
        buckets: dict[tuple[str, str], list[Review]] = defaultdict(list)
        for r in self._reviews.values():
            buckets[(r.product_id, _body_key(r.body))].append(r)
        out: list[list[Review]] = []
        for (_, body_key), group in buckets.items():
            if not body_key:
                continue
            distinct_customers = {
                r.customer_id for r in group if r.customer_id
            }
            if len(distinct_customers) >= min_body_match:
                out.append(group)
        return out

    def stats(self) -> dict[str, Any]:
        by_source: dict[str, int] = defaultdict(int)
        for r in self._reviews.values():
            by_source[r.source] += 1
        return {
            "total_reviews": len(self._reviews),
            "sources_declared": list(self._scales.keys()),
            "reviews_by_source": dict(by_source),
        }
