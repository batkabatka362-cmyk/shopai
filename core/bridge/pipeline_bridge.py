"""PipelineBridge — auto-runs data pipeline before/after engine execution.

Before engine: Raw data → Clean → Validate → Enrich → Feature extract
After engine: Result → Store → Cache → Cross-engine share
"""
from __future__ import annotations

import copy
from typing import Any

from utils.logger import get_logger
from data_pipeline.processing.cleaner import DataCleaner
from data_pipeline.processing.normalizer import DataNormalizer
from data_pipeline.processing.validator import DataValidator
from core.data_context import PipelineValidator

logger = get_logger("bridge.pipeline")

_cleaner = DataCleaner()
_normalizer = DataNormalizer()
_validator = DataValidator()
_pipeline_validator = PipelineValidator()


class PipelineBridge:
    """Bridges data_pipeline to engine execution."""

    def pre_process(self, data: dict[str, Any], engine_name: str) -> dict[str, Any]:
        """Run data pipeline BEFORE engine: clean, validate, normalize."""
        result = copy.deepcopy(data)

        # Clean list/dict data fields
        for key, value in list(result.items()):
            if key.startswith("_"):
                continue

            if isinstance(value, list) and value and isinstance(value[0], dict):
                # Clean: strip whitespace, remove nulls
                cleaned = _cleaner.clean(value)
                # Validate: check data quality
                valid, invalid = _validator.validate(cleaned, self._schema_for_field(key))
                if valid:
                    result[key] = valid
                    if invalid:
                        result[f"_{key}_invalid"] = invalid
                        result[f"_{key}_invalid_count"] = len(invalid)
                else:
                    result[key] = cleaned  # Keep cleaned if validation returns nothing

            elif isinstance(value, str) and key.lower() in ("price", "cost", "amount", "total"):
                # Auto-convert price strings
                result[key] = _normalizer.normalize_price(value)

        # Pipeline validation
        validation = _pipeline_validator.validate(result, stage="pre_engine")
        result["_pipeline_validation"] = {
            "quality_score": validation["quality_score"],
            "quality_tier": validation["quality_tier"],
            "issues": len(validation["issues"]),
            "repairs": len(validation["repairs_applied"]),
        }

        # Apply auto-repairs
        if validation.get("repaired_data"):
            repaired = validation["repaired_data"]
            for key, value in repaired.items():
                if not key.startswith("_") and key in data:
                    result[key] = value

        # Validate products specifically
        products = result.get("products", result.get("product_data", []))
        if isinstance(products, list) and products and isinstance(products[0], dict):
            product_validation = _pipeline_validator.validate_products(products)
            if product_validation["valid_products"]:
                key = "products" if "products" in result else "product_data"
                result[key] = product_validation["valid_products"]
            result["_product_validation"] = {
                "total": product_validation["total"],
                "valid": product_validation["valid"],
                "invalid": product_validation["invalid"],
            }

        return result

    def post_process(self, result: dict[str, Any], engine_name: str) -> dict[str, Any]:
        """Run data pipeline AFTER engine: normalize output, compute final metrics."""
        output = copy.deepcopy(result)

        # Compute output quality metrics
        real_fields = [k for k in output if not k.startswith("_")]
        actionable = [k for k in real_fields if isinstance(output[k], (list, dict)) and output[k]]
        numeric = [k for k in real_fields if isinstance(output[k], (int, float))]

        output["_output_quality"] = {
            "total_fields": len(real_fields),
            "actionable_fields": len(actionable),
            "numeric_fields": len(numeric),
            "completeness": round(len(actionable) / max(len(real_fields), 1), 2),
        }

        return output

    @staticmethod
    def _schema_for_field(field_name: str) -> dict[str, Any]:
        """Get validation schema for common field types."""
        schemas = {
            "products": {"required": ["name"], "types": {"price": "float", "cost": "float"}},
            "product_data": {"required": ["name"], "types": {"price": "float"}},
            "customers": {"required": [], "types": {"orders": "int"}},
            "customer_data": {"required": [], "types": {"orders": "int"}},
            "orders": {"required": [], "types": {"total": "float"}},
            "order_data": {"required": [], "types": {"total": "float"}},
        }
        return schemas.get(field_name, {})
