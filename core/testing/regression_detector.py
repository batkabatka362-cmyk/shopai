"""RegressionDetector — detects performance/quality regressions."""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("testing.regression")


class RegressionDetector:
    """Compares current results against baselines to detect regressions."""

    def __init__(self) -> None:
        self._baselines: dict[str, dict[str, Any]] = {}

    def set_baseline(self, engine_name: str, metrics: dict[str, float]) -> None:
        """Set baseline metrics for an engine."""
        self._baselines[engine_name] = {
            "metrics": dict(metrics),
            "set_at": time.time(),
        }

    def check(self, engine_name: str, current: dict[str, float], thresholds: dict[str, float] | None = None) -> dict[str, Any]:
        """Check for regressions against baseline."""
        baseline = self._baselines.get(engine_name)
        if baseline is None:
            return {"engine": engine_name, "status": "no_baseline", "regressions": []}

        base_metrics = baseline["metrics"]
        thresh = thresholds or {}
        regressions = []

        for metric, current_val in current.items():
            base_val = base_metrics.get(metric)
            if base_val is None:
                continue

            threshold = thresh.get(metric, 0.1)  # 10% default threshold

            # For success_rate, higher is better
            # For elapsed_seconds, lower is better
            if "rate" in metric or "score" in metric:
                # Higher is better
                if base_val > 0 and (base_val - current_val) / base_val > threshold:
                    regressions.append({
                        "metric": metric,
                        "baseline": base_val,
                        "current": current_val,
                        "change_pct": round((current_val - base_val) / base_val * 100, 2),
                        "severity": "high" if (base_val - current_val) / base_val > 0.2 else "medium",
                    })
            else:
                # Lower is better (time, errors)
                if base_val > 0 and (current_val - base_val) / base_val > threshold:
                    regressions.append({
                        "metric": metric,
                        "baseline": base_val,
                        "current": current_val,
                        "change_pct": round((current_val - base_val) / base_val * 100, 2),
                        "severity": "high" if (current_val - base_val) / base_val > 0.3 else "medium",
                    })

        return {
            "engine": engine_name,
            "status": "regression" if regressions else "ok",
            "regressions": regressions,
            "metrics_checked": len(current),
        }

    def check_batch(self, results: dict[str, dict[str, float]]) -> dict[str, Any]:
        """Check multiple engines for regressions."""
        checks = {}
        for engine, metrics in results.items():
            checks[engine] = self.check(engine, metrics)

        regressed = [e for e, r in checks.items() if r["status"] == "regression"]
        return {
            "total_checked": len(checks),
            "regressed": len(regressed),
            "regressed_engines": regressed,
            "checks": checks,
        }

    def get_baselines(self) -> dict[str, dict[str, Any]]:
        return dict(self._baselines)
