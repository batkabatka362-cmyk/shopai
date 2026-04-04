"""Selection Reasoning Engine — comparison builder.

Builds comparisons between selected and rejected products,
highlighting advantages and disadvantages.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def build_comparisons(
    decisions: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build comparisons for each product.

    Args:
        decisions: List of decision record dicts.
        evidence: List of evidence item dicts.

    Returns:
        Structured dict with per-product comparisons.
    """
    try:
        evidence_map: dict[str, list[dict[str, Any]]] = {}
        for e in evidence:
            pid = str(e.get("product_id", ""))
            if pid:
                evidence_map.setdefault(pid, []).append(e)

        # Split selected vs rejected
        selected_ids = [
            str(d.get("product_id", "")) for d in decisions
            if d.get("verdict") == "selected"
        ]
        rejected_ids = [
            str(d.get("product_id", "")) for d in decisions
            if d.get("verdict") != "selected"
        ]

        # Extract metric values per product
        metric_values: dict[str, dict[str, float]] = {}
        for pid, evs in evidence_map.items():
            values: dict[str, float] = {}
            for ev in evs:
                metric = str(ev.get("metric", ""))
                val = ev.get("value")
                if metric and isinstance(val, (int, float)):
                    values[metric] = float(val)
            metric_values[pid] = values

        comparisons: list[dict[str, Any]] = []

        for decision in decisions:
            pid = str(decision.get("product_id", "unknown"))
            verdict = str(decision.get("verdict", ""))
            my_values = metric_values.get(pid, {})

            # Compare against opposite group
            compare_group = rejected_ids if verdict == "selected" else selected_ids
            compared_to = compare_group[:3]

            advantages: list[str] = []
            disadvantages: list[str] = []

            for other_pid in compared_to:
                other_values = metric_values.get(other_pid, {})
                for metric in my_values:
                    if metric in other_values:
                        if my_values[metric] > other_values[metric]:
                            advantages.append(f"Higher {metric} than {other_pid}")
                        elif my_values[metric] < other_values[metric]:
                            disadvantages.append(f"Lower {metric} than {other_pid}")

            # Deduplicate
            advantages = list(dict.fromkeys(advantages))[:5]
            disadvantages = list(dict.fromkeys(disadvantages))[:5]

            comparisons.append({
                "product_id": pid,
                "compared_to": compared_to,
                "advantages": advantages if advantages else ["No clear metric advantages identified"],
                "disadvantages": disadvantages if disadvantages else ["No clear metric disadvantages identified"],
            })

        return {"status": "success", "comparisons": comparisons}
    except Exception as exc:
        return {"status": "error", "comparisons": [], "error": f"Comparison building failed: {exc}"}
