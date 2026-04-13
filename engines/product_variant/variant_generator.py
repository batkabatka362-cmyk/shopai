"""Product Variant Engine — variant generator.

Generates all valid variant combinations from option axes,
applying exclusion rules to filter out invalid combos.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import itertools
from typing import Any


def generate_variants(
    product: dict[str, Any],
    options: list[dict[str, Any]],
    exclusions: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Generate all valid variant combinations from option axes.

    Args:
        product: Product dict with id, title, etc.
        options: List of option axis dicts, each with 'name' and 'values'.
        exclusions: Optional list of dicts describing combos to exclude.
            Each dict maps option names to values that should be skipped.

    Returns:
        Structured dict with generated variants.
    """
    try:
        options = copy.deepcopy(options)
        exclusions = copy.deepcopy(exclusions) if exclusions else []

        if not options:
            return _fail("No option axes provided")

        # Validate option axes
        axis_names: list[str] = []
        axis_values: list[list[str]] = []
        for opt in options:
            name = opt.get("name", "")
            values = opt.get("values", [])
            if not name:
                return _fail("Option axis missing 'name'")
            if not values:
                return _fail(f"Option axis '{name}' has no values")
            axis_names.append(name)
            axis_values.append(values)

        # Generate all combinations using itertools.product
        all_combos = list(itertools.product(*axis_values))

        variants: list[dict[str, Any]] = []
        excluded_count = 0
        position = 1

        for combo in all_combos:
            combo_dict = dict(zip(axis_names, combo))

            # Check exclusion rules
            if _matches_exclusion(combo_dict, exclusions):
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

def _matches_exclusion(
    combo: dict[str, str],
    exclusions: list[dict[str, str]],
) -> bool:
    """Check if a combo matches any exclusion rule.

    An exclusion rule matches if ALL keys in the rule match the combo.
    """
    for rule in exclusions:
        if not rule:
            continue
        match = True
        for key, value in rule.items():
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
