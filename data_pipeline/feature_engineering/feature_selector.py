"""FeatureSelector — selects the most relevant features from a feature set."""
from __future__ import annotations

import logging
import math
from typing import Any

from utils.helpers import safe_float, safe_int

logger = logging.getLogger("data_pipeline.feature_selector")


class FeatureSelector:
    """Selects features based on variance, top-k scoring, or custom config.

    All methods receive and return ``list[dict]``, where each dict represents
    one record (sample) with feature key-value pairs.
    """

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    def select(
        self,
        features: list[dict[str, Any]],
        selection_config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Apply a selection strategy defined in *selection_config*.

        Config keys:
        * ``"strategy"``    — ``"variance"`` | ``"top_k"`` | ``"manual"``.
        * ``"threshold"``   — (variance) minimum variance to keep a feature.
        * ``"k"``           — (top_k) number of features to keep.
        * ``"score_field"`` — (top_k) field used to rank features.
        * ``"keep_fields"`` — (manual) explicit list of field names to retain.
        * ``"target_field"``— (top_k importance) target field for correlation.

        Args:
            features:         Feature records.
            selection_config: Selection strategy config.

        Returns:
            Filtered feature records.
        """
        # Defensive coercion of public entry point. Audit pass 50.
        if not isinstance(features, list):
            return []
        features = [r for r in features if isinstance(r, dict)]
        if not isinstance(selection_config, dict):
            return [dict(r) for r in features]

        strategy = selection_config.get("strategy") or "manual"
        if not isinstance(strategy, str):
            strategy = "manual"

        if strategy == "variance":
            threshold = safe_float(selection_config.get("threshold"))
            return self.filter_by_variance(features, threshold)

        if strategy == "top_k":
            k = safe_int(selection_config.get("k"), default=10)
            if k <= 0:
                k = 10
            score_field = selection_config.get("score_field") or ""
            if not isinstance(score_field, str):
                score_field = ""
            return self.select_top_k(features, k, score_field)

        if strategy == "manual":
            keep_fields = selection_config.get("keep_fields") or []
            if not isinstance(keep_fields, list):
                return [dict(r) for r in features]
            if not keep_fields:
                return [dict(r) for r in features]
            keep_fields = [k for k in keep_fields if isinstance(k, str)]
            return [{k: r[k] for k in keep_fields if k in r} for r in features]

        logger.warning("Unknown selection strategy: '%s'; returning all features", strategy)
        return [dict(r) for r in features]

    # ------------------------------------------------------------------
    # Individual selection methods
    # ------------------------------------------------------------------

    def filter_by_variance(
        self,
        features: list[dict[str, Any]],
        threshold: float,
    ) -> list[dict[str, Any]]:
        """Remove feature columns whose variance falls below *threshold*.

        Non-numeric columns are always kept.

        Args:
            features:  Feature records.
            threshold: Minimum acceptable variance.

        Returns:
            Records with low-variance numeric columns removed.
        """
        if not isinstance(features, list) or not features:
            return []
        features = [r for r in features if isinstance(r, dict)]
        if not features:
            return []
        threshold = safe_float(threshold)

        numeric_cols = self._numeric_columns(features)
        variances = {col: self._variance(features, col) for col in numeric_cols}

        keep = {
            col for col, var in variances.items() if var >= threshold
        }
        non_numeric = set(features[0].keys()) - set(numeric_cols)
        all_keep = keep | non_numeric

        dropped = set(numeric_cols) - keep
        if dropped:
            logger.info(
                "filter_by_variance: dropped %d low-variance columns: %s",
                len(dropped),
                sorted(dropped),
            )

        return [{k: v for k, v in r.items() if k in all_keep} for r in features]

    def select_top_k(
        self,
        features: list[dict[str, Any]],
        k: int,
        score_field: str,
    ) -> list[dict[str, Any]]:
        """Return the top-*k* records sorted descending by *score_field*.

        Args:
            features:    Feature records.
            k:           Number of top records to return.
            score_field: The numeric field to rank by.

        Returns:
            Up to *k* records with the highest *score_field* values.
        """
        if not score_field:
            logger.warning("select_top_k: no score_field provided; returning first %d", k)
            return [dict(r) for r in features[:k]]

        def _key(r: dict[str, Any]) -> float:
            val = r.get(score_field, 0)
            try:
                return float(val)
            except (TypeError, ValueError):
                return 0.0

        sorted_records = sorted(features, key=_key, reverse=True)
        return [dict(r) for r in sorted_records[:k]]

    def calculate_feature_importance(
        self,
        features: list[dict[str, Any]],
        target_field: str,
    ) -> dict[str, float]:
        """Estimate feature importance using Pearson correlation with *target_field*.

        This is a lightweight proxy — not a full model-based importance, but
        sufficient for quick feature selection without third-party ML libraries.

        Args:
            features:     Feature records.
            target_field: The target variable field name.

        Returns:
            ``{feature_name: abs_correlation}`` sorted descending.
            Features for which correlation cannot be computed get ``0.0``.
        """
        if not isinstance(features, list) or not features:
            return {}
        features = [r for r in features if isinstance(r, dict)]
        if not features or not isinstance(target_field, str) or not target_field:
            return {}
        if target_field not in features[0]:
            return {}

        target_values = [safe_float(r.get(target_field)) for r in features]
        numeric_cols = [
            col for col in self._numeric_columns(features) if col != target_field
        ]

        importance: dict[str, float] = {}
        for col in numeric_cols:
            col_values = [safe_float(r.get(col)) for r in features]
            corr = self._pearson_correlation(col_values, target_values)
            importance[col] = round(abs(corr), 6)

        # Sort descending by absolute correlation
        return dict(sorted(importance.items(), key=lambda kv: kv[1], reverse=True))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _numeric_columns(records: list[dict[str, Any]]) -> list[str]:
        """Return column names whose values are numeric in the first record."""
        if not records or not isinstance(records[0], dict):
            return []
        return [
            k for k, v in records[0].items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        ]

    @staticmethod
    def _variance(records: list[dict[str, Any]], col: str) -> float:
        """Compute population variance of *col* across *records*."""
        vals = [safe_float(r.get(col)) for r in records if isinstance(r, dict)]
        n = len(vals)
        if n < 2:
            return 0.0
        mean = sum(vals) / n
        return sum((v - mean) ** 2 for v in vals) / n

    @staticmethod
    def _pearson_correlation(x: list[float], y: list[float]) -> float:
        """Compute the Pearson correlation coefficient between *x* and *y*."""
        n = len(x)
        if n != len(y) or n < 2:
            return 0.0
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        den_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
        den_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))
        if den_x == 0 or den_y == 0:
            return 0.0
        return num / (den_x * den_y)
