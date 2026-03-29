"""BudgetAllocator — allocates marketing spend across channels.

Strategies
----------
- ``proportional``      — split by a per-channel weight field.
- ``equal``             — equal share for every channel.
- ``performance``       — weight by ROAS from historical data.
- ``min_roas``          — only fund channels meeting a minimum ROAS threshold.

Uses only the Python standard library.
"""

from __future__ import annotations

from typing import Any


class BudgetAllocator:
    """Allocate and optimise marketing budget across ad channels."""

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def allocate(
        self,
        total_budget: float,
        channels: list[dict[str, Any]],
        strategy: str = "proportional",
    ) -> dict[str, Any]:
        """Distribute *total_budget* across *channels* using *strategy*.

        Args:
            total_budget: Total spend available (e.g. 10_000.00 USD).
            channels:     List of channel dicts.  Each must have at least
                          ``name``.  Additional keys depend on strategy:
                          - ``weight`` (float, default 1.0) for proportional.
                          - ``min_budget`` (float) optional floor per channel.
                          - ``max_budget`` (float) optional ceiling per channel.
            strategy:     ``"proportional"`` | ``"equal"`` | ``"performance"``.

        Returns:
            ``{"strategy": str, "total_budget": float,
               "allocations": {"channel_name": float, ...},
               "channel_count": int}``
        """
        if not channels:
            return {
                "strategy": strategy,
                "total_budget": total_budget,
                "allocations": {},
                "channel_count": 0,
            }

        if strategy == "equal":
            allocations = self._equal_allocation(total_budget, channels)
        elif strategy == "proportional":
            allocations = self._proportional_allocation(total_budget, channels)
        else:
            # Unknown strategy falls back to equal
            allocations = self._equal_allocation(total_budget, channels)

        allocations = self._apply_bounds(allocations, channels, total_budget)

        return {
            "strategy": strategy,
            "total_budget": total_budget,
            "allocations": allocations,
            "channel_count": len(channels),
        }

    def optimize_allocation(
        self,
        performance_data: list[dict[str, Any]],
        total_budget: float,
    ) -> dict[str, Any]:
        """Maximise blended ROAS by weighting spend towards best-performing channels.

        Args:
            performance_data: List of dicts, each with at minimum:
                              ``channel`` (str), ``roas`` (float),
                              ``spend`` (float).  Optional: ``min_budget``,
                              ``max_budget``.
            total_budget:     Total spend to distribute.

        Returns:
            ``{"strategy": "performance", "total_budget": float,
               "allocations": {...}, "projected_roas": float,
               "channel_count": int}``
        """
        if not performance_data:
            return {
                "strategy": "performance",
                "total_budget": total_budget,
                "allocations": {},
                "projected_roas": 0.0,
                "channel_count": 0,
            }

        allocations = self._performance_based_allocation(total_budget, performance_data)
        allocations = self._apply_bounds(allocations, performance_data, total_budget)

        # Projected blended ROAS
        projected_roas = self._projected_roas(allocations, performance_data)

        return {
            "strategy": "performance",
            "total_budget": total_budget,
            "allocations": allocations,
            "projected_roas": round(projected_roas, 4),
            "channel_count": len(performance_data),
        }

    # ------------------------------------------------------------------ #
    # Private allocation strategies                                        #
    # ------------------------------------------------------------------ #

    def _equal_allocation(
        self, total: float, channels: list[dict[str, Any]]
    ) -> dict[str, float]:
        """Split budget equally among all channels."""
        share = total / len(channels)
        return {ch.get("name", ch.get("channel", f"channel_{i}")): round(share, 2)
                for i, ch in enumerate(channels)}

    def _proportional_allocation(
        self, total: float, channels: list[dict[str, Any]]
    ) -> dict[str, float]:
        """Split budget proportional to each channel's ``weight`` field."""
        total_weight = sum(float(ch.get("weight", 1.0)) for ch in channels)
        if total_weight == 0:
            return self._equal_allocation(total, channels)

        result: dict[str, float] = {}
        for i, ch in enumerate(channels):
            name = ch.get("name", ch.get("channel", f"channel_{i}"))
            weight = float(ch.get("weight", 1.0))
            result[name] = round(total * (weight / total_weight), 2)
        return result

    def _performance_based_allocation(
        self, total: float, performance_data: list[dict[str, Any]]
    ) -> dict[str, float]:
        """Weight by ROAS; channels with ROAS <= 0 get zero allocation."""
        positive = [p for p in performance_data if float(p.get("roas", 0)) > 0]
        if not positive:
            # No channel has positive ROAS — fall back to equal
            return self._equal_allocation(
                total,
                [{"name": p.get("channel", f"ch_{i}")} for i, p in enumerate(performance_data)],
            )

        total_roas = sum(float(p["roas"]) for p in positive)
        result: dict[str, float] = {}
        for i, p in enumerate(performance_data):
            name = p.get("channel", f"channel_{i}")
            roas = float(p.get("roas", 0))
            if roas > 0:
                result[name] = round(total * (roas / total_roas), 2)
            else:
                result[name] = 0.0
        return result

    def _calculate_optimal_spend(
        self, channel_data: dict[str, Any], budget: float
    ) -> float:
        """Estimate the optimal spend for a single channel.

        Uses a simple diminishing-returns model:
        ``optimal = min(budget, historical_spend * (roas / target_roas))``

        If ``roas`` equals or exceeds ``target_roas`` the full budget is
        recommended; below target the spend is scaled down proportionally.
        """
        roas = float(channel_data.get("roas", 0))
        historical_spend = float(channel_data.get("spend", budget))
        target_roas = float(channel_data.get("target_roas", 2.0))

        if roas <= 0 or target_roas <= 0:
            return 0.0
        ratio = roas / target_roas
        optimal = historical_spend * ratio
        return round(min(optimal, budget), 2)

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _apply_bounds(
        self,
        allocations: dict[str, float],
        channels: list[dict[str, Any]],
        total_budget: float,
    ) -> dict[str, float]:
        """Clip allocations to per-channel min/max budgets and rescale.

        Channels that don't appear in the channel list are left unchanged.
        After clamping, the residual budget is redistributed proportionally
        among unconstrained channels.
        """
        # Build lookup by name or channel key
        bounds: dict[str, dict[str, float]] = {}
        for ch in channels:
            name = ch.get("name", ch.get("channel", ""))
            if name:
                bounds[name] = {
                    "min": float(ch.get("min_budget", 0.0)),
                    "max": float(ch.get("max_budget", float("inf"))),
                }

        clamped: dict[str, float] = {}
        locked_total = 0.0
        for name, amount in allocations.items():
            b = bounds.get(name, {"min": 0.0, "max": float("inf")})
            val = max(b["min"], min(b["max"], amount))
            clamped[name] = val
            locked_total += val

        # If clamped total exceeds budget, scale down proportionally
        if locked_total > total_budget and locked_total > 0:
            factor = total_budget / locked_total
            clamped = {k: round(v * factor, 2) for k, v in clamped.items()}

        return clamped

    def _projected_roas(
        self,
        allocations: dict[str, float],
        performance_data: list[dict[str, Any]],
    ) -> float:
        """Compute blended projected ROAS for the new allocation."""
        roas_by_channel = {
            p.get("channel", ""): float(p.get("roas", 0))
            for p in performance_data
        }
        total_spend = sum(allocations.values())
        if total_spend == 0:
            return 0.0
        weighted = sum(
            alloc * roas_by_channel.get(ch, 0)
            for ch, alloc in allocations.items()
        )
        return weighted / total_spend
