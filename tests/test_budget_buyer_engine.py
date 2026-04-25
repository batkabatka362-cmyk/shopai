"""Unit + integration tests for core/engines/budget_buyer/.

Covers:
  * SKUPerformance invariants + derived metrics (ROAS / CVR /
    CPC / daily_orders)
  * BudgetAllocator — empty input, zero budget, every-SKU-
    new fallback (equal split), Thompson favouring winners,
    floor/cap clamping, renormalisation sum invariant
  * LTV — combine_orders pure function, classify rules (VIP /
    REGULAR / ONE_TIME / DORMANT) + boundary conditions
  * LTVStorage — upsert idempotency, get missing → None, top
    sort orders, invalid sort column rejected
  * LTVTracker — record_order integration, stats shape, list
    by segment
  * BudgetBuyerEngine — record_order pipeline, allocate_budget
    smoke, singleton identity

Pure stdlib. Thompson tests pin the RNG seed so results are
deterministic.
"""
from __future__ import annotations

import pytest

from core.engines.budget_buyer import (
    BudgetAllocation, BudgetAllocator, BudgetBuyerEngine,
    CustomerLTV, LTVSegment, LTVTracker, SKUPerformance,
    get_engine, reset_singleton_for_tests,
)
from core.engines.budget_buyer.ltv import (
    classify, combine_orders,
)
from core.engines.budget_buyer.storage import LTVStorage


# ── SKUPerformance ───────────────────────────────────────


class TestSKUPerformance:
    def test_basic_fields(self):
        p = SKUPerformance(
            sku="galaxy", orders=10, revenue_usd=250.0,
            ad_spend_usd=50.0, clicks=200, impressions=10_000,
            days_active=7,
        )
        assert p.roas() == 5.0
        assert p.cvr() == 0.05
        assert p.cpc() == 0.25
        assert p.daily_orders() == pytest.approx(10 / 7)

    def test_zero_ad_spend_roas_zero(self):
        p = SKUPerformance(sku="x", orders=5, revenue_usd=100)
        assert p.roas() == 0.0

    def test_zero_clicks_cvr_zero(self):
        p = SKUPerformance(sku="x", orders=5)
        assert p.cvr() == 0.0
        assert p.cpc() == 0.0

    def test_missing_sku_raises(self):
        with pytest.raises(ValueError, match="sku"):
            SKUPerformance(sku="")

    def test_negative_revenue_raises(self):
        with pytest.raises(ValueError):
            SKUPerformance(sku="x", revenue_usd=-1)

    def test_zero_days_active_raises(self):
        with pytest.raises(ValueError):
            SKUPerformance(sku="x", days_active=0)


# ── BudgetAllocator ──────────────────────────────────────


class TestBudgetAllocatorEdgeCases:
    def test_empty_performance_returns_empty(self):
        a = BudgetAllocator(seed=1)
        assert a.allocate(100, []) == []

    def test_zero_budget_all_zero(self):
        a = BudgetAllocator(seed=1)
        perf = [
            SKUPerformance(sku="a", orders=10, revenue_usd=100, ad_spend_usd=20),
        ]
        allocs = a.allocate(0.0, perf)
        assert len(allocs) == 1
        assert allocs[0].recommended_daily_usd == 0.0
        assert "zero" in allocs[0].reason.lower()

    def test_negative_budget_raises(self):
        a = BudgetAllocator(seed=1)
        with pytest.raises(ValueError):
            a.allocate(-1.0, [SKUPerformance(sku="x")])

    def test_all_new_skus_equal_split(self):
        """No SKU has enough data — all go into exploration
        pool + get equal shares."""
        a = BudgetAllocator(seed=1, min_samples=5)
        perf = [
            SKUPerformance(
                sku=s, orders=2, revenue_usd=40,
                ad_spend_usd=30,
            )
            for s in ("a", "b", "c", "d")
        ]
        allocs = a.allocate(100.0, perf)
        shares = [a.recommended_daily_usd for a in allocs]
        # All equal within float noise
        for s in shares:
            assert abs(s - 25.0) < 0.01
        assert all(
            "exploration" in a.reason for a in allocs
        )


