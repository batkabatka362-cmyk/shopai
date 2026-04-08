"""Forecasting — real time series forecasting algorithms.

  - Simple moving average
  - Weighted moving average
  - Exponential smoothing
  - Seasonal decomposition
  - Trend extrapolation
  - Confidence intervals
"""
from __future__ import annotations

import math
from typing import Any

from utils.helpers import safe_float


_UNPARSEABLE = float("nan")


def _coerce_values(values: Any) -> list[float]:
    """Coerce an arbitrary input to a list of floats.

    Pre-audit the forecasting algorithms assumed ``values``
    was a clean list of numbers. Callers from the autonomous
    loop sometimes pass a list with None, strings, or dicts
    in it (e.g. raw order.total_price fields from a JSON
    webhook that occasionally comes back as a string). That
    crashed the arithmetic in ``_exponential_smoothing`` /
    ``_linear_trend`` / ``_seasonal_forecast``. Audit pass 40.
    """
    if values is None:
        return []
    if not isinstance(values, (list, tuple)):
        return []
    cleaned: list[float] = []
    for v in values:
        if isinstance(v, bool):
            # ``bool`` is a subclass of ``int`` in Python; reject
            # explicitly so a list of bools doesn't silently
            # become a list of 0s and 1s.
            continue
        if isinstance(v, (int, float)):
            if math.isnan(v) or math.isinf(v):
                continue
            cleaned.append(float(v))
            continue
        if isinstance(v, str):
            # ``safe_float`` strips $/commas and returns 0 on
            # parse failure. Use a NaN sentinel so we can tell
            # a successful "0" apart from a failed parse.
            parsed = safe_float(v, default=_UNPARSEABLE)
            if not math.isnan(parsed) and not math.isinf(parsed):
                cleaned.append(parsed)
        # All other types (dict, None, object) are dropped.
    return cleaned


