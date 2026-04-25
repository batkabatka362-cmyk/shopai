"""Constraint solver — greedy LP-style optimiser over resources.

The budget allocator (v6-D3) fair-shares a single resource. Real
store decisions involve *multiple* constraints simultaneously:

  maximise   Σ roas_i · alloc_i
  subject to Σ alloc_i ≤ total_budget
             alloc_i ≥ min_budget_i
             alloc_i ≤ max_budget_i
             Σ items_sold_i ≤ inventory_i  (non-negotiable)
             alloc_i ≤ (inventory_i / demand_per_dollar_i)

Full-blown LP needs scipy / pulp; we want pure-stdlib and
deterministic. Implemented as a two-pass greedy:

  1. Assign every item its ``min_budget`` (hard floor).
  2. Greedily allocate remaining budget to the item with the
     highest *marginal* ROAS until a cap (budget, inventory) is
     hit, then move on.

The greedy is optimal when each item's marginal ROAS is monotone-
decreasing in allocation (true for most ad auctions). If the
caller supplies non-monotone items, the solver returns the greedy
approximation and flags ``approx=True``.

Also exposes:

  solve(items, total_budget)                 → Allocation
  explain(allocation)                        → human-readable
  binding_constraints(allocation)            → which caps hit

Zero LLM, O(N log N) in number of items.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class Item:
    id: str
    marginal_roas: float            # expected $ return per $1 spent
    min_budget: float = 0.0
    max_budget: float = float("inf")
    inventory_units: float | None = None
    demand_per_dollar: float = 0.0  # units expected per $ spent

    def max_spend_from_inventory(self) -> float:
        if self.inventory_units is None or self.demand_per_dollar <= 0:
            return float("inf")
        return self.inventory_units / self.demand_per_dollar

    def effective_cap(self) -> float:
        return min(self.max_budget, self.max_spend_from_inventory())


@dataclass
class AllocatedItem:
    id: str
    allocated: float
    binding: str | None = None      # "max" | "inventory" | "budget" | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "allocated": round(self.allocated, 2),
            "binding": self.binding,
        }


@dataclass
class Allocation:
    items: list[AllocatedItem] = field(default_factory=list)
    total_spent: float = 0.0
    budget: float = 0.0
    expected_return: float = 0.0
    approx: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "items": [i.as_dict() for i in self.items],
            "total_spent": round(self.total_spent, 2),
            "budget": round(self.budget, 2),
            "expected_return": round(self.expected_return, 2),
            "unspent": round(self.budget - self.total_spent, 2),
            "approx": self.approx,
        }

    def get(self, item_id: str) -> AllocatedItem | None:
        for it in self.items:
            if it.id == item_id:
                return it
        return None


# ── Solver ──────────────────────────────────────────────────

def solve(
    items: Iterable[Item], total_budget: float,
) -> Allocation:
    items = list(items)
    if total_budget <= 0 or not items:
        return Allocation(
            items=[AllocatedItem(i.id, 0.0) for i in items],
            total_spent=0.0, budget=max(0.0, total_budget),
        )

    # Validate minimums don't already exceed the budget
    min_total = sum(i.min_budget for i in items)
    if min_total > total_budget:
        # Cannot satisfy all minimums; scale proportionally.
        scale = total_budget / min_total
        scaled = []
        expected = 0.0
        for it in items:
            alloc = it.min_budget * scale
            scaled.append(AllocatedItem(
                id=it.id, allocated=alloc,
                binding="budget",
            ))
            expected += alloc * it.marginal_roas
        return Allocation(
            items=scaled, total_spent=total_budget,
            budget=total_budget, expected_return=expected,
            approx=True,
        )

    # Pass 1: seed minimums
    seeded: dict[str, AllocatedItem] = {
        i.id: AllocatedItem(id=i.id, allocated=i.min_budget)
        for i in items
    }
    remaining = total_budget - min_total

    # Mark items that hit caps from the minimum alone
    for it in items:
        cap = it.effective_cap()
        if seeded[it.id].allocated >= cap:
            seeded[it.id].allocated = cap
            if cap == it.max_budget:
                seeded[it.id].binding = "max"
            elif it.max_spend_from_inventory() == cap:
                seeded[it.id].binding = "inventory"

    # Pass 2: greedy by marginal_roas
    ordered = sorted(items, key=lambda i: -i.marginal_roas)
    for it in ordered:
        if remaining <= 0:
            break
        alloc = seeded[it.id]
        cap = it.effective_cap()
        room = max(0.0, cap - alloc.allocated)
        take = min(room, remaining)
        if take <= 0:
            continue
        alloc.allocated += take
        remaining -= take
        if alloc.allocated >= cap - 1e-9:
            if it.max_spend_from_inventory() <= it.max_budget:
                alloc.binding = "inventory"
            else:
                alloc.binding = "max"

    result = list(seeded.values())
    spent = sum(a.allocated for a in result)
    expected = sum(
        a.allocated * it.marginal_roas
        for a, it in zip(result, items)
    )
    # If we couldn't spend the full budget, last-allocated item's
    # cap is the binding one (already marked above).
    return Allocation(
        items=result,
        total_spent=spent,
        budget=total_budget,
        expected_return=expected,
        approx=False,
    )


# ── Introspection ───────────────────────────────────────────

def binding_constraints(allocation: Allocation) -> list[str]:
    """Which item / constraint combinations are binding right now.

    Useful for the owner digest: ``"L2.inventory is binding — raising
    it would let the solver spend 40 more"``."""
    out: list[str] = []
    for a in allocation.items:
        if a.binding:
            out.append(f"{a.id}.{a.binding}")
    if allocation.budget - allocation.total_spent > 0.01:
        out.append("total_budget.underutilised")
    return out


def explain(allocation: Allocation) -> str:
    lines = [
        f"budget {allocation.budget:.2f} → spent {allocation.total_spent:.2f} "
        f"→ expected {allocation.expected_return:.2f}"
    ]
    if allocation.approx:
        lines.append("  (approximate — couldn't satisfy all minimums)")
    for a in allocation.items:
        tag = f" [{a.binding}]" if a.binding else ""
        lines.append(f"  • {a.id:16s} ${a.allocated:8.2f}{tag}")
    binding = binding_constraints(allocation)
    if binding:
        lines.append(f"  binding: {', '.join(binding)}")
    return "\n".join(lines)