class TestBudgetAllocatorThompson:
    def test_winner_gets_larger_share(self):
        """SKU with 10× higher ROAS gets substantially more
        budget than the laggard."""
        a = BudgetAllocator(seed=42, min_samples=5)
        perf = [
            SKUPerformance(
                sku="winner", orders=50, revenue_usd=2000,
                ad_spend_usd=200, days_active=7,
            ),
            SKUPerformance(
                sku="loser", orders=20, revenue_usd=200,
                ad_spend_usd=400, days_active=7,
            ),
        ]
        allocs = a.allocate(100.0, perf)
        winner = [x for x in allocs if x.sku == "winner"][0]
        loser = [x for x in allocs if x.sku == "loser"][0]
        assert winner.recommended_daily_usd > loser.recommended_daily_usd
        # Should be at least 2× more
        assert (
            winner.recommended_daily_usd
            > loser.recommended_daily_usd * 2
        )

    def test_seed_reproducibility(self):
        perf = [
            SKUPerformance(
                sku="a", orders=30, revenue_usd=600,
                ad_spend_usd=100, days_active=7,
            ),
            SKUPerformance(
                sku="b", orders=20, revenue_usd=200,
                ad_spend_usd=200, days_active=7,
            ),
        ]
        a1 = BudgetAllocator(seed=12345)
        a2 = BudgetAllocator(seed=12345)
        allocs1 = a1.allocate(100.0, perf)
        allocs2 = a2.allocate(100.0, perf)
        for x, y in zip(allocs1, allocs2):
            assert (
                x.recommended_daily_usd
                == y.recommended_daily_usd
            )

    def test_sum_equals_total(self):
        a = BudgetAllocator(seed=7, min_samples=3)
        perf = [
            SKUPerformance(
                sku="a", orders=10, revenue_usd=200,
                ad_spend_usd=50, days_active=7,
            ),
            SKUPerformance(
                sku="b", orders=15, revenue_usd=300,
                ad_spend_usd=60, days_active=7,
            ),
            SKUPerformance(
                sku="new", orders=1, days_active=1,
            ),
        ]
        allocs = a.allocate(100.0, perf)
        total = sum(x.recommended_daily_usd for x in allocs)
        assert abs(total - 100.0) < 0.01

    def test_mixed_new_and_tested(self):
        """Exploration reserve goes to the new SKU; exploit
        pool splits across the tested ones."""
        a = BudgetAllocator(
            seed=42, min_samples=5,
            exploration_reserve_pct=0.25,
        )
        perf = [
            SKUPerformance(
                sku="tested_hot", orders=30, revenue_usd=600,
                ad_spend_usd=100, days_active=7,
            ),
            SKUPerformance(
                sku="new_1", orders=1, revenue_usd=20,
                ad_spend_usd=10, days_active=1,
            ),
        ]
        allocs = a.allocate(100.0, perf)
        new_alloc = [x for x in allocs if x.sku == "new_1"][0]
        # 25% reserve / 1 new SKU → $25 for the new one
        assert new_alloc.recommended_daily_usd == pytest.approx(
            25.0, abs=0.01,
        )


