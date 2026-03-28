"""Feature Selector — selects most relevant features."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("data.feature_selector")


class FeatureSelector:
    """Selects relevant features for model input."""

    def select(self, data: list[dict[str, Any]], keep_fields: list[str]) -> list[dict[str, Any]]:
        logger.info("Selecting %d features from %d records", len(keep_fields), len(data))
        return [{k: r.get(k) for k in keep_fields} for r in data]
