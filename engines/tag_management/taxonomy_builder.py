"""Tag Management Engine — taxonomy builder.

Builds and maintains a hierarchical taxonomy tree from
tags and categories. Identifies parent-child relationships.
"""
from __future__ import annotations

import copy
from typing import Any


def build_taxonomy(
    tag_assignments: list[dict[str, Any]],
    existing_taxonomy: dict[str, Any],
) -> dict[str, Any]:
    """Build/update taxonomy tree from tag assignments.

    Args:
        tag_assignments: Auto-generated tag assignments.
        existing_taxonomy: Current taxonomy structure.

    Returns:
        Structured dict with updated taxonomy.
    """
    try:
        assignments = copy.deepcopy(tag_assignments)
        taxonomy = copy.deepcopy(existing_taxonomy) or {}

        # Count tag frequency
        tag_freq: dict[str, int] = {}
        tag_co_occurrence: dict[str, dict[str, int]] = {}

        for assignment in assignments:
            tags = assignment.get("tags", [])
            for tag in tags:
                tag_freq[tag] = tag_freq.get(tag, 0) + 1

            # Co-occurrence for hierarchy inference
            for i, t1 in enumerate(tags):
                if t1 not in tag_co_occurrence:
                    tag_co_occurrence[t1] = {}
                for t2 in tags[i+1:]:
                    tag_co_occurrence[t1][t2] = tag_co_occurrence[t1].get(t2, 0) + 1

        # Build tree from existing + new tags
        tree = taxonomy.get("tree", {})
        updates: list[dict[str, Any]] = []

        for tag, freq in sorted(tag_freq.items(), key=lambda x: x[1], reverse=True):
            if tag not in tree:
                # Try to find parent from co-occurrence
                parent = None
                co = tag_co_occurrence.get(tag, {})
                if co:
                    # Most co-occurring tag with higher frequency is potential parent
                    candidates = [
                        (t, c) for t, c in co.items()
                        if tag_freq.get(t, 0) > freq
                    ]
                    if candidates:
                        parent = max(candidates, key=lambda x: x[1])[0]

                tree[tag] = {
                    "parent": parent,
                    "frequency": freq,
                    "children": [],
                }
                updates.append({
                    "action": "added",
                    "tag": tag,
                    "parent": parent,
                })
            else:
                tree[tag]["frequency"] = freq

        # Populate children lists
        for tag, node in tree.items():
            parent = node.get("parent")
            if parent and parent in tree:
                if tag not in tree[parent].get("children", []):
                    tree[parent].setdefault("children", []).append(tag)

        return {
            "status": "success",
            "taxonomy": {"tree": tree},
            "updates": updates,
            "total_tags": len(tree),
        }
    except Exception as exc:
        return {
            "status": "error",
            "taxonomy": {},
            "error": f"Taxonomy building failed: {exc}",
        }
