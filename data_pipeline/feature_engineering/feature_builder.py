"""FeatureBuilder — constructs engineered features from clean, normalized data."""
from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger("data_pipeline.feature_builder")

# Price tier thresholds (in currency units)
_PRICE_TIERS = [
    (0, 10, "budget"),
    (10, 50, "economy"),
    (50, 150, "mid"),
    (150, 500, "premium"),
    (500, float("inf"), "luxury"),
]


class FeatureBuilder:
    """Builds domain-specific features for products, users, and time-series."""

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    def build_features(
        self,
        data: list[dict[str, Any]],
        feature_config: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Apply feature-building operations defined in *feature_config* to *data*.

        Config entry format::

            {
                "type": "price" | "engagement" | "trend",
                "target_field": "features",   # output sub-dict key (optional)
                "source": "product" | "user" | "timeseries",
            }

        When *feature_config* is ``None`` each record is returned as-is.

        Args:
            data:           Input records.
            feature_config: List of feature-build descriptors.

        Returns:
            Records enriched with new feature fields.
        """
        if not feature_config:
            logger.debug("build_features: no config; returning data unchanged")
            return [dict(r) for r in data]

        logger.info("Building features for %d records", len(data))
        results: list[dict[str, Any]] = []

        for record in data:
            new_rec = dict(record)
            for cfg in feature_config:
                ftype = cfg.get("type", "")
                target = cfg.get("target_field", ftype + "_features")
                if ftype == "price":
                    new_rec[target] = self.build_price_features(new_rec)
                elif ftype == "engagement":
                    new_rec[target] = self.build_engagement_features(new_rec)
                elif ftype == "trend":
                    # For trend features the record should contain a
                    # "time_series" key with a list of dicts
                    ts = new_rec.get("time_series", [])
                    new_rec[target] = self.build_trend_features(ts)
                else:
                    logger.warning("Unknown feature type: '%s'", ftype)
            results.append(new_rec)

        return results

    # ------------------------------------------------------------------
    # Domain-specific feature builders
    # ------------------------------------------------------------------

    def build_price_features(self, product: dict[str, Any]) -> dict[str, Any]:
        """Compute price-related features for a product record.

        Input fields used (all optional, default to 0):
        * ``price``       — selling price.
        * ``cost``        — cost / COGS.
        * ``compare_at``  — original / compare-at price (for discount depth).

        Returns:
            Dict with:
            * ``margin``        — gross margin as a fraction (0–1).
            * ``margin_pct``    — gross margin as a percentage.
            * ``price_tier``    — categorical tier label.
            * ``discount_depth``— fractional discount vs ``compare_at`` (0–1).
            * ``is_on_sale``    — bool: True if price < compare_at.
        """
        price = float(product.get("price") or 0.0)
        cost = float(product.get("cost") or 0.0)
        compare_at = float(product.get("compare_at") or 0.0)

        from utils.finance import margin as _margin
        # require_cost=False so zero-cost items get a full 100% margin
        # (matches the original semantics of this feature)
        margin = _margin(price, cost, require_cost=False)
        margin_pct = round(margin * 100, 2)
        price_tier = self._price_tier(price)

        discount_depth = 0.0
        is_on_sale = False
        if compare_at > 0 and price < compare_at:
            discount_depth = round((compare_at - price) / compare_at, 4)
            is_on_sale = True

        return {
            "margin": round(margin, 4),
            "margin_pct": margin_pct,
            "price_tier": price_tier,
            "discount_depth": discount_depth,
            "is_on_sale": is_on_sale,
        }

    def build_engagement_features(self, user_data: dict[str, Any]) -> dict[str, Any]:
        """Compute RFM (Recency, Frequency, Monetary) engagement features.

        Input fields used:
        * ``days_since_last_order``  — int/float, recency in days.
        * ``order_count``            — total number of orders.
        * ``total_spent``            — lifetime monetary value.
        * ``avg_order_value``        — average order value (computed if absent).

        Returns:
            Dict with:
            * ``recency``        — days since last order (lower = more recent).
            * ``frequency``      — total order count.
            * ``monetary``       — total spend.
            * ``avg_order_value``— average order value.
            * ``rfm_score``      — composite score: 1/recency + frequency + monetary/100.
            * ``segment``        — "champion" | "loyal" | "at_risk" | "inactive".
        """
        recency = float(user_data.get("days_since_last_order") or 0.0)
        frequency = float(user_data.get("order_count") or 0.0)
        monetary = float(user_data.get("total_spent") or 0.0)

        aov = float(user_data.get("avg_order_value") or (
            monetary / frequency if frequency > 0 else 0.0
        ))

        recency_score = 1.0 / (recency + 1)  # +1 to avoid div/0; higher = more recent
        rfm_score = round(recency_score * 0.4 + (frequency / 10) * 0.3 + (monetary / 1000) * 0.3, 4)

        segment = self._rfm_segment(recency, frequency, monetary)

        return {
            "recency": recency,
            "frequency": frequency,
            "monetary": monetary,
            "avg_order_value": round(aov, 2),
            "rfm_score": rfm_score,
            "segment": segment,
        }

    def build_trend_features(self, time_series: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute trend metrics for a time-ordered list of ``{date, value}`` dicts.

        Args:
            time_series: List of dicts each with at least a numeric ``"value"`` key.
                         Must be ordered chronologically (oldest first).

        Returns:
            Dict with:
            * ``growth_rate``  — percentage change from first to last value.
            * ``volatility``   — coefficient of variation (std / mean).
            * ``momentum``     — mean of the last 3 deltas (average recent change).
            * ``trend``        — "up" | "down" | "flat" based on growth_rate.
            * ``mean``         — mean of the series.
            * ``n``            — number of data points.
        """
        if not time_series:
            return {
                "growth_rate": 0.0,
                "volatility": 0.0,
                "momentum": 0.0,
                "trend": "flat",
                "mean": 0.0,
                "n": 0,
            }

        values = [float(item.get("value", 0) or 0) for item in time_series]
        n = len(values)
        mean_val = sum(values) / n

        first, last = values[0], values[-1]
        growth_rate = round(((last - first) / first * 100) if first != 0 else 0.0, 4)

        # Volatility: coefficient of variation
        if n > 1:
            variance = sum((v - mean_val) ** 2 for v in values) / (n - 1)
            std = math.sqrt(variance)
            volatility = round(std / mean_val if mean_val != 0 else 0.0, 4)
        else:
            volatility = 0.0

        # Momentum: mean of last 3 period-over-period changes
        deltas = [values[i] - values[i - 1] for i in range(1, n)]
        recent_deltas = deltas[-3:] if deltas else []
        momentum = round(sum(recent_deltas) / len(recent_deltas) if recent_deltas else 0.0, 4)

        trend = "flat"
        if growth_rate > 5:
            trend = "up"
        elif growth_rate < -5:
            trend = "down"

        return {
            "growth_rate": growth_rate,
            "volatility": volatility,
            "momentum": momentum,
            "trend": trend,
            "mean": round(mean_val, 4),
            "n": n,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _price_tier(price: float) -> str:
        for lo, hi, label in _PRICE_TIERS:
            if lo <= price < hi:
                return label
        return "luxury"

    @staticmethod
    def _rfm_segment(recency: float, frequency: float, monetary: float) -> str:
        """Classify a customer into an RFM segment using simple thresholds."""
        if recency <= 30 and frequency >= 5 and monetary >= 500:
            return "champion"
        if recency <= 60 and frequency >= 3:
            return "loyal"
        if recency > 90:
            return "inactive"
        return "at_risk"
