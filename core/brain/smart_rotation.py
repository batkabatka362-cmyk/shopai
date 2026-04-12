"""Smart Rotation — ensures different products get attention each cycle.

Problems solved:
  1. Same products analyzed every cycle → rotation
  2. No time awareness → seasonal/daily/weekly patterns
  3. DecisionEngine too conservative → exploration boost
  4. Competitor data stale → cache invalidation
"""
from __future__ import annotations
import math
import threading as _threading
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("brain.rotation")


class ProductRotation:
    """Rotates which products get deep analysis each cycle."""

    def __init__(self) -> None:
        self._cycle = 0
        self._last_analyzed: dict[str, float] = {}

    def select(self, products: list[dict], count: int = 5) -> list[dict]:
        """Select products for this cycle — prioritize least-recently-analyzed."""
        self._cycle += 1

        scored = []
        for p in products:
            pid = str(p.get("id", ""))
            last = self._last_analyzed.get(pid, 0)
            staleness = time.time() - last if last else 999999

            # Priority: stale > low margin > high price
            price = float(p.get("price", 0))
            cost = float(p.get("cost", 0))
            from utils.finance import margin as _margin
            margin = _margin(price, cost, default=0.5)

            priority = staleness * 0.5 + (1 - margin) * 100 + price * 0.1
            scored.append((priority, p))

        scored.sort(key=lambda x: -x[0])
        selected = [p for _, p in scored[:count]]

        for p in selected:
            self._last_analyzed[str(p.get("id", ""))] = time.time()

        return selected

    def get_stats(self) -> dict:
        return {"cycles": self._cycle, "products_tracked": len(self._last_analyzed)}


class TimeAwareness:
    """Adds time context to decisions — hour, day, season."""

    @staticmethod
    def get_context() -> dict[str, Any]:
        now = time.localtime()
        hour = now.tm_hour
        weekday = now.tm_wday  # 0=Monday
        month = now.tm_mon
        day_of_month = now.tm_mday

        # Time of day
        if 6 <= hour < 12:
            period = "morning"
        elif 12 <= hour < 17:
            period = "afternoon"
        elif 17 <= hour < 22:
            period = "evening"
        else:
            period = "night"

        # Day type
        is_weekend = weekday >= 5
        day_name = ["Monday", "Tuesday", "Wednesday", "Thursday",
                    "Friday", "Saturday", "Sunday"][weekday]

        # Season (Northern hemisphere)
        if month in (12, 1, 2):
            season = "winter"
        elif month in (3, 4, 5):
            season = "spring"
        elif month in (6, 7, 8):
            season = "summer"
        else:
            season = "fall"

        # E-commerce signals
        signals = []
        if is_weekend:
            signals.append("weekend_traffic_higher")
        if period == "evening":
            signals.append("peak_shopping_hours")
        if day_of_month <= 5:
            signals.append("payday_period")
        if month == 11:
            signals.append("pre_black_friday")
        if month == 12:
            signals.append("holiday_season")

        return {
            "hour": hour,
            "period": period,
            "day": day_name,
            "is_weekend": is_weekend,
            "month": month,
            "season": season,
            "signals": signals,
            "shopping_intensity": 0.8 if is_weekend or period == "evening" else 0.5,
        }


class ExplorationBoost:
    """Boosts exploration when decisions are too repetitive."""

    def __init__(self) -> None:
        self._action_history: list[str] = []

    def record(self, action: str) -> None:
        self._action_history.append(action)
        if len(self._action_history) > 100:
            self._action_history = self._action_history[-100:]

    def should_explore(self) -> dict[str, Any]:
        """Check if we're stuck in a rut."""
        if len(self._action_history) < 10:
            return {"explore": False, "reason": "insufficient_data"}

        recent = self._action_history[-10:]
        # Count unique actions
        unique = len(set(recent))
        repetition = 1 - (unique / len(recent))

        # If >70% same action, boost exploration
        most_common = max(set(recent), key=recent.count)
        freq = recent.count(most_common) / len(recent)

        return {
            "explore": freq > 0.7,
            "repetition_rate": round(repetition, 2),
            "most_common": most_common,
            "frequency": round(freq, 2),
            "suggestion": "Try something other than {}".format(most_common) if freq > 0.7 else "Good diversity",
            "unique_last_10": unique,
        }

    def get_stats(self) -> dict:
        return {"history_size": len(self._action_history)}


class CompetitorCacheManager:
    """Manages competitor data freshness."""

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._ttl = ttl_seconds
        self._last_fetch: dict[str, float] = {}

    def is_stale(self, product_id: str) -> bool:
        last = self._last_fetch.get(product_id, 0)
        return (time.time() - last) > self._ttl

    def mark_fresh(self, product_id: str) -> None:
        self._last_fetch[product_id] = time.time()

    def get_stale_products(self, product_ids: list[str]) -> list[str]:
        return [pid for pid in product_ids if self.is_stale(pid)]


# Singletons
_rotation = None
_rotation_lock = _threading.Lock()
_time = None
_time_lock = _threading.Lock()
_explore = None
_explore_lock = _threading.Lock()
_comp_cache = None
_comp_cache_lock = _threading.Lock()

def get_product_rotation():
    global _rotation
    if _rotation is None:
        with _rotation_lock:
            if _rotation is None:
                _rotation = ProductRotation()
    return _rotation

def get_time_awareness():
    global _time
    if _time is None:
        with _time_lock:
            if _time is None:
                _time = TimeAwareness()
    return _time

def get_exploration_boost():
    global _explore
    if _explore is None:
        with _explore_lock:
            if _explore is None:
                _explore = ExplorationBoost()
    return _explore

def get_competitor_cache():
    global _comp_cache
    if _comp_cache is None:
        with _comp_cache_lock:
            if _comp_cache is None:
                _comp_cache = CompetitorCacheManager()
    return _comp_cache