class TestBudgetAllocatorFloorCap:
    def test_floor_applied(self):
        """``min_per_sku_usd`` enforces a spending floor on every
        SKU — useful to keep the long tail alive."""
        a = BudgetAllocator(seed=1, min_samples=5)
        perf = [
            SKUPerformance(
                sku="winner", orders=100, revenue_usd=5000,
                ad_spend_usd=100, days_active=7,
            ),
            SKUPerformance(
                sku="dog", orders=10, revenue_usd=50,
                ad_spend_usd=300, days_active=7,
            ),
        ]
        allocs = a.allocate(
            100.0, perf, min_per_sku_usd=15.0,
        )
        dog = [x for x in allocs if x.sku == "dog"][0]
        assert dog.recommended_daily_usd >= 15.0 - 0.01

    def test_cap_applied(self):
        """``max_per_sku_usd`` caps any runaway winner."""
        a = BudgetAllocator(seed=1, min_samples=3)
        perf = [
            SKUPerformance(
                sku="star", orders=100, revenue_usd=20_000,
                ad_spend_usd=100, days_active=7,
            ),
            SKUPerformance(
                sku="ok", orders=10, revenue_usd=100,
                ad_spend_usd=50, days_active=7,
            ),
        ]
        allocs = a.allocate(
            100.0, perf, max_per_sku_usd=40.0,
        )
        star = [x for x in allocs if x.sku == "star"][0]
        assert star.recommended_daily_usd <= 40.0 + 0.01

    def test_cap_renormalises(self):
        """When the cap steals budget from the winner, the
        leftover flows to the remaining SKUs rather than
        disappearing. With 3 SKUs + cap=40, a $100 budget is
        fully achievable (winner=40, others absorb the $60)."""
        a = BudgetAllocator(seed=1, min_samples=3)
        perf = [
            SKUPerformance(
                sku="star", orders=100, revenue_usd=20_000,
                ad_spend_usd=100, days_active=7,
            ),
            SKUPerformance(
                sku="ok", orders=10, revenue_usd=100,
                ad_spend_usd=50, days_active=7,
            ),
            SKUPerformance(
                sku="mid", orders=15, revenue_usd=200,
                ad_spend_usd=80, days_active=7,
            ),
        ]
        allocs = a.allocate(
            100.0, perf, max_per_sku_usd=40.0,
        )
        total = sum(x.recommended_daily_usd for x in allocs)
        # Renormalised back to near the full $100
        assert abs(total - 100.0) < 0.5
        # Star capped at 40
        star = [x for x in allocs if x.sku == "star"][0]
        assert star.recommended_daily_usd <= 40.0 + 0.01


# ── LTV combine_orders (pure) ──────────────────────────


class TestCombineOrders:
    def test_first_order_creates_record(self):
        ltv = combine_orders(
            None, email="jane@x.com",
            amount_usd=29.99, ts=1000.0,
        )
        assert ltv.orders_count == 1
        assert ltv.total_spent_usd == 29.99
        assert ltv.first_order_at == 1000.0
        assert ltv.last_order_at == 1000.0
        assert ltv.email == "jane@x.com"

    def test_second_order_merges(self):
        first = combine_orders(
            None, email="jane@x.com", amount_usd=20.0,
            ts=1000.0,
        )
        merged = combine_orders(
            first, email="jane@x.com", amount_usd=50.0,
            ts=2000.0,
        )
        assert merged.orders_count == 2
        assert merged.total_spent_usd == 70.0
        assert merged.first_order_at == 1000.0
        assert merged.last_order_at == 2000.0

    def test_out_of_order_ts_handled(self):
        """Orders arriving out-of-order (replay, late webhook)
        shouldn't corrupt first/last timestamps."""
        first = combine_orders(
            None, email="jane@x.com", amount_usd=20.0,
            ts=2000.0,
        )
        merged = combine_orders(
            first, email="jane@x.com", amount_usd=30.0,
            ts=1000.0,  # earlier!
        )
        assert merged.first_order_at == 1000.0
        assert merged.last_order_at == 2000.0

    def test_case_normalized_email(self):
        ltv = combine_orders(
            None, email="Jane@Example.COM",
            amount_usd=10.0, ts=0.0,
        )
        assert ltv.email == "jane@example.com"

    def test_missing_id_raises(self):
        with pytest.raises(ValueError):
            combine_orders(
                None, email="", amount_usd=10.0, ts=0.0,
            )

    def test_negative_amount_raises(self):
        with pytest.raises(ValueError):
            combine_orders(
                None, email="a@b.c",
                amount_usd=-5.0, ts=0.0,
            )