class Forecasting:
    """Real forecasting algorithms for e-commerce data."""

    def forecast(self, values: list[float], periods: int = 7, method: str = "auto") -> dict[str, Any]:
        """Forecast future values from historical data.

        Args:
            values: historical data points (daily/weekly/monthly)
            periods: how many periods to forecast
            method: auto, sma, ema, linear, seasonal
        """
        # Defensive coercion. Audit pass 40.
        values = _coerce_values(values)
        if not isinstance(periods, int) or periods <= 0:
            periods = 7
        if not isinstance(method, str):
            method = "auto"

        if len(values) < 3:
            return {"error": "Need at least 3 data points", "values_provided": len(values)}

        if method == "auto":
            method = self._select_method(values)

        methods = {
            "sma": self._simple_moving_average,
            "ema": self._exponential_smoothing,
            "linear": self._linear_trend,
            "seasonal": self._seasonal_forecast,
            "wma": self._weighted_moving_average,
        }

        forecaster = methods.get(method, self._exponential_smoothing)
        forecast_values = forecaster(values, periods)

        # Confidence intervals (±2 standard deviations of residuals)
        residuals = self._calculate_residuals(values, method)
        std_residual = self._std(residuals) if residuals else self._std(values) * 0.1

        upper = [round(f + 2 * std_residual, 2) for f in forecast_values]
        lower = [round(max(0, f - 2 * std_residual), 2) for f in forecast_values]

        # Trend analysis
        trend = self._detect_trend(values)
        seasonality = self._detect_seasonality(values)

        return {
            "method": method,
            "forecast": [round(f, 2) for f in forecast_values],
            "upper_bound": upper,
            "lower_bound": lower,
            "confidence_level": "95%",
            "historical_points": len(values),
            "forecast_periods": periods,
            "trend": trend,
            "seasonality": seasonality,
            "summary": {
                "last_value": round(values[-1], 2),
                "forecast_avg": round(sum(forecast_values) / len(forecast_values), 2),
                "forecast_min": round(min(forecast_values), 2),
                "forecast_max": round(max(forecast_values), 2),
                "growth_pct": round((forecast_values[-1] - values[-1]) / max(abs(values[-1]), 1) * 100, 1),
            },
        }

    def revenue_forecast(self, daily_revenue: list[float], days_ahead: int = 30) -> dict[str, Any]:
        """Revenue-specific forecast with business context."""
        # Coerce once so the sum() below can't crash on a
        # non-numeric webhook payload. Audit pass 40.
        daily_revenue = _coerce_values(daily_revenue)
        result = self.forecast(daily_revenue, days_ahead, method="auto")
        if "error" in result:
            return result

        forecast = result["forecast"]
        total_forecast = sum(forecast)
        historical_total = (
            sum(daily_revenue[-days_ahead:])
            if len(daily_revenue) >= days_ahead
            else sum(daily_revenue)
        )

        result["revenue_summary"] = {
            "forecast_total": round(total_forecast, 2),
            "historical_total": round(historical_total, 2),
            "growth_pct": round((total_forecast - historical_total) / max(historical_total, 1) * 100, 1),
            "daily_avg_forecast": round(total_forecast / max(len(forecast), 1), 2),
            "best_day_forecast": round(max(forecast), 2),
            "worst_day_forecast": round(min(forecast), 2),
        }
        return result

    def demand_forecast(self, daily_units: list[float], days_ahead: int = 14) -> dict[str, Any]:
        """Demand-specific forecast with inventory context."""
        daily_units = _coerce_values(daily_units)
        result = self.forecast(daily_units, days_ahead, method="auto")
        if "error" in result:
            return result

        forecast = result["forecast"]
        total_demand = sum(forecast)
        avg_daily = total_demand / max(len(forecast), 1)

        result["demand_summary"] = {
            "total_units_forecast": round(total_demand),
            "avg_daily_demand": round(avg_daily, 1),
            "peak_day_demand": round(max(forecast)),
            "safety_stock_recommendation": round(avg_daily * 3),
            "reorder_point": round(avg_daily * 7),
        }
        return result

    # --- Algorithms ---

    @staticmethod
    def _simple_moving_average(values: list[float], periods: int, window: int = 0) -> list[float]:
        if not window:
            window = min(7, len(values) // 2)
            window = max(2, window)
        avg = sum(values[-window:]) / window
        return [avg] * periods

    @staticmethod
    def _weighted_moving_average(values: list[float], periods: int) -> list[float]:
        window = min(7, len(values) // 2)
        window = max(2, window)
        recent = values[-window:]
        weights = list(range(1, window + 1))
        total_weight = sum(weights)
        wma = sum(v * w for v, w in zip(recent, weights)) / total_weight
        return [round(wma, 2)] * periods

    @staticmethod
    def _exponential_smoothing(values: list[float], periods: int, alpha: float = 0) -> list[float]:
        if not alpha:
            alpha = 2 / (min(len(values), 10) + 1)

        smoothed = values[0]
        for v in values[1:]:
            smoothed = alpha * v + (1 - alpha) * smoothed

        # Forecast: use last smoothed value + trend
        if len(values) >= 2:
            trend = (values[-1] - values[-max(1, len(values)//2)]) / max(len(values)//2, 1)
        else:
            trend = 0

        return [round(smoothed + trend * i, 2) for i in range(1, periods + 1)]

    @staticmethod
    def _linear_trend(values: list[float], periods: int) -> list[float]:
        n = len(values)
        x = list(range(n))
        x_mean = sum(x) / n
        y_mean = sum(values) / n

        numerator = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, values))
        denominator = sum((xi - x_mean) ** 2 for xi in x)

        if abs(denominator) < 1e-10:
            return [y_mean] * periods

        slope = numerator / denominator
        intercept = y_mean - slope * x_mean

        return [round(slope * (n + i) + intercept, 2) for i in range(periods)]

    def _seasonal_forecast(self, values: list[float], periods: int) -> list[float]:
        """Simple seasonal forecast — detects repeating pattern."""
        # Try common season lengths
        best_season = 7  # Default weekly
        best_score = float("inf")

        for season_len in [7, 14, 30, 12, 4]:
            if len(values) < season_len * 2:
                continue
            score = self._seasonal_error(values, season_len)
            if score < best_score:
                best_score = score
                best_season = season_len

        # Extract seasonal pattern
        pattern = [0.0] * best_season
        counts = [0] * best_season
        for i, v in enumerate(values):
            idx = i % best_season
            pattern[idx] += v
            counts[idx] += 1
        pattern = [p / max(c, 1) for p, c in zip(pattern, counts)]

        # Trend adjustment
        trend = self._linear_trend(values, 1)[0] - values[-1]

        forecast = []
        for i in range(periods):
            seasonal_val = pattern[(len(values) + i) % best_season]
            forecast.append(round(seasonal_val + trend * (i + 1) / periods, 2))

        return forecast

    # --- Analysis ---

    def _detect_trend(self, values: list[float]) -> dict[str, Any]:
        if len(values) < 5:
            return {"direction": "unknown", "strength": 0}

        mid = len(values) // 2
        first_half = sum(values[:mid]) / mid
        second_half = sum(values[mid:]) / (len(values) - mid)

        change_pct = (second_half - first_half) / max(abs(first_half), 1) * 100
        direction = "up" if change_pct > 5 else "down" if change_pct < -5 else "flat"

        return {
            "direction": direction,
            "change_pct": round(change_pct, 1),
            "strength": "strong" if abs(change_pct) > 20 else "moderate" if abs(change_pct) > 10 else "weak",
        }

    def _detect_seasonality(self, values: list[float]) -> dict[str, Any]:
        if len(values) < 14:
            return {"detected": False, "reason": "insufficient_data"}

        for period in [7, 30, 12]:
            if len(values) >= period * 2:
                error = self._seasonal_error(values, period)
                avg_val = sum(abs(v) for v in values) / len(values)
                if avg_val > 0 and error / avg_val < 0.3:
                    return {"detected": True, "period": period, "pattern": "weekly" if period == 7 else "monthly" if period == 30 else "quarterly"}

        return {"detected": False, "reason": "no_pattern_found"}

    @staticmethod
    def _seasonal_error(values: list[float], period: int) -> float:
        errors = []
        for i in range(period, len(values)):
            predicted = values[i - period]
            actual = values[i]
            errors.append(abs(actual - predicted))
        return sum(errors) / max(len(errors), 1)

    def _calculate_residuals(self, values: list[float], method: str) -> list[float]:
        if len(values) < 5:
            return []
        mid = len(values) // 2
        train = values[:mid]
        test = values[mid:]

        methods = {"sma": self._simple_moving_average, "ema": self._exponential_smoothing, "linear": self._linear_trend}
        forecaster = methods.get(method, self._exponential_smoothing)
        predicted = forecaster(train, len(test))

        return [actual - pred for actual, pred in zip(test, predicted)]

    def _select_method(self, values: list[float]) -> str:
        if len(values) >= 14 and self._detect_seasonality(values).get("detected"):
            return "seasonal"
        trend = self._detect_trend(values)
        if trend["direction"] != "flat" and abs(trend.get("change_pct", 0)) > 15:
            return "linear"
        return "ema"

    @staticmethod
    def _std(values: list[float]) -> float:
        if len(values) < 2:
            return 0
        mean = sum(values) / len(values)
        return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
