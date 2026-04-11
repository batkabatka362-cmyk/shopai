import uuid
from datetime import datetime, timezone


def generate_id(prefix: str = "") -> str:
    uid = uuid.uuid4().hex[:12]
    return f"{prefix}_{uid}" if prefix else uid


def timestamp_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(val, default: float = 0.0) -> float:
    """Convert any value to float safely. Never crashes."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val.replace("$", "").replace(",", "").strip())
        except (ValueError, TypeError):
            return default
    return default


def safe_int(val, default: int = 0) -> int:
    """Convert any value to int safely. Never crashes."""
    if val is None:
        return default
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    if isinstance(val, str):
        try:
            return int(float(val.replace(",", "").strip()))
        except (ValueError, TypeError):
            return default
    return default


def safe_dict(val, default: dict | None = None) -> dict:
    """Ensure value is a dict. Never crashes."""
    if isinstance(val, dict):
        return val
    return default if default is not None else {}
