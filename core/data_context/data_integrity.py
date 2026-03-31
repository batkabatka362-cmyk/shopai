"""DataIntegrity — ensures data quality across the entire pipeline.

Validates: data flows correctly, no noise, no corruption, engines get clean input.
"""
from __future__ import annotations

import copy
import math
from typing import Any

from utils.logger import get_logger

logger = get_logger("data.integrity")


class DataIntegrity:
    """Validates and cleans data at every stage of the pipeline."""

    def clean_input(self, data: dict[str, Any]) -> dict[str, Any]:
        """Deep clean any input data — remove noise, fix types, normalize."""
        cleaned = copy.deepcopy(data)

        for key in list(cleaned.keys()):
            if key.startswith("_"):
                continue
            value = cleaned[key]
            cleaned[key] = self._clean_value(key, value)

        return cleaned

    def validate_products(self, products: list[dict]) -> dict[str, Any]:
        """Strict product validation — only clean data passes."""
        valid = []
        invalid = []
        fixed = []

        for i, p in enumerate(products):
            if not isinstance(p, dict):
                invalid.append({"index": i, "reason": "not_a_dict"})
                continue

            issues = []
            fixed_p = dict(p)

            # Name required
            name = fixed_p.get("name", fixed_p.get("title", ""))
            if not name or not isinstance(name, str) or len(name.strip()) < 2:
                issues.append("missing_name")

            # Price must be positive number
            price = self._to_float(fixed_p.get("price", 0))
            if price <= 0:
                issues.append("invalid_price")
            else:
                fixed_p["price"] = price

            # Cost must be non-negative
            cost = self._to_float(fixed_p.get("cost", 0))
            if cost < 0:
                issues.append("negative_cost")
                cost = 0
            fixed_p["cost"] = cost

            # Cost must be less than price
            if cost > 0 and price > 0 and cost >= price:
                issues.append("cost_exceeds_price")

            # Weight non-negative
            weight = self._to_float(fixed_p.get("weight", 0))
            if weight < 0:
                weight = 0
            fixed_p["weight"] = weight

            # Search volume non-negative
            sv = self._to_int(fixed_p.get("search_volume", 0))
            fixed_p["search_volume"] = max(sv, 0)

            # Competition non-negative
            comp = self._to_int(fixed_p.get("competition", 0))
            fixed_p["competition"] = max(comp, 0)

            # Rating 0-5
            rating = self._to_float(fixed_p.get("rating", 0))
            if rating < 0 or rating > 5:
                rating = max(0, min(5, rating))
            fixed_p["rating"] = rating

            if issues:
                invalid.append({"index": i, "name": name, "issues": issues})
            else:
                valid.append(fixed_p)
                if fixed_p != p:
                    fixed.append({"index": i, "name": name, "fixes": "type_normalization"})

        return {
            "valid": valid,
            "invalid": invalid,
            "fixed": fixed,
            "total": len(products),
            "valid_count": len(valid),
            "invalid_count": len(invalid),
            "clean_rate": round(len(valid) / max(len(products), 1), 2),
        }

    def validate_customers(self, customers: list[dict]) -> dict[str, Any]:
        """Strict customer data validation."""
        valid = []
        invalid = []

        for i, c in enumerate(customers):
            if not isinstance(c, dict):
                invalid.append({"index": i, "reason": "not_a_dict"})
                continue

            fixed = dict(c)
            issues = []

            # Orders non-negative int
            fixed["orders"] = max(0, self._to_int(fixed.get("orders", fixed.get("order_count", 0))))

            # Total spent non-negative
            fixed["total_spent"] = max(0, self._to_float(fixed.get("total_spent", fixed.get("ltv", 0))))

            # Days since last order non-negative
            days = self._to_int(fixed.get("days_since_last_order", fixed.get("recency", 0)))
            fixed["days_since_last_order"] = max(0, days)

            if issues:
                invalid.append({"index": i, "issues": issues})
            else:
                valid.append(fixed)

        return {"valid": valid, "invalid": invalid, "total": len(customers), "valid_count": len(valid)}

    def check_flow_integrity(self, step_outputs: list[dict]) -> dict[str, Any]:
        """Check that data flows correctly between engine steps."""
        issues = []

        for i, step in enumerate(step_outputs):
            if not isinstance(step, dict):
                issues.append({"step": i, "issue": "not_a_dict"})
                continue
            if not step:
                issues.append({"step": i, "issue": "empty_output"})

        # Check data accumulation — later steps should have more context
        if len(step_outputs) >= 2:
            first_keys = set(step_outputs[0].keys()) if isinstance(step_outputs[0], dict) else set()
            last_keys = set(step_outputs[-1].keys()) if isinstance(step_outputs[-1], dict) else set()
            if len(last_keys) < len(first_keys):
                issues.append({"issue": "data_loss", "detail": f"Last step has fewer keys ({len(last_keys)}) than first ({len(first_keys)})"})

        return {
            "integrity": "ok" if not issues else "degraded",
            "issues": issues,
            "steps_checked": len(step_outputs),
        }

    def _clean_value(self, key: str, value: Any) -> Any:
        """Clean a single value based on field name."""
        key_lower = key.lower()

        if value is None:
            return value

        # Numeric fields
        if any(w in key_lower for w in ("price", "cost", "amount", "total", "revenue", "spend", "weight")):
            return self._to_float(value)

        # Integer fields
        if any(w in key_lower for w in ("count", "quantity", "stock", "orders", "units")):
            return self._to_int(value)

        # String cleanup
        if isinstance(value, str):
            return value.strip()

        # List cleanup
        if isinstance(value, list):
            return [v for v in value if v is not None]

        return value

    @staticmethod
    def _to_float(value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.replace("$", "").replace(",", "").strip())
            except ValueError:
                return 0.0
        return 0.0

    @staticmethod
    def _to_int(value: Any) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(float(value.replace(",", "").strip()))
            except ValueError:
                return 0
        return 0
