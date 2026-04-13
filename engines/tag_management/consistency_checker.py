"""Tag Management Engine — consistency checker.

Checks tag consistency: similar tags that should be merged,
case mismatches, plural/singular variants, and orphaned tags.
"""
from __future__ import annotations

import copy
from typing import Any


def check_consistency(
    tag_assignments: list[dict[str, Any]],
    taxonomy: dict[str, Any],
) -> dict[str, Any]:
    """Check tag consistency across the catalog.

    Args:
        tag_assignments: Current tag assignments.
        taxonomy: Taxonomy tree.

    Returns:
        Structured dict with consistency issues and score.
    """
    try:
        assignments = copy.deepcopy(tag_assignments)
        issues: list[dict[str, Any]] = []

        # Collect all used tags
        all_tags: set[str] = set()
        for a in assignments:
            for tag in a.get("tags", []):
                all_tags.add(tag)

        tag_list = sorted(all_tags)
        total_checks = 0
        passed_checks = 0

        # Check for near-duplicates (simple plural/singular)
        for i, t1 in enumerate(tag_list):
            total_checks += 1
            found_dup = False
            for t2 in tag_list[i+1:]:
                if _are_similar(t1, t2):
                    issues.append({
                        "type": "near_duplicate",
                        "tags": [t1, t2],
                        "suggestion": f"Merge '{t1}' and '{t2}'",
                    })
                    found_dup = True
            if not found_dup:
                passed_checks += 1

        # Check for case inconsistencies
        lower_map: dict[str, list[str]] = {}
        for tag in all_tags:
            key = tag.lower()
            if key not in lower_map:
                lower_map[key] = []
            lower_map[key].append(tag)

        for key, variants in lower_map.items():
            total_checks += 1
            if len(variants) > 1:
                issues.append({
                    "type": "case_mismatch",
                    "tags": variants,
                    "suggestion": f"Standardize case for: {', '.join(variants)}",
                })
            else:
                passed_checks += 1

        # Check taxonomy orphans
        tree = taxonomy.get("tree", {})
        for tag in all_tags:
            total_checks += 1
            if tag not in tree:
                issues.append({
                    "type": "orphan_tag",
                    "tags": [tag],
                    "suggestion": f"Tag '{tag}' not in taxonomy — add or remove",
                })
            else:
                passed_checks += 1

        consistency_score = round(
            passed_checks / total_checks * 100, 1
        ) if total_checks > 0 else 100.0

        return {
            "status": "success",
            "issues": issues,
            "total_issues": len(issues),
            "consistency_score": consistency_score,
        }
    except Exception as exc:
        return {
            "status": "error",
            "issues": [],
            "consistency_score": 0.0,
            "error": f"Consistency check failed: {exc}",
        }


def _are_similar(a: str, b: str) -> bool:
    """Check if two tags are likely the same concept."""
    la, lb = a.lower(), b.lower()
    # Plural/singular
    if la + "s" == lb or lb + "s" == la:
        return True
    if la + "es" == lb or lb + "es" == la:
        return True
    # Hyphen vs space
    if la.replace("-", " ") == lb.replace("-", " ") and la != lb:
        return True
    return False