# ── CustomerLTV derived metrics ────────────────────────


class TestCustomerLTVDerived:
    def test_aov(self):
        ltv = CustomerLTV(
            customer_id="c", email="a@b.c",
            orders_count=3, total_spent_usd=90.0,
            first_order_at=0, last_order_at=0,
        )
        assert ltv.aov_usd == 30.0

    def test_zero_orders_aov_zero(self):
        ltv = CustomerLTV(
            customer_id="c", email="a@b.c",
            orders_count=0, total_spent_usd=0,
            first_order_at=0, last_order_at=0,
        )
        assert ltv.aov_usd == 0.0

    def test_days_since_last_order(self):
        ltv = CustomerLTV(
            customer_id="c", email="a@b.c",
            orders_count=1, total_spent_usd=20,
            first_order_at=0, last_order_at=1_700_000_000.0,
        )
        # 10 days later
        days = ltv.days_since_last_order(
            now=1_700_000_000.0 + 10 * 86400,
        )
        assert days == pytest.approx(10.0, abs=0.01)

    def test_avg_days_between_orders(self):
        ltv = CustomerLTV(
            customer_id="c", email="a@b.c",
            orders_count=3, total_spent_usd=60,
            first_order_at=0,
            last_order_at=20 * 86400,  # 20 days span
        )
        # 3 orders in 20 days → 2 gaps → 10 days avg
        assert ltv.avg_days_between_orders() == pytest.approx(
            10.0, abs=0.01,
        )


# ── Segmentation ───────────────────────────────────────


class TestClassify:
    def _ltv(self, *, orders, spent, days_ago):
        now = 1_700_000_000.0
        return CustomerLTV(
            customer_id="c", email="a@b.c",
            orders_count=orders, total_spent_usd=spent,
            first_order_at=now - days_ago * 86400,
            last_order_at=now - days_ago * 86400,
        ), now

    def test_vip_by_orders(self):
        ltv, now = self._ltv(
            orders=3, spent=100, days_ago=10,
        )
        assert classify(ltv, now=now) == LTVSegment.VIP

    def test_vip_by_spend(self):
        """Big-ticket one-time buyer counts as VIP."""
        ltv, now = self._ltv(
            orders=1, spent=500, days_ago=10,
        )
        assert classify(ltv, now=now) == LTVSegment.VIP

    def test_vip_goes_dormant_after_90_days(self):
        ltv, now = self._ltv(
            orders=3, spent=100, days_ago=120,
        )
        # Not VIP anymore — but still REGULAR (within 180d)
        assert classify(ltv, now=now) == LTVSegment.REGULAR

    def test_regular(self):
        ltv, now = self._ltv(
            orders=2, spent=50, days_ago=30,
        )
        assert classify(ltv, now=now) == LTVSegment.REGULAR

    def test_one_time_recent(self):
        ltv, now = self._ltv(
            orders=1, spent=25, days_ago=30,
        )
        assert classify(ltv, now=now) == LTVSegment.ONE_TIME

    def test_one_time_dormant(self):
        ltv, now = self._ltv(
            orders=1, spent=25, days_ago=400,
        )
        assert classify(ltv, now=now) == LTVSegment.DORMANT


# ── LTVStorage ─────────────────────────────────────────


@pytest.fixture
def storage(tmp_path):
    return LTVStorage(db_path=str(tmp_path / "ltv.db"))


