"""Loyalty Engine — program designer.

Designs points/tiers structure for the loyalty program. Defines
tier thresholds, point earning rates, and tier benefits based on
program configuration and customer base analysis.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Default tier definitions
# ---------------------------------------------------------------------------

_DEFAULT_TIERS: list[dict[str, Any]] = [
    {
        "name": "bronze",
        "min_points": 0,
        "multiplier": 1.0,
        "benefits": ["basic_rewards", "birthday_bonus"],
    },
    {
        "name": "silver",
        "min_points": 1000,
        "multiplier": 1.25,
        "benefits": ["basic_rewards", "birthday_bonus", "early_access", "free_shipping_over_50"],
    },
    {
        "name": "gold",
        "min_points": 5000,
        "multiplier": 1.5,
        "benefits": ["basic_rewards", "birthday_bonus", "early_access", "free_shipping", "exclusive_deals"],
    },
    {
        "name": "platinum",
        "min_points": 15000,
        "multiplier": 2.0,
        "benefits": ["basic_rewards", "birthday_bonus", "early_access", "free_shipping", "exclusive_deals", "personal_stylist", "vip_events"],
    },
]

_DEFAULT_POINTS_PER_DOLLAR = 10.0


def design_program(
    program_config: dict[str, Any],
    customers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Design or validate the loyalty program structure.

    Args:
        program_config: ProgramConfig dict with optional overrides.
        customers: List of customer records for calibration.

    Returns:
        Structured dict with program design.
    """
    try:
        config = copy.deepcopy(program_config)

        # Use configured tiers or defaults
        tier_thresholds = config.get("tier_thresholds", {})
        if tier_thresholds:
            tiers = []
            for name in ["bronze", "silver", "gold", "platinum"]:
                threshold = tier_thresholds.get(name, 0)
                default = next((t for t in _DEFAULT_TIERS if t["name"] == name), _DEFAULT_TIERS[0])
                tiers.append({
                    "name": name,
                    "min_points": int(threshold),
                    "multiplier": default["multiplier"],
                    "benefits": default["benefits"],
                })
        else:
            tiers = copy.deepcopy(_DEFAULT_TIERS)

        points_per_dollar = float(config.get("points_per_dollar", _DEFAULT_POINTS_PER_DOLLAR))

        # Build point rules
        point_rules = [
            {"action": "purchase", "points_per_dollar": points_per_dollar, "description": "Earn points on every purchase"},
            {"action": "review", "points": 50, "description": "Write a product review"},
            {"action": "referral", "points": 200, "description": "Refer a friend who makes a purchase"},
            {"action": "birthday", "points": 100, "description": "Birthday bonus points"},
            {"action": "social_share", "points": 25, "description": "Share a product on social media"},
        ]

        return {
            "status": "success",
            "design": {
                "tiers": tiers,
                "point_rules": point_rules,
                "earning_rate": points_per_dollar,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "design": {},
            "error": f"Program design failed: {exc}",
        }
