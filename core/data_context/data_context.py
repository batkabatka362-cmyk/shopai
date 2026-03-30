"""DataContext — prepares the right data for each engine step.

Rule: Raw → Clean → Normalize → Feature → Model
Every engine step gets exactly the data it needs — no more, no less.
Never mutates source data.
"""
from __future__ import annotations

import copy
from typing import Any

from utils.logger import get_logger

logger = get_logger("data_context")


class DataContext:
    """Manages data flow through engine steps.

    Responsibilities:
      - Clean raw input before engine processes it
      - Enrich data with computed fields
      - Route the right subset to each step
      - Track data lineage (where each field came from)
    """

    def __init__(self, raw_data: dict[str, Any]) -> None:
        self._raw = copy.deepcopy(raw_data)
        self._cleaned: dict[str, Any] = {}
        self._normalized: dict[str, Any] = {}
        self._features: dict[str, Any] = {}
        self._enriched: dict[str, Any] = {}
        self._lineage: list[dict[str, str]] = []

    @property
    def raw(self) -> dict[str, Any]:
        return copy.deepcopy(self._raw)

    @property
    def cleaned(self) -> dict[str, Any]:
        return copy.deepcopy(self._cleaned)

    @property
    def features(self) -> dict[str, Any]:
        return copy.deepcopy(self._features)

    def prepare(self) -> "DataContext":
        """Run full data preparation pipeline: clean → normalize → feature extract."""
        self._clean()
        self._normalize()
        self._extract_features()
        return self

    def for_step(self, step_name: str) -> dict[str, Any]:
        """Get the right data for a specific engine step."""
        if step_name == "analyze":
            # Analyzer gets cleaned data + features for scoring
            return {**self._cleaned, **self._features, "_step": "analyze"}
        elif step_name == "execute":
            # Worker gets full context: cleaned + features + enriched
            return {**self._cleaned, **self._features, **self._enriched, "_step": "execute"}
        elif step_name == "enhance":
            # Creative gets minimal data — focused on content
            return {**self._enriched, "_step": "enhance"}
        elif step_name == "validate":
            # Validator gets everything for verification
            return {**self._cleaned, **self._features, **self._enriched, "_step": "validate"}
        else:
            return copy.deepcopy(self._cleaned)

    def enrich(self, key: str, value: Any, source: str = "computed") -> None:
        """Add enriched data field."""
        self._enriched[key] = value
        self._lineage.append({"field": key, "source": source, "stage": "enrich"})

    def add_feature(self, key: str, value: Any, source: str = "computed") -> None:
        """Add a computed feature."""
        self._features[key] = value
        self._lineage.append({"field": key, "source": source, "stage": "feature"})

    def get_lineage(self) -> list[dict[str, str]]:
        """Get data lineage — where each field came from."""
        return list(self._lineage)

    def _clean(self) -> None:
        """Clean raw data: strip whitespace, remove nulls, normalize types."""
        cleaned = {}
        for key, value in self._raw.items():
            if value is None:
                continue
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    continue
            if isinstance(value, dict):
                value = {k: v for k, v in value.items() if v is not None}
            if isinstance(value, list):
                value = [v for v in value if v is not None]
            cleaned[key] = value
            self._lineage.append({"field": key, "source": "raw", "stage": "clean"})
        self._cleaned = cleaned

    def _normalize(self) -> None:
        """Normalize data types and formats."""
        for key, value in list(self._cleaned.items()):
            if isinstance(value, dict):
                self._cleaned[key] = self._normalize_dict(value)
            elif isinstance(value, list) and value and isinstance(value[0], dict):
                self._cleaned[key] = [self._normalize_dict(item) for item in value]
        self._normalized = copy.deepcopy(self._cleaned)

    def _normalize_dict(self, d: dict[str, Any]) -> dict[str, Any]:
        """Normalize a dict: convert price strings, standardize keys."""
        result = {}
        for k, v in d.items():
            # Normalize key: lowercase, strip
            norm_key = k.strip().lower().replace(" ", "_")
            # Normalize price strings
            if isinstance(v, str) and norm_key in ("price", "cost", "msrp", "compare_at_price"):
                v = self._parse_price(v)
            result[norm_key] = v
        return result

    @staticmethod
    def _parse_price(price_str: str) -> float:
        """Parse price string to float: '$1,234.56' → 1234.56"""
        try:
            cleaned = price_str.replace("$", "").replace(",", "").replace(" ", "").strip()
            return float(cleaned)
        except (ValueError, AttributeError):
            return 0.0

    def _extract_features(self) -> None:
        """Extract computed features from cleaned data."""
        # Product features
        products = self._cleaned.get("products", self._cleaned.get("product_data", []))
        if isinstance(products, list):
            for i, product in enumerate(products):
                if isinstance(product, dict):
                    features = self._product_features(product)
                    for fk, fv in features.items():
                        self._features[f"product_{i}_{fk}"] = fv
            self._features["product_count"] = len(products)
        elif isinstance(products, dict):
            features = self._product_features(products)
            self._features.update(features)

        # General features
        for key, value in self._cleaned.items():
            if isinstance(value, list):
                self._features[f"{key}_count"] = len(value)
            elif isinstance(value, dict):
                self._features[f"{key}_field_count"] = len(value)

    @staticmethod
    def _product_features(product: dict[str, Any]) -> dict[str, float]:
        """Compute features from a product dict."""
        features = {}
        price = float(product.get("price", 0))
        cost = float(product.get("cost", 0))

        if price > 0:
            features["margin_pct"] = round((price - cost) / price * 100, 2) if cost > 0 else 100.0
            features["price_tier"] = (
                "budget" if price < 20
                else "mid" if price < 50
                else "premium" if price < 150
                else "luxury"
            )
        if cost > 0 and price > 0:
            features["markup_ratio"] = round(price / cost, 2)

        compare = float(product.get("compare_at_price", 0))
        if compare > 0 and price > 0:
            features["discount_depth"] = round((compare - price) / compare * 100, 2)

        weight = float(product.get("weight", 0))
        if weight > 0:
            features["shipping_class"] = (
                "light" if weight < 0.5
                else "standard" if weight < 5
                else "heavy" if weight < 30
                else "freight"
            )

        return features
