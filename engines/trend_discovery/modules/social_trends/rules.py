"""Social trends rules — constraints on chasing viral products."""
from __future__ import annotations
from typing import Any


RULES = [
    {
        "id": "min_engagement",
        "name": "Minimum engagement threshold",
        "description": "Product must have >5000 total engagements across platforms",
        "check": lambda p: _total_engagement(p) >= 5000,
        "severity": "blocker",
        "action": "Engagement too low — not enough social proof to validate demand",
    },
    {
        "id": "multi_platform",
        "name": "Multi-platform confirmation for high confidence",
        "description": "High-confidence actions require presence on 2+ platforms",
        "check": lambda p: p.get("platform_spread", 0) >= 2 or p.get("composite_score", 0) < 70,
        "severity": "warning",
        "action": "Single-platform trend — downgrade confidence, wait for cross-platform confirmation",
    },
    {
        "id": "no_single_creator",
        "name": "Not single-creator driven",
        "description": "Don't chase virality from a single mega-creator",
        "check": lambda p: p.get("creator_tier", "") != "mega" or p.get("platform_spread", 0) >= 2,
        "severity": "warning",
        "action": "Trend driven by single mega-creator — likely paid, not organic demand",
    },
    {
        "id": "organic_validation",
        "name": "Organic engagement required",
        "description": "Must have evidence of organic (non-sponsored) engagement",
        "check": lambda p: _has_organic_signals(p),
        "severity": "warning",
        "action": "No organic engagement detected — may be purely paid/sponsored virality",
    },
    {
        "id": "min_virality",
        "name": "Minimum virality score",
        "description": "Virality score must be at least 15 to consider",
        "check": lambda p: p.get("virality_score", 0) >= 15,
        "severity": "blocker",
        "action": "Virality score too low — product is not trending on social media",
    },
    {
        "id": "not_too_old",
        "name": "Trend not past peak",
        "description": "Trend older than 45 days needs accelerating velocity to act",
        "check": lambda p: (
            p.get("first_seen_days_ago", 0) <= 45
            or p.get("engagement_velocity", 0) >= 0.5
        ),
        "severity": "warning",
        "action": "Trend is 45+ days old with slowing velocity — may be past the profit window",
    },
    {
        "id": "purchase_intent_present",
        "name": "Purchase intent signals",
        "description": "Hashtags or content should indicate buying intent, not just entertainment",
        "check": lambda p: (
            p.get("hashtag_purchase_intent", 0) >= 0.1
            or p.get("platform_spread", 0) >= 3
        ),
        "severity": "info",
        "action": "No purchase-intent hashtags — virality may be entertainment-only",
    },
    {
        "id": "velocity_check",
        "name": "Engagement velocity positive",
        "description": "Engagement should still be growing, not decaying",
        "check": lambda p: p.get("engagement_velocity", 0.5) >= 0.2,
        "severity": "warning",
        "action": "Engagement velocity is very low — trend may be dying out",
    },
]


def evaluate_rules(product_data: dict[str, Any]) -> dict[str, Any]:
    """Evaluate all rules against a product's social data."""
    blockers, warnings, info = [], [], []
    for rule in RULES:
        try:
            passed = rule["check"](product_data)
        except Exception:
            passed = True  # fail open on data issues
        if not passed:
            entry = {"rule_id": rule["id"], "name": rule["name"], "action": rule["action"]}
            if rule["severity"] == "blocker":
                blockers.append(entry)
            elif rule["severity"] == "warning":
                warnings.append(entry)
            else:
                info.append(entry)

    return {
        "passed": len(blockers) == 0,
        "blockers": blockers,
        "warnings": warnings,
        "info": info,
        "rules_evaluated": len(RULES),
    }


def _total_engagement(product: dict[str, Any]) -> int:
    """Sum all engagement metrics across platforms."""
    total = 0
    tt = product.get("tiktok", {})
    total += tt.get("views", 0) + tt.get("shares", 0) * 5 + tt.get("comments", 0) * 2

    ig = product.get("instagram", {})
    total += ig.get("saves", 0) * 3 + ig.get("shares", 0) * 5 + ig.get("comments", 0) * 2

    pt = product.get("pinterest", {})
    total += pt.get("repins", 0) * 3 + pt.get("clicks", 0) * 5

    yt = product.get("youtube", {})
    total += yt.get("views", 0) + yt.get("likes", 0) * 2 + yt.get("comments", 0) * 3

    return total


def _has_organic_signals(product: dict[str, Any]) -> bool:
    """Check if engagement appears organic (not just paid/sponsored)."""
    creator = product.get("creator_tier", "unknown")
    spread = product.get("platform_spread", 0)
    hashtag_intent = product.get("hashtag_purchase_intent", 0)

    # Micro/nano creators or mixed = organic
    if creator in ("micro", "nano", "mixed"):
        return True
    # Multi-platform spread suggests organic pickup
    if spread >= 2:
        return True
    # Strong purchase-intent hashtags from users = organic
    if hashtag_intent >= 0.3:
        return True
    return False
