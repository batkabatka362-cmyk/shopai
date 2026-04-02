"""Global Brain — data ingestor.

Ingests engine outputs, normalizes format, validates structure,
and extracts source metadata. Converts raw engine output into
a list of RawKnowledge items ready for extraction.

No connections to other modules — called only from flow.py.
"""
from __future__ import annotations

import copy
import time
from typing import Any


def ingest_engine_output(
    source_engine: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Ingest a single engine output and produce normalized raw knowledge items.

    Args:
        source_engine: Name of the engine that produced this output.
        data: The engine's output data dict.

    Returns:
        Structured dict with status, raw_items list, and metadata.
    """
    try:
        safe_data = copy.deepcopy(data)
        if not isinstance(safe_data, dict):
            return {
                "status": "error",
                "raw_items": [],
                "source_metadata": {},
                "error": "data must be a dict",
            }

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        raw_items: list[dict[str, Any]] = []

        # Extract insights
        insights = safe_data.get("insights", [])
        if isinstance(insights, list):
            for insight in insights:
                if isinstance(insight, str) and insight.strip():
                    raw_items.append({
                        "source_engine": source_engine,
                        "content": insight.strip(),
                        "category": "insight",
                        "timestamp": timestamp,
                        "raw_data": {"original": insight},
                    })
                elif isinstance(insight, dict):
                    content = insight.get("detail", "") or insight.get("content", "") or str(insight)
                    if content.strip():
                        raw_items.append({
                            "source_engine": source_engine,
                            "content": content.strip(),
                            "category": "insight",
                            "timestamp": timestamp,
                            "raw_data": insight,
                        })

        # Extract errors
        errors = safe_data.get("errors", [])
        if isinstance(errors, list):
            for error in errors:
                if isinstance(error, str) and error.strip():
                    raw_items.append({
                        "source_engine": source_engine,
                        "content": error.strip(),
                        "category": "error",
                        "timestamp": timestamp,
                        "raw_data": {"original": error},
                    })
                elif isinstance(error, dict):
                    err_type = error.get("type", "unknown")
                    detail = error.get("detail", "") or error.get("message", "")
                    content = f"{err_type}: {detail}" if detail else err_type
                    if content.strip():
                        raw_items.append({
                            "source_engine": source_engine,
                            "content": content.strip(),
                            "category": "error",
                            "timestamp": timestamp,
                            "raw_data": error,
                        })

        # Extract patterns
        patterns = safe_data.get("patterns", [])
        if isinstance(patterns, list):
            for pattern in patterns:
                if isinstance(pattern, str) and pattern.strip():
                    raw_items.append({
                        "source_engine": source_engine,
                        "content": pattern.strip(),
                        "category": "pattern",
                        "timestamp": timestamp,
                        "raw_data": {"original": pattern},
                    })
                elif isinstance(pattern, dict):
                    p_type = pattern.get("type", "general")
                    detail = pattern.get("detail", "") or pattern.get("description", "")
                    content = f"{p_type}: {detail}" if detail else p_type
                    if content.strip():
                        raw_items.append({
                            "source_engine": source_engine,
                            "content": content.strip(),
                            "category": "pattern",
                            "timestamp": timestamp,
                            "raw_data": pattern,
                        })

        # Extract metrics
        metrics = safe_data.get("metrics", [])
        if isinstance(metrics, list):
            for metric in metrics:
                if isinstance(metric, str) and metric.strip():
                    raw_items.append({
                        "source_engine": source_engine,
                        "content": metric.strip(),
                        "category": "metric",
                        "timestamp": timestamp,
                        "raw_data": {"original": metric},
                    })
                elif isinstance(metric, dict):
                    name = metric.get("name", "")
                    value = metric.get("value", "")
                    content = f"{name}: {value}" if name else str(metric)
                    if content.strip():
                        raw_items.append({
                            "source_engine": source_engine,
                            "content": content.strip(),
                            "category": "metric",
                            "timestamp": timestamp,
                            "raw_data": metric,
                        })

        # Extract any top-level string fields not yet captured
        _known_keys = {"insights", "errors", "patterns", "metrics"}
        for key, value in safe_data.items():
            if key in _known_keys:
                continue
            if isinstance(value, str) and value.strip():
                raw_items.append({
                    "source_engine": source_engine,
                    "content": value.strip(),
                    "category": "insight",
                    "timestamp": timestamp,
                    "raw_data": {key: value},
                })
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.strip():
                        raw_items.append({
                            "source_engine": source_engine,
                            "content": item.strip(),
                            "category": "insight",
                            "timestamp": timestamp,
                            "raw_data": {key: item},
                        })

        source_metadata = {
            "source_engine": source_engine,
            "ingested_at": timestamp,
            "items_extracted": len(raw_items),
            "input_keys": list(safe_data.keys()),
        }

        return {
            "status": "success",
            "raw_items": raw_items,
            "source_metadata": source_metadata,
            "error": None,
        }

    except Exception as exc:
        return {
            "status": "error",
            "raw_items": [],
            "source_metadata": {},
            "error": f"Ingestion failed: {exc}",
        }
