"""Analytics Pipeline — Raw -> Clean -> Normalize -> Feature for analytics data."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger
from data_pipeline.processing.cleaner import DataCleaner
from data_pipeline.processing.normalizer import DataNormalizer
from data_pipeline.processing.validator import DataValidator
from data_pipeline.feature_engineering.feature_builder import FeatureBuilder

logger = get_logger("pipeline.analytics")


class AnalyticsPipeline:
    """End-to-end data pipeline for analytics data."""

    def __init__(self) -> None:
        self._cleaner = DataCleaner()
        self._normalizer = DataNormalizer()
        self._validator = DataValidator(required_fields=["metric_name", "value"])
        self._feature_builder = FeatureBuilder()

    def run(self, raw_data: list[dict[str, Any]]) -> dict[str, Any]:
        logger.info("Running analytics pipeline (%d records)", len(raw_data))
        cleaned = self._cleaner.clean(raw_data)
        normalized = self._normalizer.normalize(cleaned)
        valid, invalid = self._validator.validate(normalized)
        features = self._feature_builder.build(valid)
        return {"features": features, "valid_count": len(valid), "invalid_count": len(invalid)}
