"""Product Variant Engine — memory writer.

Persists variant generation results to disk for future reference.
Each run is stored as a separate JSON file keyed by record_id.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_variant_record(
    product_id: str,
    product_code: str,
    variants: list[dict[str, Any]],
    skus: list[dict[str, Any]],
    prices: list[dict[str, Any]],
    validation: dict[str, Any],
    total_variants: int,
    excluded_count: int,
) -> dict[str, Any]:
    """Write a variant generation result record to memory.

    Args:
        product_id: Product identifier.
        product_code: Product code used for SKUs.
        variants: List of generated variant dicts.
        skus: List of SKU records.
        prices: List of price records.
        validation: Validation result dict.
        total_variants: Total number of generated variants.
        excluded_count: Number of excluded combinations.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "product_id": product_id,
            "product_code": product_code,
            "total_variants": total_variants,
            "excluded_count": excluded_count,
            "is_valid": validation.get("is_valid", False),
            "duplicate_sku_count": len(validation.get("duplicate_skus", [])),
            "price_anomaly_count": len(validation.get("price_anomalies", [])),
            "warning_count": len(validation.get("warnings", [])),
            "sku_sample": copy.deepcopy(skus[:5]),
            "price_sample": copy.deepcopy(prices[:5]),
        }

        _ensure_memory_dir()
        fpath = os.path.join(_MEMORY_DIR, f"{record_id}.json")
        with open(fpath, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, default=str)

        return {
            "status": "success",
            "record_id": record_id,
            "path": fpath,
        }
    except Exception as exc:
        return {
            "status": "warning",
            "record_id": None,
            "path": None,
            "note": f"Memory write failed (non-fatal): {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_memory_dir() -> None:
    """Create the memory directory if it doesn't exist."""
    os.makedirs(_MEMORY_DIR, exist_ok=True)