class TestLTVStorage:
    def test_upsert_then_get(self, storage):
        ltv = CustomerLTV(
            customer_id="c1", email="a@b.c",
            orders_count=1, total_spent_usd=25,
            first_order_at=100, last_order_at=100,
        )
        storage.upsert(ltv)
        fetched = storage.get("c1")
        assert fetched.email == "a@b.c"
        assert fetched.total_spent_usd == 25

    def test_upsert_merges_timestamps(self, storage):
        """Second upsert with different first_order_at —
        storage takes the MIN / MAX."""
        ltv_a = CustomerLTV(
            customer_id="c1", email="a@b.c",
            orders_count=1, total_spent_usd=10,
            first_order_at=200.0, last_order_at=200.0,
        )
        storage.upsert(ltv_a)
        ltv_b = CustomerLTV(
            customer_id="c1", email="a@b.c",
            orders_count=2, total_spent_usd=30,
            first_order_at=100.0, last_order_at=300.0,
        )
        storage.upsert(ltv_b)
        fetched = storage.get("c1")
        assert fetched.first_order_at == 100.0
        assert fetched.last_order_at == 300.0
        assert fetched.total_spent_usd == 30

    def test_get_missing_returns_none(self, storage):
        assert storage.get("does-not-exist") is None

    def test_top_orders_by_spend(self, storage):
        for i, spend in enumerate([10, 500, 50, 200]):
            storage.upsert(CustomerLTV(
                customer_id=f"c{i}", email=f"c{i}@x.c",
                orders_count=1, total_spent_usd=spend,
                first_order_at=0, last_order_at=0,
            ))
        top = storage.top(limit=2)
        assert [x.total_spent_usd for x in top] == [500, 200]

    def test_invalid_sort_column_raises(self, storage):
        with pytest.raises(ValueError):
            storage.top(by="DROP TABLE")

    def test_persistence_survives_reopen(self, tmp_path):
        path = str(tmp_path / "ltv.db")
        s1 = LTVStorage(db_path=path)
        s1.upsert(CustomerLTV(
            customer_id="c1", email="a@b.c",
            orders_count=1, total_spent_usd=25,
            first_order_at=100, last_order_at=100,
        ))
        s2 = LTVStorage(db_path=path)
        assert s2.get("c1").total_spent_usd == 25


# ── LTVTracker ─────────────────────────────────────────


@pytest.fixture
def tracker(tmp_path):
    return LTVTracker(
        db_path=str(tmp_path / "ltv.db"),
        now_fn=lambda: 1_700_000_000.0,
    )


class TestLTVTracker:
    def test_record_order_builds_customer(self, tracker):
        row = tracker.record_order(
            email="jane@x.com", amount_usd=29.99,
        )
        assert row.orders_count == 1
        assert row.total_spent_usd == 29.99

    def test_repeat_order_accumulates(self, tracker):
        tracker.record_order(
            email="jane@x.com", amount_usd=20.0, ts=100.0,
        )
        tracker.record_order(
            email="jane@x.com", amount_usd=30.0, ts=200.0,
        )
        fetched = tracker.get("jane@x.com")
        assert fetched.orders_count == 2
        assert fetched.total_spent_usd == 50.0

    def test_segment_of_unknown_returns_none(self, tracker):
        assert tracker.segment("does-not-exist") is None

    def test_stats_shape(self, tracker):
        # 4 customers: 1 VIP, 1 regular, 1 one-time, 1 dormant
        now = 1_700_000_000.0
        vip_ts = now - 5 * 86400
        regular_ts = now - 30 * 86400
        one_time_ts = now - 30 * 86400
        dormant_ts = now - 500 * 86400

        tracker.record_order(
            email="vip@x.com", amount_usd=100,
            ts=vip_ts - 60 * 86400,
        )
        tracker.record_order(
            email="vip@x.com", amount_usd=100,
            ts=vip_ts - 30 * 86400,
        )
        tracker.record_order(
            email="vip@x.com", amount_usd=100, ts=vip_ts,
        )
        tracker.record_order(
            email="regular@x.com", amount_usd=50,
            ts=regular_ts - 30 * 86400,
        )
        tracker.record_order(
            email="regular@x.com", amount_usd=50,
            ts=regular_ts,
        )
        tracker.record_order(
            email="once@x.com", amount_usd=25, ts=one_time_ts,
        )
        tracker.record_order(
            email="dormant@x.com", amount_usd=50,
            ts=dormant_ts,
        )
        stats = tracker.stats()
        assert stats["total_customers"] == 4
        assert stats["segments"]["vip"] == 1
        assert stats["segments"]["regular"] == 1
        assert stats["segments"]["one_time"] == 1
        assert stats["segments"]["dormant"] == 1
        # 300 (vip) + 100 (regular) + 25 (once) + 50 (dormant)
        assert stats["total_gmv_usd"] == 475.0

    def test_list_by_segment(self, tracker):
        """VIP filter returns only VIPs, sorted by spend."""
        now = 1_700_000_000.0
        for email, spend in [
            ("vip1@x.com", 600), ("vip2@x.com", 200),
        ]:
            # 3 orders each → VIP by orders OR spend
            for i in range(3):
                tracker.record_order(
                    email=email,
                    amount_usd=spend / 3,
                    ts=now - i * 10 * 86400,
                )
        vips = tracker.list_by_segment(LTVSegment.VIP)
        assert len(vips) == 2
        # Sorted by spend desc
        assert vips[0].email == "vip1@x.com"


