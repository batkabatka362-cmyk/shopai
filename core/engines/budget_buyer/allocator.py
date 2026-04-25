"""Ad budget allocator — Thompson Sampling across SKUs.

The classic multi-armed bandit problem: spend ad budget on the
SKU most likely to return the highest ROAS, while still
exploring SKUs with less data. Thompson Sampling solves this
elegantly — sample from each SKU's posterior ROAS distribution
(Beta-Gamma style), then allocate proportional to the sampled
values. Pure math, deterministic given a seed.

Policy wraps the algorithm with two owner-facing guardrails:

  * ``min_per_sku_usd`` — floor. Don't starve any active SKU
    below this — exploration stays alive even for poor
    performers until they're explicitly paused.
  * ``max_per_sku_usd`` — cap. One unusually hot SKU mid-day
    shouldn't eat the whole budget + leave the catalogue dry.
    Diversification guardrail.

Insufficient-data behaviour:

  * A SKU with < ``min_samples`` orders gets an equal share of
    the "exploration pool" (a percentage of total budget set
    aside). This guarantees new SKUs always get a chance —
    Thompson's own exploration is too slow at small N.

Pure stdlib ``random`` + ``statistics``. Tests pin the seed.
"""
from __future__ import annotations

import logging
import random
import statistics
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger("shopai.budget_buyer.allocator")


# ── Inputs / outputs ─────────────────────────────────────


@dataclass
class SKUPerformance:
    """One SKU's recent rolling window (e.g. last 7 days).

    Caller populates this from Shopify orders + Meta Ads
    insights. ``days_active`` lets the allocator detect new
    SKUs and route them to the exploration pool.
    """

    sku: str
    product_id: str = ""
    orders: int = 0
    revenue_usd: float = 0.0
    ad_spend_usd: float = 0.0
    impressions: int = 0
    clicks: int = 0
    days_active: int = 1

    def __post_init__(self) -> None:
        if not self.sku:
            raise ValueError("sku is required")
        if self.days_active < 1:
            raise ValueError("days_active must be >= 1")
        # Non-negative invariants
        for field_name in (
            "orders", "revenue_usd", "ad_spend_usd",
            "impressions", "clicks",
        ):
            if getattr(self, field_name) < 0:
                raise ValueError(
                    f"{field_name} must be >= 0",
                )

    def roas(self) -> float:
        """Return on Ad Spend — revenue / ad_spend."""
        if self.ad_spend_usd <= 0:
            return 0.0
        return self.revenue_usd / self.ad_spend_usd

    def cvr(self) -> float:
        """Conversion rate — orders / clicks."""
        if self.clicks <= 0:
            return 0.0
        return self.orders / self.clicks

    def cpc(self) -> float:
        """Cost per click — ad_spend / clicks."""
        if self.clicks <= 0:
            return 0.0
        return self.ad_spend_usd / self.clicks

    def daily_orders(self) -> float:
        return self.orders / max(1, self.days_active)


@dataclass
class BudgetAllocation:
    """One allocator decision for one SKU."""

    sku: str
    recommended_daily_usd: float
    share_pct: float             # of total_daily_usd
    sampled_roas: float = 0.0    # posterior sample (Thompson)
    observed_roas: float = 0.0
    orders_observed: int = 0
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "recommended_daily_usd": round(
                self.recommended_daily_usd, 2,
            ),
            "share_pct": round(self.share_pct, 2),
            "sampled_roas": round(self.sampled_roas, 3),
            "observed_roas": round(self.observed_roas, 3),
            "orders_observed": self.orders_observed,
            "reason": self.reason,
        }


# ── Allocator ────────────────────────────────────────────


