"""BudgetBuyerEngine — public surface.

Thin orchestration layer over ``BudgetAllocator`` + ``LTVTracker``.
One singleton per process. Injectable config for tests.

Public surface::

    from core.engines.budget_buyer import get_engine

    engine = get_engine()

    # Record orders as webhooks arrive
    engine.record_order(
        customer_id="c_123", email="jane@x.com",
        amount_usd=29.99, ts=...,
    )

    # Ask for ad budget split
    plan = engine.allocate_budget(
        total_daily_usd=100.0,
        performance=[SKUPerformance(...), ...],
    )
    # → list[BudgetAllocation]

    # Owner inspects
    engine.ltv_stats()
    engine.top_customers()
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from core.engines.budget_buyer.allocator import (
    BudgetAllocation, BudgetAllocator, SKUPerformance,
)
from core.engines.budget_buyer.ltv import (
    CustomerLTV, LTVSegment, LTVTracker,
)

_logger = logging.getLogger("shopai.budget_buyer.engine")


class BudgetBuyerEngine:
    """Orchestrates the ad allocator + LTV tracker.

    Thread-safe; stateless beyond the two underlying stores
    (in-memory for the allocator, SQLite for the LTV tracker).
    Constructor accepts injectable pieces for tests.
    """

    def __init__(
        self,
        *,
        ltv_tracker: LTVTracker | None = None,
        allocator: BudgetAllocator | None = None,
        now_fn: Any = None,
    ) -> None:
        self._ltv = ltv_tracker or LTVTracker()
        self._allocator = allocator or BudgetAllocator()
        self._now = now_fn or time.time

    # ── LTV ─────────────────────────────────────────────

    def record_order(
        self,
        *,
        customer_id: str = "",
        email: str = "",
        amount_usd: float,
        ts: float | None = None,
    ) -> CustomerLTV:
        """Ingest one order event. See
        ``LTVTracker.record_order`` for idempotency notes."""
        return self._ltv.record_order(
            customer_id=customer_id, email=email,
            amount_usd=amount_usd, ts=ts,
        )

    def get_customer(
        self, customer_id: str,
    ) -> CustomerLTV | None:
        return self._ltv.get(customer_id)

    def segment_customer(
        self, customer_id: str,
    ) -> LTVSegment | None:
        return self._ltv.segment(customer_id)

    def top_customers(
        self, *, limit: int = 20, by: str = "total_spent_usd",
    ) -> list[CustomerLTV]:
        return self._ltv.top_customers(
            limit=limit, by=by,
        )

    def ltv_stats(self) -> dict[str, Any]:
        return self._ltv.stats()

    def vip_customers(
        self, *, limit: int = 200,
    ) -> list[CustomerLTV]:
        return self._ltv.list_by_segment(
            LTVSegment.VIP, limit=limit,
        )

    def dormant_customers(
        self, *, limit: int = 200,
    ) -> list[CustomerLTV]:
        """For win-back flow enrolment."""
        return self._ltv.list_by_segment(
            LTVSegment.DORMANT, limit=limit,
        )

    # ── Budget allocation ───────────────────────────────

    def allocate_budget(
        self,
        *,
        total_daily_usd: float,
        performance: list[SKUPerformance],
        min_per_sku_usd: float = 0.0,
        max_per_sku_usd: float | None = None,
    ) -> list[BudgetAllocation]:
        return self._allocator.allocate(
            total_daily_usd, performance,
            min_per_sku_usd=min_per_sku_usd,
            max_per_sku_usd=max_per_sku_usd,
        )


# ── Singleton ────────────────────────────────────────────


_SINGLETON: BudgetBuyerEngine | None = None
_SINGLETON_LOCK = threading.Lock()


def get_engine() -> BudgetBuyerEngine:
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = BudgetBuyerEngine()
    return _SINGLETON


def reset_singleton_for_tests() -> None:
    global _SINGLETON
    with _SINGLETON_LOCK:
        _SINGLETON = None
