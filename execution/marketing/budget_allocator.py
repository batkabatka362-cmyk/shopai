"""Budget Allocator — allocates budgets across marketing channels."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("exec.budget_allocator")


class BudgetAllocator:
    def allocate(self, total_budget: float, channels: list[dict[str, Any]]) -> dict[str, float]:
        if not channels:
            return {}
        per_channel = total_budget / len(channels)
        allocation = {}
        for ch in channels:
            name = ch.get("name", "unknown")
            weight = ch.get("weight", 1.0)
            allocation[name] = per_channel * weight
        logger.info("Allocated %.2f across %d channels", total_budget, len(channels))
        return allocation
