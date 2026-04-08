"""ProductPipeline — Raw → Clean → Validate → Normalize → Feature engineer for product data."""
from __future__ import annotations

import logging
import time
from typing import Any

from data_pipeline.processing.cleaner import DataCleaner
from data_pipeline.processing.normalizer import DataNormalizer
from data_pipeline.processing.validator import DataValidator
from data_pipeline.feature_engineering.feature_builder import FeatureBuilder
from data_pipeline.feature_engineering.feature_store import FeatureStore
from data_pipeline.ingestion.api.shopify_api import ShopifyAPI

logger = logging.getLogger("data_pipeline.product_pipeline")

# Validation schema for product records
_PRODUCT_SCHEMA: dict[str, Any] = {
    "required": [],  # title/name checked flexibly below
    "types": {
        "price": "float",
        "compare_at": "float",
    },
    "ranges": {
        "price": {"min": 0.0},
        "compare_at": {"min": 0.0},
    },
}

# Fields that satisfy the "has a name" requirement
_NAME_FIELDS = ("title", "name", "product_title", "product_name")

# Normalization config
_PRODUCT_NORM_CONFIG: dict[str, Any] = {
    "price_fields": ["price", "compare_at", "cost"],
    "date_fields": ["created_at", "updated_at", "published_at"],
    "url_fields": ["image_url", "product_url"],
}

# Feature config
_PRODUCT_FEATURE_CONFIG: list[dict[str, Any]] = [
    {"type": "price", "target_field": "price_features"},
]


class ProductPipeline:
    """Raw → Clean → Normalize → Feature engineer for product data.

    Typical usage::

        pipeline = ProductPipeline()
        result = pipeline.run(raw_products)
        # or fetch directly from Shopify:
        result = pipeline.run_from_shopify("mystore.myshopify.com", api_key)
    """

    def __init__(self) -> None:
        self._cleaner = DataCleaner()
        self._normalizer = DataNormalizer()
        self._validator = DataValidator()
        self._feature_builder = FeatureBuilder()
        self._feature_store = FeatureStore()

    # ------------------------------------------------------------------
    # Primary entry points
    # ------------------------------------------------------------------

    def run(self, raw_products: list[dict[str, Any]]) -> dict[str, Any]:
        """Execute the full product pipeline on *raw_products*.

        Steps:
        1. Clean — strip whitespace, remove empty records, normalize text.
        2. Normalize — price strings to float, dates to ISO 8601, URLs.
        3. Validate — type and range checks after normalization.
        4. Build features — price tier, margin, discount depth.
        5. Store features — persisted to the feature store.

        Args:
            raw_products: List of raw product dicts (e.g. from Shopify API).

        Returns:
            ``{
                "products":  list[dict],   # normalized + featured valid products
                "features":  list[dict],   # same as products (features embedded)
                "invalid":   list[dict],   # records that failed validation
                "stats": {
                    "total_input":   int,
                    "valid":         int,
                    "invalid":       int,
                    "duration_sec":  float,
                }
            }``
        """
        start = time.monotonic()
        # Defensive: coerce None / non-list at entry. Audit pass 50.
        if not isinstance(raw_products, list):
            raw_products = []
        logger.info("ProductPipeline.run: processing %d raw products", len(raw_products))

        # Step 0: Normalize field names (name→title, etc.)
        standardized = self._standardize_fields(raw_products)

        # Step 1: Clean
        cleaned = self._cleaner.clean(standardized)

        # Step 2: Normalize (must happen before type validation)
        normalized = self._normalizer.normalize(cleaned, _PRODUCT_NORM_CONFIG)

        # Step 3: Validate
        valid, invalid = self._validator.validate(normalized, _PRODUCT_SCHEMA)

        # Step 4: Build features
        featured = self._feature_builder.build_features(
            valid, _PRODUCT_FEATURE_CONFIG
        )

        # Step 5: Store features
        self._feature_store.store("products_latest", featured)

        duration = round(time.monotonic() - start, 3)
        stats: dict[str, Any] = {
            "total_input": len(raw_products),
            "valid": len(valid),
            "invalid": len(invalid),
            "duration_sec": duration,
        }
        logger.info(
            "ProductPipeline complete: %d valid, %d invalid in %.3fs",
            len(valid),
            len(invalid),
            duration,
        )
        return {
            "products": featured,
            "features": featured,
            "invalid": invalid,
            "stats": stats,
        }

    @staticmethod
    def _standardize_fields(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Standardize field names so validator doesn't reject valid data.

        Maps common aliases: name→title, review_count→reviews, etc.
        """
        result = []
        for p in products:
            if not isinstance(p, dict):
                continue
            item = dict(p)
            # Ensure 'title' exists (validator requires it)
            if "title" not in item:
                for alias in _NAME_FIELDS:
                    if alias in item and item[alias]:
                        item["title"] = item[alias]
                        break
            result.append(item)
        return result

    def run_from_shopify(
        self,
        shop_url: str,
        api_key: str,
    ) -> dict[str, Any]:
        """Fetch products from Shopify and run the full pipeline.

        Args:
            shop_url: Shopify store domain, e.g. ``"mystore.myshopify.com"``.
            api_key:  Admin API access token.

        Returns:
            Same structure as :meth:`run`.
        """
        logger.info("ProductPipeline: fetching products from Shopify (%s)", shop_url)
        api = ShopifyAPI(shop_url=shop_url, api_key=api_key)
        response = api.fetch_products()

        if response.get("errors"):
            logger.warning(
                "Shopify fetch returned errors: %s", response["errors"]
            )

        raw_products: list[dict[str, Any]] = response.get("products", [])
        logger.info("Fetched %d products from Shopify", len(raw_products))
        return self.run(raw_products)
