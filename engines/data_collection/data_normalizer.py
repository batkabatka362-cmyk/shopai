"""Data Collection Engine — data normalizer.

Normalizes fetched data from heterogeneous sources into a common
record format for downstream processing.
"""
from __future__ import annotations

import copy
import time
from typing import Any


def normalize_data(
    fetched_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """Normalize fetched data into a common format.

    Args:
        fetched_sources: List of FetchedSourceData dicts.

    Returns:
        Structured dict with normalized records per source.
    """
    try:
        sources = copy.deepcopy(fetched_sources)
        normalized: dict[str, list[dict[str, Any]]] = {}
        total_normalized = 0
        skipped = 0

        for source_data in sources:
            source_name = source_data.get("source", "unknown")
            records = source_data.get("records", [])
            source_normalized: list[dict[str, Any]] = []

            for idx, record in enumerate(records):
                try:
                    norm = _normalize_record(record, source_name, idx)
                    source_normalized.append(norm)
                    total_normalized += 1
                except Exception:
                    skipped += 1
                    continue

            normalized[source_name] = source_normalized

        return {
            "status": "success",
            "normalized": normalized,
            "total_normalized": total_normalized,
            "skipped": skipped,
        }
    except Exception as exc:
        return {
            "status": "error",
            "normalized": {},
            "total_normalized": 0,
            "error": f"Normalization failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_record(
    record: dict[str, Any],
    source: str,
    index: int,
) -> dict[str, Any]:
    """Normalize a single record to common format."""
    record_id = str(record.get("id", f"{source}_{index}"))
    entity_type = _infer_entity_type(record)
    timestamp = str(
        record.get("timestamp")
        or record.get("created_at")
        or record.get("date")
        or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )

    return {
        "id": record_id,
        "source": source,
        "entity_type": entity_type,
        "data": record,
        "timestamp": timestamp,
    }


def _infer_entity_type(record: dict[str, Any]) -> str:
    """Infer the entity type from record fields."""
    if "order_id" in record or "order_number" in record:
        return "order"
    if "product_id" in record or "sku" in record:
        return "product"
    if "customer_id" in record or "email" in record:
        return "customer"
    if "session_id" in record or "page_views" in record:
        return "session"
    if "transaction_id" in record or "amount" in record:
        return "transaction"
    return "generic"
