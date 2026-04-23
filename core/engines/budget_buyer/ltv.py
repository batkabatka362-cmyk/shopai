"""Per-customer Lifetime Value tracker.

Ingests order events (customer_id, email, amount, ts),
aggregates into rolling per-customer totals, and segments
customers into VIP / regular / one-time / dormant tiers so
downstream engines (email campaigns, ad lookalike audiences)
can target tightly.

Pure stdlib. SQLite storage via :mod:`storage`. Math here is
deterministic given the same input stream — recency /
frequency / monetary (RFM-style) scoring without LLM calls.

Segmentation policy (§4a 95/5 rule — rules first, no LLM):

  * **VIP**       — ≥ 3 orders OR total_spent ≥ $300, active
                    within 90 days
  * **REGULAR**   — ≥ 2 orders, active within 180 days
  * **ONE_TIME**  — exactly 1 order, active within 365 days
  * **DORMANT**   — any customer with no order in 365+ days

Boundaries tuned for dropshipping — small AOV ($20-50), long
purchase-cycle gaps between novelty items.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

_logger = logging.getLogger("shopai.budget_buyer.ltv")


class LTVSegment(str, Enum):
    VIP = "vip"
    REGULAR = "regular"
    ONE_TIME = "one_time"
    DORMANT = "dormant"


@dataclass
class CustomerLTV:
    customer_id: str
    email: str
    orders_count: int
    total_spent_usd: float
    first_order_at: float   # unix ts
    last_order_at: float    # unix ts

    @property
    def aov_usd(self) -> float:
        """Average order value."""
        if self.orders_count <= 0:
            return 0.0
        return self.total_spent_usd / self.orders_count

    def days_since_last_order(
        self, *, now: float | None = None,
    ) -> float:
        t = float(now if now is not None else time.time())
        if self.last_order_at <= 0:
            return 0.0
        return max(0.0, (t - self.last_order_at) / 86400.0)

    def avg_days_between_orders(self) -> float:
        """Rolling average gap between orders — used by
        win-back scheduling."""
        if self.orders_count < 2:
            return 0.0
        span = max(
            0.0, self.last_order_at - self.first_order_at,
        )
        # N orders in span → N-1 gaps
        return (span / (self.orders_count - 1)) / 86400.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "email": self.email,
            "orders_count": self.orders_count,
            "total_spent_usd": round(self.total_spent_usd, 2),
            "aov_usd": round(self.aov_usd, 2),
            "first_order_at": round(self.first_order_at, 2),
            "last_order_at": round(self.last_order_at, 2),
            "days_since_last_order": round(
                self.days_since_last_order(), 1,
            ),
            "avg_days_between_orders": round(
                self.avg_days_between_orders(), 1,
            ),
        }


# ── Segmentation ─────────────────────────────────────────


_VIP_MIN_ORDERS = 3
_VIP_MIN_SPEND = 300.0
_VIP_RECENCY_DAYS = 90

_REGULAR_MIN_ORDERS = 2
_REGULAR_RECENCY_DAYS = 180

_ONE_TIME_RECENCY_DAYS = 365

_DORMANT_MIN_DAYS = 365


def classify(
    ltv: CustomerLTV, *, now: float | None = None,
) -> LTVSegment:
    """Assign an ``LTVSegment`` to a single customer. Rule-based
    — no LLM. Order of checks matters: VIP wins over REGULAR
    wins over ONE_TIME wins over DORMANT."""
    days_since = ltv.days_since_last_order(now=now)

    # DORMANT bucket is checked last — inactive VIPs stay VIP
    # for retargeting until the full 365-day window.
    if (
        (
            ltv.orders_count >= _VIP_MIN_ORDERS
            or ltv.total_spent_usd >= _VIP_MIN_SPEND
        )
        and days_since <= _VIP_RECENCY_DAYS
    ):
        return LTVSegment.VIP
    if (
        ltv.orders_count >= _REGULAR_MIN_ORDERS
        and days_since <= _REGULAR_RECENCY_DAYS
    ):
        return LTVSegment.REGULAR
    if (
        ltv.orders_count == 1
        and days_since <= _ONE_TIME_RECENCY_DAYS
    ):
        return LTVSegment.ONE_TIME
    return LTVSegment.DORMANT


# ── Aggregation (in-memory combine) ──────────────────────


def combine_orders(
    existing: CustomerLTV | None,
    email: str,
    amount_usd: float,
    ts: float,
    *,
    customer_id: str = "",
) -> CustomerLTV:
    """Merge a new order event into an existing LTV record (or
    create one if ``existing`` is None). Pure function — no
    side effects, testable."""
    if amount_usd < 0:
        raise ValueError(
            f"amount_usd must be >= 0 (got {amount_usd})",
        )
    if ts < 0:
        raise ValueError("ts must be >= 0")
    clean_email = (email or "").strip().lower()
    cid = customer_id or clean_email
    if not cid:
        raise ValueError(
            "customer_id or email is required",
        )

    if existing is None:
        return CustomerLTV(
            customer_id=cid,
            email=clean_email,
            orders_count=1,
            total_spent_usd=float(amount_usd),
            first_order_at=float(ts),
            last_order_at=float(ts),
        )

    # Preserve the original email if caller omitted one
    new_email = clean_email or existing.email
    return CustomerLTV(
        customer_id=existing.customer_id,
        email=new_email,
        orders_count=existing.orders_count + 1,
        total_spent_usd=existing.total_spent_usd + float(amount_usd),
        first_order_at=min(existing.first_order_at, float(ts)),
        last_order_at=max(existing.last_order_at, float(ts)),
    )


# ── LTVTracker (SQLite-backed) ───────────────────────────


from core.engines.budget_buyer.storage import LTVStorage


class LTVTracker:
    """Thin wrapper around :class:`LTVStorage` that enforces the
    combine-then-upsert pattern + surfaces segmentation.

    One instance per process; stateless beyond the DB it wraps.
    """

    def __init__(
        self,
        *,
        db_path: str = "data/ltv.db",
        now_fn: Any = None,
    ) -> None:
        self._storage = LTVStorage(db_path=db_path)
        self._now = now_fn or time.time

    def record_order(
        self,
        *,
        customer_id: str = "",
        email: str = "",
        amount_usd: float,
        ts: float | None = None,
    ) -> CustomerLTV:
        """Ingest one order. Idempotency is the caller's
        responsibility — this tracker just aggregates every
        call. Duplicate-event filtering lives upstream (order
        webhook's ``idempotency.db``)."""
        t = float(ts if ts is not None else self._now())
        cid_in = customer_id or email.strip().lower()
        existing = self._storage.get(cid_in) if cid_in else None
        merged = combine_orders(
            existing, email, amount_usd, t,
            customer_id=customer_id,
        )
        self._storage.upsert(merged)
        return merged

    def get(self, customer_id: str) -> CustomerLTV | None:
        return self._storage.get(customer_id)

    def segment(
        self, customer_id: str, *, now: float | None = None,
    ) -> LTVSegment | None:
        ltv = self._storage.get(customer_id)
        if ltv is None:
            return None
        return classify(ltv, now=now or self._now())

    def top_customers(
        self, *, limit: int = 20, by: str = "total_spent_usd",
    ) -> list[CustomerLTV]:
        return self._storage.top(limit=limit, by=by)

    def stats(
        self, *, now: float | None = None,
    ) -> dict[str, Any]:
        """Aggregate summary — total customers, segment split,
        avg / median LTV."""
        t = float(now if now is not None else self._now())
        all_rows = self._storage.all()
        seg_counts = {s.value: 0 for s in LTVSegment}
        for row in all_rows:
            seg_counts[classify(row, now=t).value] += 1
        total = len(all_rows)
        spends = sorted(row.total_spent_usd for row in all_rows)
        avg_ltv = (
            sum(spends) / total if total else 0.0
        )
        median_ltv = 0.0
        if spends:
            mid = len(spends) // 2
            median_ltv = (
                spends[mid]
                if len(spends) % 2
                else (spends[mid - 1] + spends[mid]) / 2
            )
        return {
            "total_customers": total,
            "segments": seg_counts,
            "avg_ltv_usd": round(avg_ltv, 2),
            "median_ltv_usd": round(median_ltv, 2),
            "total_gmv_usd": round(sum(spends), 2),
        }

    def list_by_segment(
        self,
        segment: LTVSegment,
        *,
        now: float | None = None,
        limit: int = 200,
    ) -> list[CustomerLTV]:
        t = float(now if now is not None else self._now())
        out = [
            r for r in self._storage.all()
            if classify(r, now=t) == segment
        ]
        # Sort by total_spent descending
        out.sort(
            key=lambda r: r.total_spent_usd, reverse=True,
        )
        return out[:limit]
