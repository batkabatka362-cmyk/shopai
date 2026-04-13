"""LTV:CAC Dashboard Engine — memory writer."""
from __future__ import annotations
import copy, json, os, time, uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")

def write_ltv_cac_result(
    ltv: dict[str, Any], cac: dict[str, Any], ratio: float,
    trend: str, alerts: list[dict[str, Any]], payback_months: float,
) -> dict[str, Any]:
    try:
        record_id = uuid.uuid4().hex[:12]
        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ltv": copy.deepcopy(ltv), "cac": copy.deepcopy(cac),
            "ratio": ratio, "trend": trend,
            "alerts_count": len(alerts), "payback_months": payback_months,
            "outcome_actual": None,
        }
        _ensure_memory_dir()
        fpath = os.path.join(_MEMORY_DIR, f"{record_id}.json")
        with open(fpath, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, default=str)
        return {"status": "success", "record_id": record_id, "path": fpath}
    except Exception as exc:
        return {"status": "warning", "record_id": None, "path": None, "note": f"Memory write failed (non-fatal): {exc}"}

def _ensure_memory_dir() -> None:
    os.makedirs(_MEMORY_DIR, exist_ok=True)
