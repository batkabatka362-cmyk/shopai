"""Blacklist checker — screen products against compliance blacklists.

Checks products for: restricted categories, banned substances,
trademark keywords, and platform-specific policy violations.

Input contract:  {status, data: {product_name, category, description, ingredients?, platform?}, meta, error}
Output contract: {status, data: {result, violations, risk_assessment}, meta: {engine, confidence, timestamp}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .rules import BLOCKED_CATEGORIES, RESTRICTED_CATEGORIES, RESTRICTED_KEYWORDS
from .data import BANNED_SUBSTANCES, TRADEMARK_TERMS, get_substances_for_category
from .logic import assess_risk_level, check_platform_compliance


def check_blacklist(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Check a product against all blacklists — engine contract entry point.

    Args:
        input_payload: Engine contract dict with product data.

    Returns:
        Engine contract dict with pass/fail result and violation details.
    """
    validation = _validate_input(input_payload)
    if not validation["valid"]:
        return _error_output(validation["reason"])

    data = copy.deepcopy(input_payload.get("data", {}))
    product_text = _build_search_text(data)

    violations = []
    violations.extend(_check_category_rules(product_text, BLOCKED_CATEGORIES))
    violations.extend(_check_category_rules(product_text, RESTRICTED_CATEGORIES))
    violations.extend(_check_trademark_keywords(product_text))
    violations.extend(_check_banned_substances(data))

    # Platform-specific check if platform is specified
    platform = data.get("platform", "")
    platform_result = None
    if platform:
        platform_result = check_platform_compliance(data, platform)
        violations.extend(platform_result.get("issues", []))

    risk = assess_risk_level(violations)
    result = "fail" if not risk["can_proceed"] else "pass"

    return {
        "status": "success",
        "data": {
            "result": result,
            "product_name": data.get("product_name", data.get("name", "")),
            "violations": violations,
            "violation_count": len(violations),
            "risk_assessment": risk,
            "platform_compliance": platform_result,
            "checked_against": [
                "restricted_categories",
                "banned_substances",
                "trademark_keywords",
                "platform_policies",
            ],
        },
        "meta": {
            "engine": "blacklist_checker",
            "confidence": 0.90 if violations else 0.95,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "note": (
                "Automated check — not a substitute for legal counsel. "
                "Consult a compliance professional for regulated products."
            ),
        },
        "error": None,
    }


def _validate_input(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the input payload has required structure."""
    if not isinstance(payload, dict):
        return {"valid": False, "reason": "Input must be a dictionary"}
    data = payload.get("data")
    if not isinstance(data, dict):
        return {"valid": False, "reason": "Missing or invalid 'data' field"}
    has_product_info = (
        data.get("product_name")
        or data.get("name")
        or data.get("category")
        or data.get("description")
    )
    if not has_product_info:
        return {"valid": False, "reason": "Need product_name, name, category, or description"}
    return {"valid": True, "reason": "OK"}


def _build_search_text(data: dict[str, Any]) -> str:
    """Combine all product fields into a single searchable text."""
    parts = [
        data.get("product_name", ""),
        data.get("name", ""),
        data.get("category", ""),
        data.get("description", ""),
        data.get("tags", ""),
    ]
    if isinstance(data.get("ingredients"), list):
        parts.extend(data["ingredients"])
    elif isinstance(data.get("ingredients"), str):
        parts.append(data["ingredients"])
    return " ".join(parts).lower()


def _check_category_rules(text: str, rules: dict) -> list[dict[str, Any]]:
    """Check product text against a category rule set (blocked or restricted)."""
    violations = []
    for cat_key, cat_info in rules.items():
        for keyword in cat_info["keywords"]:
            if keyword in text:
                violations.append({
                    "category": cat_key,
                    "severity": cat_info["severity"] if "severity" in cat_info else "blocked",
                    "matched_keyword": keyword,
                    "detail": cat_info["reason"],
                })
                break  # One match per category is enough
    return violations


def _check_trademark_keywords(text: str) -> list[dict[str, Any]]:
    """Check product text for known trademark terms."""
    violations = []
    for group, terms in TRADEMARK_TERMS.items():
        for term in terms:
            if term in text:
                violations.append({
                    "category": "trademark",
                    "severity": "blocked",
                    "matched_keyword": term,
                    "detail": (
                        f"'{term}' is a protected trademark ({group}). "
                        f"Using it without authorization may result in IP complaints."
                    ),
                })
    return violations


def _check_banned_substances(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Check product ingredients against banned substance lists."""
    violations = []
    category = data.get("category", "")
    ingredients = data.get("ingredients", [])
    if isinstance(ingredients, str):
        ingredients = [i.strip() for i in ingredients.split(",")]
    if not ingredients:
        return violations

    substance_info = get_substances_for_category(category)
    banned_list = substance_info.get("banned", [])

    for ingredient in ingredients:
        ingredient_lower = ingredient.lower().strip()
        for banned in banned_list:
            if banned.lower() in ingredient_lower or ingredient_lower in banned.lower():
                violations.append({
                    "category": "banned_substance",
                    "severity": "blocked",
                    "matched_keyword": banned,
                    "ingredient": ingredient,
                    "detail": (
                        f"'{ingredient}' matches banned substance '{banned}'. "
                        f"Source: {substance_info.get('source', 'Unknown')}."
                    ),
                })
    return violations


def _error_output(reason: str) -> dict[str, Any]:
    """Return a standardized error output."""
    return {
        "status": "fail",
        "data": None,
        "meta": {
            "engine": "blacklist_checker",
            "confidence": 0,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "error": {"reason": reason},
    }