class BudgetAllocator:
    """Thompson-Sampling budget splitter.

    One instance per process is fine — state is only the
    ``random.Random`` instance so reproducible seeds are
    testable.

    The prior is Gamma(α=1, β=1) over ROAS: 1 pseudo-order + 1
    pseudo-dollar of ad spend. Conjugate posterior after N
    real orders + $S ad spend is Gamma(α=1+N, β=1+S). Sampling
    from this gives a score proportional to the posterior mean
    with variance that shrinks as N grows — Thompson in one
    line.
    """

    def __init__(
        self,
        *,
        seed: int | None = None,
        exploration_reserve_pct: float = 0.20,
        min_samples: int = 5,
    ) -> None:
        self._rng = random.Random(seed)
        if not 0 <= exploration_reserve_pct <= 0.5:
            raise ValueError(
                "exploration_reserve_pct must be in [0, 0.5]",
            )
        self._explore_pct = exploration_reserve_pct
        if min_samples < 1:
            raise ValueError("min_samples must be >= 1")
        self._min_samples = min_samples

    def allocate(
        self,
        total_daily_usd: float,
        performance: list[SKUPerformance],
        *,
        min_per_sku_usd: float = 0.0,
        max_per_sku_usd: float | None = None,
    ) -> list[BudgetAllocation]:
        """Split ``total_daily_usd`` across the SKUs.

        Ordering of the return list matches ``performance`` —
        caller gets a stable 1:1 mapping to their input.
        """
        if total_daily_usd < 0:
            raise ValueError("total_daily_usd must be >= 0")
        if not performance:
            return []

        n = len(performance)
        if total_daily_usd == 0:
            return [
                BudgetAllocation(
                    sku=p.sku, recommended_daily_usd=0.0,
                    share_pct=0.0,
                    observed_roas=p.roas(),
                    orders_observed=p.orders,
                    reason="total budget is zero",
                )
                for p in performance
            ]

        # Split: exploration pool (equal share for low-data SKUs),
        # exploit pool (Thompson-sampled across well-sampled SKUs).
        explore_budget = total_daily_usd * self._explore_pct
        exploit_budget = total_daily_usd - explore_budget

        new_skus = [
            p for p in performance
            if p.orders < self._min_samples
        ]
        tested_skus = [
            p for p in performance
            if p.orders >= self._min_samples
        ]

        # Edge cases: everything is new, or everything is
        # tested. Collapse pools.
        if not tested_skus:
            # Every SKU is new — split the full budget equally
            per = total_daily_usd / n
            out = [
                BudgetAllocation(
                    sku=p.sku,
                    recommended_daily_usd=per,
                    share_pct=(per / total_daily_usd) * 100,
                    observed_roas=p.roas(),
                    orders_observed=p.orders,
                    reason=(
                        f"exploration — only {p.orders} "
                        f"orders (<{self._min_samples} min)"
                    ),
                )
                for p in performance
            ]
            return self._apply_floor_cap(
                out, total_daily_usd,
                min_per_sku_usd, max_per_sku_usd,
            )
        if not new_skus:
            # Everyone has data — no exploration pool needed
            exploit_budget = total_daily_usd
            explore_budget = 0.0

        # Build exploration allocations
        alloc_by_sku: dict[str, BudgetAllocation] = {}
        if new_skus:
            per_new = explore_budget / len(new_skus)
            for p in new_skus:
                alloc_by_sku[p.sku] = BudgetAllocation(
                    sku=p.sku,
                    recommended_daily_usd=per_new,
                    share_pct=(
                        (per_new / total_daily_usd) * 100
                        if total_daily_usd else 0.0
                    ),
                    observed_roas=p.roas(),
                    orders_observed=p.orders,
                    reason=(
                        f"exploration pool — {p.orders} "
                        f"orders (<{self._min_samples} min)"
                    ),
                )

        # Thompson sampling across tested SKUs
        if tested_skus:
            sampled = [
                (p, self._posterior_sample(p))
                for p in tested_skus
            ]
            total_sample = sum(s for _, s in sampled)
            if total_sample <= 0:
                # Everything sampled to zero — fallback equal
                per = exploit_budget / len(tested_skus)
                for p, score in sampled:
                    alloc_by_sku[p.sku] = BudgetAllocation(
                        sku=p.sku,
                        recommended_daily_usd=per,
                        share_pct=(
                            (per / total_daily_usd) * 100
                        ),
                        sampled_roas=score,
                        observed_roas=p.roas(),
                        orders_observed=p.orders,
                        reason=(
                            "all sampled ROAS zero — "
                            "equal fallback"
                        ),
                    )
            else:
                for p, score in sampled:
                    share = score / total_sample
                    usd = exploit_budget * share
                    alloc_by_sku[p.sku] = BudgetAllocation(
                        sku=p.sku,
                        recommended_daily_usd=usd,
                        share_pct=(
                            (usd / total_daily_usd) * 100
                            if total_daily_usd else 0.0
                        ),
                        sampled_roas=score,
                        observed_roas=p.roas(),
                        orders_observed=p.orders,
                        reason=(
                            f"Thompson sample — "
                            f"posterior ROAS {score:.2f} "
                            f"of {total_sample:.2f} total"
                        ),
                    )

        # Preserve input order
        ordered = [alloc_by_sku[p.sku] for p in performance]
        return self._apply_floor_cap(
            ordered, total_daily_usd,
            min_per_sku_usd, max_per_sku_usd,
        )

    # ── Internals ────────────────────────────────────────

    def _posterior_sample(self, p: SKUPerformance) -> float:
        """Sample from the posterior ROAS distribution.

        Prior: Gamma(α=1, β=1). After N orders + $S ad spend
        observed: Gamma(α=1+N, β=1+S). Mean of the posterior
        is ``N_revenue / (1+ad_spend)`` effectively. We sample
        a single draw — that's Thompson's stochastic choice.

        Edge case: zero ad_spend. Then we fall back to a
        velocity-based prior (daily orders × ~$25 AOV so the
        SKU is still considered, just not heavily backed).
        """
        if p.ad_spend_usd > 0:
            alpha = 1 + p.revenue_usd
            beta = 1 + p.ad_spend_usd
            # gammavariate returns the Gamma distribution
            # sample. alpha/beta gives a ROAS-shaped quantity.
            return self._rng.gammavariate(alpha, 1.0 / beta)
        # No ad spend yet — bootstrap with daily velocity as
        # proxy. This matters for SKUs gaining organic traction
        # that haven't been test-promoted.
        if p.daily_orders() > 0:
            return 1.0 + p.daily_orders() * 0.1
        return 0.0

    def _apply_floor_cap(
        self,
        allocs: list[BudgetAllocation],
        total: float,
        min_per_sku: float,
        max_per_sku: float | None,
    ) -> list[BudgetAllocation]:
        """Constrained allocation: respect ``[min, max]`` per
        SKU while keeping the sum equal to ``total``.

        Algorithm: iterate until stable (or cap at 20 passes).
        Each pass:

          1. Clamp every value into [min, max]
          2. Lock clamped values (they satisfy their bound
             exactly); redistribute the remaining budget
             among the unclamped proportionally

        Converges fast — typically 1-3 passes. The 20-pass cap
        is a safety net against pathological inputs (e.g.
        every SKU floored + sum already exceeds total).
        """
        if min_per_sku < 0:
            raise ValueError("min_per_sku_usd must be >= 0")
        if max_per_sku is not None and max_per_sku < min_per_sku:
            raise ValueError(
                "max_per_sku_usd must be >= min_per_sku_usd",
            )
        # If floors alone exceed total, the problem is
        # unsolvable — everyone gets equal share of total.
        n = len(allocs)
        if n * min_per_sku > total:
            per = total / n
            for a in allocs:
                a.recommended_daily_usd = per
            self._recompute_share_pct(allocs, total)
            return allocs

        locked: set[int] = set()
        for _pass in range(20):
            # Step 1: clamp anything that breaches its bound
            changed = False
            for i, a in enumerate(allocs):
                if i in locked:
                    continue
                v = a.recommended_daily_usd
                if v < min_per_sku:
                    a.recommended_daily_usd = min_per_sku
                    locked.add(i)
                    changed = True
                elif (
                    max_per_sku is not None
                    and v > max_per_sku
                ):
                    a.recommended_daily_usd = max_per_sku
                    locked.add(i)
                    changed = True

            # Step 2: check if sum matches — if so, done
            current_sum = sum(
                a.recommended_daily_usd for a in allocs
            )
            if abs(current_sum - total) <= 0.01:
                break

            # Step 3: redistribute the delta across unlocked
            unlocked_idx = [
                i for i in range(n) if i not in locked
            ]
            if not unlocked_idx:
                # Everything is locked — can't fix further
                break
            unlocked_sum = sum(
                allocs[i].recommended_daily_usd
                for i in unlocked_idx
            )
            locked_sum = current_sum - unlocked_sum
            remaining = total - locked_sum
            if unlocked_sum <= 0:
                # Unlocked all at zero — spread remaining
                # equally
                if remaining <= 0:
                    break
                per = remaining / len(unlocked_idx)
                for i in unlocked_idx:
                    allocs[i].recommended_daily_usd = per
            else:
                scale = remaining / unlocked_sum
                for i in unlocked_idx:
                    allocs[i].recommended_daily_usd *= scale

            if not changed:
                # No clamps happened this pass — stable
                break

        self._recompute_share_pct(allocs, total)
        return allocs

    @staticmethod
    def _recompute_share_pct(
        allocs: list[BudgetAllocation], total: float,
    ) -> None:
        for a in allocs:
            a.share_pct = (
                (a.recommended_daily_usd / total) * 100
                if total > 0 else 0.0
            )
