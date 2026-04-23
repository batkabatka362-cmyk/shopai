"""Budget + Buyer engine — ad budget allocator + LTV tracker.

Third of the 4 HIGH-priority logic engines owner identified
(budget/buyer, AutoDS ✓, suppliers, email ✓). Two tightly-
coupled responsibilities share this package because both are
fuelled by the same order + ad-spend stream:

  * **allocator.py** — given each SKU's recent performance
    (orders, revenue, ad spend), recommend how to split the
    total daily ad budget. Thompson Sampling (multi-armed
    bandit) for exploration/exploitation balance. Pure math
    — no LLM, deterministic given the same random seed.

  * **ltv.py** — per-customer Lifetime Value tracker. Ingests
    order events, aggregates orders_count / total_spent /
    recency. Segments customers into VIP / regular / one-time
    so win-back flows + VIP-only campaigns can target tightly.

  * **engine.py** — public surface. One singleton orchestrates
    both. Autopilot cycle feeds orders → LTV, periodically
    calls allocator with recent SKU performance.

Architecture (per owner's CORE/COMMODITY frame):

  * CORE (ours):  Thompson Sampling + LTV math + segmentation
                  rules. All determinism, no vendor lock.
  * COMMODITY:    Meta Ads + Shopify order data ingest — data
                  adapters already exist, this engine just
                  consumes normalised records.
  * WIRING (opt): autopilot cycle hook; CLI; MCP tools.

Usage::

    from core.engines.budget_buyer import get_engine

    engine = get_engine()

    # 1. Stream orders from webhook into LTV tracker
    engine.record_order(
        customer_id="c_123", email="jane@x.com",
        amount_usd=29.99, ts=...,
    )

    # 2. Feed SKU performance + ask for allocation
    report = engine.allocate_budget(
        total_daily_usd=100,
        skus=[SKUPerformance(...)],
    )
    # → [{"sku": "galaxy-projector", "recommended_usd": 45, ...}]

    # 3. Owner inspects
    engine.ltv_stats()
    # → {"total_customers": N, "vips": M, "avg_ltv_usd": X, ...}

Pure stdlib math (``random`` + ``statistics``). No SciPy, no
numpy — ShopAI should run on a plain Python install.
"""
from core.engines.budget_buyer.allocator import (
    BudgetAllocation,
    BudgetAllocator,
    SKUPerformance,
)
from core.engines.budget_buyer.engine import (
    BudgetBuyerEngine,
    get_engine,
    reset_singleton_for_tests,
)
from core.engines.budget_buyer.ltv import (
    CustomerLTV,
    LTVSegment,
    LTVTracker,
)

__all__ = [
    "BudgetAllocation",
    "BudgetAllocator",
    "BudgetBuyerEngine",
    "CustomerLTV",
    "LTVSegment",
    "LTVTracker",
    "SKUPerformance",
    "get_engine",
    "reset_singleton_for_tests",
]
