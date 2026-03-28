"""Feature Builder — constructs features from processed data."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("data.feature_builder")


class FeatureBuilder:
    """Builds features from clean, normalized data."""

    def build(self, data: list[dict[str, Any]], feature_defs: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        logger.info("Building features for %d records", len(data))
        featured = []
        for record in data:
            features = dict(record)
            if feature_defs:
                for fdef in feature_defs:
                    name = fdef.get("name", "")
                    source = fdef.get("source", "")
                    if source in features:
                        features[name] = features[source]
            featured.append(features)
        return featured
