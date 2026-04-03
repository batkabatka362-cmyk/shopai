"""Product Variant Engine — variant generator.

Generates all valid variant combinations from option axes,
applying exclusion rules to filter out forbidden combos.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import itertools
from typing import Any


def generate_variants(
    product: dict[str, Any],
    options: list[dict[str, Any]],
    exclusions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate all valid variant combinations from option axes.

    Args:
        product: Product dict with product_id, title, etc.
        options: List of OptionAxis dicts, each with name and values.
        exclusions: Optional list of ExclusionRule dicts to filter combos.

    Returns:
        Structured dict with generated variants.
    """
    try:
        options = copy.deepcopy(options)
        exclusions = copy.deepcopy(exclusions) if exclusions else []

        if not options:
            return _fail("At least one option axis is required")

        # Validate each axis has a name and at least one value
        for idx, axis in enumerate(options):
            name = axis.get("name", "")
            values = axis.get("values", [])
            if not name:
                return _fail(f"Option axis at index {idx} has no name")
            if not values:
                return _fail(f"Option axis '{name}' has no values")

        # Build axis names and value lists for cartesian product
        axis_names = [axis["name"] for axis in options]
        axis_values = [axis["values"] for axis in options]

        # Check for duplicate axis names
        if len(set(axis_names)) != len(axis_names):
            return _fail("Duplicate option axis names detected")

        # Generate all combinations via cartesian product
        all_combos = list(itertools.product(*axis_values))

        # Apply exclusion rules
        excluded_count = 0
        variants: list[dict[str, Any]] = []
        position = 1

        for combo in all_combos:
            combo_dict = dict(zip(axis_names, combo))

            if _is_excluded(combo_dict, exclusions):
                excluded_count += 1
                continue

            variants.append({
                "options": combo_dict,
                "position": position,
            })
            position += 1

        return {
            "status": "success",
            "variants": variants,
            "total": len(variants),
            "excluded": excluded_count,
        }
    except Exception as exc:
        return _fail(f"Variant generation failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_excluded(
    combo: dict[str, str],
    exclusions: list[dict[str, Any]],
) -> bool:
    """Check if a combination matches any exclusion rule.

    An exclusion rule matches when ALL its conditions match the combo.
    """
    for rule in exclusions:
        conditions = rule.get("conditions", rule)
        # If the rule is a flat dict without 'conditions' key, treat entire dict
        # as conditions (supports both {"conditions": {...}} and plain {...}).
        if not isinstance(conditions, dict):
            continue

        if not conditions:
            continue

        match = True
        for key, value in conditions.items():
            if combo.get(key) != value:
                match = False
                break

        if match:
            return True

    return False


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized error dict."""
    return {
        "status": "error",
        "variants": [],
        "total": 0,
        "excluded": 0,
        "error": reason,
    }