# ── BudgetBuyerEngine ──────────────────────────────────


@pytest.fixture
def engine(tmp_path, monkeypatch):
    reset_singleton_for_tests()
    tracker = LTVTracker(
        db_path=str(tmp_path / "engine.db"),
        now_fn=lambda: 1_700_000_000.0,
    )
    allocator = BudgetAllocator(seed=42)
    return BudgetBuyerEngine(
        ltv_tracker=tracker, allocator=allocator,
        now_fn=lambda: 1_700_000_000.0,
    )


class TestBudgetBuyerEngine:
    def test_record_order_round_trip(self, engine):
        engine.record_order(
            email="jane@x.com", amount_usd=29.99,
        )
        fetched = engine.get_customer("jane@x.com")
        assert fetched.total_spent_usd == 29.99

    def test_allocate_budget_integration(self, engine):
        perf = [
            SKUPerformance(
                sku="a", orders=20, revenue_usd=400,
                ad_spend_usd=100, days_active=7,
            ),
            SKUPerformance(
                sku="b", orders=10, revenue_usd=100,
                ad_spend_usd=200, days_active=7,
            ),
        ]
        allocs = engine.allocate_budget(
            total_daily_usd=100.0, performance=perf,
        )
        assert len(allocs) == 2
        assert sum(
            x.recommended_daily_usd for x in allocs
        ) == pytest.approx(100.0, abs=0.01)

    def test_ltv_stats_from_engine(self, engine):
        engine.record_order(
            email="vip@x.com", amount_usd=100,
            ts=1_700_000_000.0 - 10 * 86400,
        )
        engine.record_order(
            email="vip@x.com", amount_usd=100,
            ts=1_700_000_000.0 - 5 * 86400,
        )
        engine.record_order(
            email="vip@x.com", amount_usd=150,
            ts=1_700_000_000.0,
        )
        stats = engine.ltv_stats()
        assert stats["total_customers"] == 1
        assert stats["segments"]["vip"] == 1

    def test_segment_customer(self, engine):
        engine.record_order(
            email="one@x.com", amount_usd=25,
            ts=1_700_000_000.0 - 30 * 86400,
        )
        assert engine.segment_customer("one@x.com") == LTVSegment.ONE_TIME

    def test_dormant_customers_for_winback(self, engine):
        engine.record_order(
            email="ghost@x.com", amount_usd=20,
            ts=1_700_000_000.0 - 500 * 86400,
        )
        dormant = engine.dormant_customers()
        emails = {c.email for c in dormant}
        assert "ghost@x.com" in emails


class TestSingleton:
    def test_get_engine_same_instance(self):
        reset_singleton_for_tests()
        a = get_engine()
        b = get_engine()
        assert a is b
        reset_singleton_for_tests()
