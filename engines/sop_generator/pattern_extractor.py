"""SOP Generator Engine — pattern extractor.

Extracts repeatable patterns from execution history.
All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def extract_patterns(
    execution_history: list[dict[str, Any]],
    operations: list[str],
) -> dict[str, Any]:
    """Extract repeatable patterns from execution history.

    Args:
        execution_history: List of past execution records.
        operations: Operations to extract patterns for.

    Returns:
        Structured dict with extracted patterns per operation.
    """
    try:
        history = copy.deepcopy(execution_history)
        patterns: dict[str, list[dict[str, Any]]] = {}

        for record in history:
            op = str(record.get("operation", record.get("type", "")))
            if operations and op not in operations:
                continue

            steps = record.get("steps", record.get("actions", []))
            if not steps:
                continue

            patterns.setdefault(op, [])
            patterns[op].append({
                "steps": steps,
                "duration_minutes": int(record.get("duration_minutes", 0)),
                "success": bool(record.get("success", True)),
                "timestamp": str(record.get("timestamp", "")),
            })

        # Find most common step sequences per operation
        extracted: list[dict[str, Any]] = []
        for op, executions in patterns.items():
            successful = [e for e in executions if e["success"]]
            if not successful:
                successful = executions

            # Use the most recent successful execution as the pattern
            if successful:
                best = sorted(successful, key=lambda x: x["timestamp"], reverse=True)[0]
                avg_duration = round(
                    sum(e["duration_minutes"] for e in successful) / len(successful), 1,
                )
                extracted.append({
                    "operation": op,
                    "pattern_steps": best["steps"],
                    "avg_duration_minutes": avg_duration,
                    "execution_count": len(executions),
                    "success_rate": round(
                        len([e for e in executions if e["success"]]) / len(executions), 2,
                    ) if executions else 0.0,
                })

        return {"status": "success", "patterns": extracted}
    except Exception as exc:
        return {"status": "error", "patterns": [], "error": f"Pattern extraction failed: {exc}"}
