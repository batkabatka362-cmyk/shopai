"""Auto-scaling engine with load-based recommendations."""

import time
from datetime import datetime, timezone
from typing import Optional


class AutoScaler:
    """Evaluate metrics and manage resource scaling decisions."""

    def __init__(self):
        self._resources: dict[str, dict] = {}
        self._limits: dict[str, dict] = {}
        self._history: list[dict] = []

    def evaluate(self, metrics: dict, config: dict) -> dict:
        """Evaluate current metrics and return a scaling recommendation.

        Args:
            metrics: Dict with metric values (e.g. cpu_usage, memory_usage, request_rate).
            config: Scaling config with thresholds:
                - scale_up_threshold (float): load factor above this triggers scale-up (default 0.8)
                - scale_down_threshold (float): load factor below this triggers scale-down (default 0.3)
                - cooldown_seconds (int): min seconds between scale actions (default 300)
                - resource (str): resource name to evaluate

        Returns:
            Dict with recommendation ('scale_up', 'scale_down', or 'none') and details.
        """
        resource = config.get("resource", "default")
        scale_up_thresh = config.get("scale_up_threshold", 0.8)
        scale_down_thresh = config.get("scale_down_threshold", 0.3)
        cooldown = config.get("cooldown_seconds", 300)

        load_factor = self._calculate_load_factor(metrics)

        # Check cooldown
        if self._history:
            last_action_time = self._history[-1].get("timestamp_epoch", 0)
            if time.time() - last_action_time < cooldown:
                return {
                    "recommendation": "none",
                    "reason": "cooldown_active",
                    "load_factor": round(load_factor, 4),
                    "resource": resource,
                }

        current = self._resources.get(resource, {}).get("count", 1)
        limits = self._limits.get(resource, {"min": 1, "max": 100})

        if load_factor >= scale_up_thresh and current < limits["max"]:
            return {
                "recommendation": "scale_up",
                "reason": f"load_factor {load_factor:.4f} >= {scale_up_thresh}",
                "load_factor": round(load_factor, 4),
                "resource": resource,
                "current_count": current,
                "suggested_count": min(current + 1, limits["max"]),
            }
        elif load_factor <= scale_down_thresh and current > limits["min"]:
            return {
                "recommendation": "scale_down",
                "reason": f"load_factor {load_factor:.4f} <= {scale_down_thresh}",
                "load_factor": round(load_factor, 4),
                "resource": resource,
                "current_count": current,
                "suggested_count": max(current - 1, limits["min"]),
            }
        else:
            return {
                "recommendation": "none",
                "reason": "within_thresholds",
                "load_factor": round(load_factor, 4),
                "resource": resource,
                "current_count": current,
            }

    def scale_up(self, resource: str, count: int = 1) -> dict:
        """Scale a resource up by count instances."""
        if resource not in self._resources:
            self._resources[resource] = {"count": 1, "status": "running"}

        old_count = self._resources[resource]["count"]
        limits = self._limits.get(resource, {"min": 1, "max": 100})
        new_count = min(old_count + count, limits["max"])
        self._resources[resource]["count"] = new_count

        record = {
            "action": "scale_up",
            "resource": resource,
            "old_count": old_count,
            "new_count": new_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp_epoch": time.time(),
        }
        self._history.append(record)
        return record

    def scale_down(self, resource: str, count: int = 1) -> dict:
        """Scale a resource down by count instances."""
        if resource not in self._resources:
            self._resources[resource] = {"count": 1, "status": "running"}

        old_count = self._resources[resource]["count"]
        limits = self._limits.get(resource, {"min": 1, "max": 100})
        new_count = max(old_count - count, limits["min"])
        self._resources[resource]["count"] = new_count

        record = {
            "action": "scale_down",
            "resource": resource,
            "old_count": old_count,
            "new_count": new_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp_epoch": time.time(),
        }
        self._history.append(record)
        return record

    def get_current_scale(self) -> dict:
        """Get the current scale for all resources."""
        return {
            name: {"count": info["count"], "status": info.get("status", "unknown")}
            for name, info in self._resources.items()
        }

    def set_limits(self, resource: str, min_count: int, max_count: int) -> None:
        """Set scaling limits for a resource."""
        if min_count < 0:
            raise ValueError("min_count must be >= 0")
        if max_count < min_count:
            raise ValueError("max_count must be >= min_count")
        self._limits[resource] = {"min": min_count, "max": max_count}

    def _calculate_load_factor(self, metrics: dict) -> float:
        """Calculate a composite load factor from metrics (0.0 - 1.0).

        Considers cpu_usage, memory_usage, and request_rate if present.
        Values should be normalized 0-1 or 0-100; values > 1 are treated as percentages.
        """
        weights = {
            "cpu_usage": 0.4,
            "memory_usage": 0.3,
            "request_rate": 0.3,
        }
        total_weight = 0.0
        weighted_sum = 0.0

        for metric, weight in weights.items():
            if metric in metrics:
                value = float(metrics[metric])
                if value > 1.0:
                    value = value / 100.0  # normalize percentage to 0-1
                value = max(0.0, min(1.0, value))
                weighted_sum += value * weight
                total_weight += weight

        if total_weight == 0:
            # Fallback: average all provided metrics
            vals = [float(v) for v in metrics.values() if isinstance(v, (int, float))]
            if not vals:
                return 0.0
            avg = sum(vals) / len(vals)
            if avg > 1.0:
                avg = avg / 100.0
            return max(0.0, min(1.0, avg))

        return weighted_sum / total_weight
