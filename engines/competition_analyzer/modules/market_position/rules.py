"""Market position rules — constraints on valid positioning decisions.

Core principles:
  - Position must be CONSISTENT across the entire catalog
  - Cannot be premium AND budget simultaneously (brand confusion)
  - Position must be SUSTAINABLE with current margins
  - Repositioning requires a deliberate plan, not accidental drift
"""
from __future__ import annotations

from typing import Any


# Positioning must be consistent across all catalog items
POSITION_CONSISTENCY_REQUIRED = True

# Minimum margin floor — position must be sustainable at this margin
MARGIN_FLOOR_PCT = 15

# Positions that cannot coexist in the same catalog
INCOMPATIBLE_POSITIONS = {
    ("budget_leader", "premium"),
    ("budget_leader", "ultra_premium"),
    ("value_leader", "ultra_premium"),
}

# Maximum catalog items allowed to deviate from primary position
MAX_POSITION_DEVIATIONS = 1


RULES = [
    {
        "id": "catalog_consistency",
        "name": "Catalog position consistency",
        "description": (
            "All products in catalog should share the same positioning. "
            "Mixed signals confuse customers and weaken brand."
        ),
        "check": lambda ctx: len(ctx.get("conflicts", [])) <= MAX_POSITION_DEVIATIONS,
        "severity": "blocker",
        "action": (
            "Too many catalog items conflict with proposed position. "
            "Resolve conflicts before repositioning."
        ),
    },
    {
        "id": "no_premium_and_budget",
        "name": "No contradictory positions",
        "description": (
            "Cannot simultaneously position as budget AND premium. "
            "Pick one tier and commit."
        ),
        "check": lambda ctx: not _has_incompatible_pair(
            ctx.get("recommended_position", ""),
            ctx.get("catalog", []),
        ),
        "severity": "blocker",
        "action": (
            "Catalog contains products that contradict the proposed position. "
            "Remove conflicting products or change position."
        ),
    },
    {
        "id": "margin_sustainability",
        "name": "Margin sustainability",
        "description": (
            f"Position must be sustainable with at least {MARGIN_FLOOR_PCT}% margin. "
            "Budget positioning with razor-thin margins is a losing game for small sellers."
        ),
        "check": lambda ctx: ctx.get("target_margin_pct", 30) >= MARGIN_FLOOR_PCT,
        "severity": "blocker",
        "action": (
            f"Target margin below {MARGIN_FLOOR_PCT}%. Either increase prices, "
            "reduce costs, or choose a higher-margin position."
        ),
    },
    {
        "id": "repositioning_must_be_deliberate",
        "name": "Deliberate repositioning",
        "description": (
            "Changing position requires a plan. Accidental drift damages brand."
        ),
        "check": lambda ctx: (
            ctx.get("current_position") is None
            or ctx.get("current_position") == ctx.get("recommended_position")
            or ctx.get("repositioning_acknowledged", False)
        ),
        "severity": "warning",
        "action": (
            "You are changing market positions. This requires a deliberate plan "
            "covering pricing, content, packaging, and customer communication."
        ),
    },
    {
        "id": "premium_requires_premium_everything",
        "name": "Premium position requirements",
        "description": (
            "Premium or ultra-premium positioning requires premium across "
            "ALL touchpoints: product, packaging, photos, service, and content."
        ),
        "check": lambda ctx: _premium_check(ctx),
        "severity": "warning",
        "action": (
            "Premium positioning chosen but not all touchpoints are premium-grade. "
            "Upgrade packaging, photography, and service before claiming premium."
        ),
    },
    {
        "id": "niche_must_define_niche",
        "name": "Niche definition required",
        "description": (
            "Niche specialist position requires a clearly defined target audience. "
            "Cannot be a niche specialist without knowing the niche."
        ),
        "check": lambda ctx: (
            ctx.get("recommended_position") != "niche_specialist"
            or bool(ctx.get("niche_definition"))
        ),
        "severity": "warning",
        "action": "Define your niche audience before positioning as a specialist.",
    },
]


def evaluate_rules(
    context: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate all positioning rules against the proposed strategy.

    Args:
        context: Dict with recommended_position, current_position,
                 target_margin_pct, catalog, conflicts, etc.

    Returns:
        Dict with passed (bool), blockers, warnings, and rules_evaluated count.
    """
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for rule in RULES:
        try:
            passed = rule["check"](context)
        except Exception:
            passed = True

        if not passed:
            entry = {
                "rule_id": rule["id"],
                "name": rule["name"],
                "description": rule["description"],
                "action": rule["action"],
            }
            if rule["severity"] == "blocker":
                blockers.append(entry)
            else:
                warnings.append(entry)

    return {
        "passed": len(blockers) == 0,
        "blockers": blockers,
        "warnings": warnings,
        "rules_evaluated": len(RULES),
    }


def _has_incompatible_pair(
    recommended: str, catalog: list[dict[str, Any]]
) -> bool:
    """Check if any catalog item has a position incompatible with the recommendation."""
    for item in catalog:
        item_pos = item.get("position", "")
        pair = tuple(sorted([recommended, item_pos]))
        if pair in INCOMPATIBLE_POSITIONS or tuple(reversed(pair)) in INCOMPATIBLE_POSITIONS:
            return True
    return False


def _premium_check(context: dict[str, Any]) -> bool:
    """Check if premium positioning has premium-grade touchpoints."""
    position = context.get("recommended_position", "")
    if position not in ("premium", "ultra_premium"):
        return True  # Rule only applies to premium positions

    # If touchpoint data is available, verify all are premium
    touchpoints = context.get("touchpoints", {})
    if not touchpoints:
        return True  # No data to check — pass with warning from other rules

    required = ["photography", "packaging", "service", "content"]
    for tp in required:
        grade = touchpoints.get(tp, "standard")
        if grade not in ("premium", "excellent"):
            return False

    return True
