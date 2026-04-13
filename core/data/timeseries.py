"""Time Series Analyzer — trend analysis per data domain over time."""
from __future__ import annotations
import threading as _threading
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("data.timeseries")


class TimeSeriesAnalyzer:
    """Analyze trends in DataArchitecture domains over time."""

    def trend(self, domain: str, metric: str = "score",
              days: int = 7) -> dict[str, Any]:
        """Get trend for a domain metric over time."""
        try:
            from core.data.architecture import get_data_architecture
            da = get_data_architecture()
        except Exception:
            return {"error": "unavailable"}

        since = time.time() - (days * 86400)
        records = da.query(domain, since=since, limit=200)

        if len(records) < 2:
            return {"domain": domain, "trend": "insufficient_data", "points": len(records)}

        values = []
        for r in records:
            val = r.get(metric, r.get("score", 0))
            if isinstance(val, (int, float)):
                values.append(float(val))

        if not values:
            return {"domain": domain, "trend": "no_numeric_data"}

        n = len(values)
        first_half = values[:n//2]
        second_half = values[n//2:]
        avg_first = sum(first_half) / len(first_half)
        avg_second = sum(second_half) / len(second_half)

        if avg_second > avg_first * 1.05:
            trend = "improving"
        elif avg_second < avg_first * 0.95:
            trend = "declining"
        else:
            trend = "stable"

        return {
            "domain": domain,
            "metric": metric,
            "trend": trend,
            "points": n,
            "avg_early": round(avg_first, 2),
            "avg_recent": round(avg_second, 2),
            "change_pct": round((avg_second - avg_first) / max(avg_first, 0.01) * 100, 1),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
        }

    def all_domains(self, days: int = 7) -> dict[str, Any]:
        """Get trends for all domains."""
        from core.data.architecture import DOMAIN_NAMES
        results = {}
        for domain in DOMAIN_NAMES:
            results[domain] = self.trend(domain, days=days)
        improving = sum(1 for r in results.values() if r.get("trend") == "improving")
        declining = sum(1 for r in results.values() if r.get("trend") == "declining")
        return {
            "domains": results,
            "improving": improving,
            "declining": declining,
            "stable": len(DOMAIN_NAMES) - improving - declining,
        }


_instance = None
_instance_lock = _threading.Lock()

def get_timeseries():
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = TimeSeriesAnalyzer()
    return _instance
