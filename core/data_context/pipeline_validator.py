"""PipelineValidator — deep validation rules for data pipeline.

Validates data at every stage: ingestion → cleaning → normalization → feature.
Detects anomalies, auto-repairs common issues, scores quality.
"""
from __future__ import annotations

import copy
import re
import math
from typing import Any

from utils.logger import get_logger

logger = get_logger("data_context.validator")


class PipelineValidator:
    """Multi-stage data validation with anomaly detection and auto-repair."""

    def __init__(self) -> None:
        self._rules: list[dict[str, Any]] = self._default_rules()
        self._anomaly_history: dict[str, list[float]] = {}

    def validate(self, data: dict[str, Any], stage: str = "input") -> dict[str, Any]:
        """Validate data at a given pipeline stage. Returns validation report."""
        issues: list[dict[str, Any]] = []
        repairs: list[dict[str, Any]] = []
        repaired_data = copy.deepcopy(data)

        # Type validation
        for key, value in data.items():
            if key.startswith("_"):
                continue
            type_issues = self._validate_types(key, value)
            issues.extend(type_issues)

        # Rule-based validation
        for rule in self._rules:
            if rule.get("stage") and rule["stage"] != stage:
                continue
            result = self._apply_rule(rule, data)
            if result:
                issues.append(result)

        # Anomaly detection on numeric fields
        anomalies = self._detect_anomalies(data)
        issues.extend(anomalies)

        # Auto-repair
        repaired_data, done_repairs = self._auto_repair(repaired_data, issues)
        repairs.extend(done_repairs)

        # Quality score
        total_fields = sum(1 for k in data if not k.startswith("_"))
        issue_count = len([i for i in issues if i.get("severity") in ("high", "critical")])
        quality_score = max(0, round(10 - (issue_count / max(total_fields, 1)) * 10, 1))

        return {
            "valid": len(issues) == 0,
            "quality_score": quality_score,
            "quality_tier": "high" if quality_score >= 8 else "medium" if quality_score >= 5 else "low",
            "total_fields": total_fields,
            "issues": issues,
            "issue_count": len(issues),
            "critical_issues": sum(1 for i in issues if i.get("severity") == "critical"),
            "repairs_applied": repairs,
            "repair_count": len(repairs),
            "repaired_data": repaired_data,
            "stage": stage,
        }

    def validate_products(self, products: list[dict[str, Any]]) -> dict[str, Any]:
        """Validate a list of products with product-specific rules."""
        issues = []
        valid_products = []
        invalid_products = []

        for i, p in enumerate(products):
            if not isinstance(p, dict):
                issues.append({"field": f"products[{i}]", "issue": "not_a_dict", "severity": "critical"})
                invalid_products.append(p)
                continue

            product_issues = []

            # Required fields
            if not p.get("name") and not p.get("title"):
                product_issues.append({"field": "name", "issue": "missing", "severity": "high"})

            price = p.get("price", 0)
            if isinstance(price, str):
                try:
                    price = float(price.replace("$", "").replace(",", ""))
                except ValueError:
                    product_issues.append({"field": "price", "issue": "invalid_format", "severity": "high", "value": price})
                    price = 0

            if price < 0:
                product_issues.append({"field": "price", "issue": "negative", "severity": "critical", "value": price})
            elif price == 0:
                product_issues.append({"field": "price", "issue": "zero", "severity": "medium"})

            cost = p.get("cost", 0)
            if isinstance(cost, (int, float)) and isinstance(price, (int, float)):
                if cost > price and price > 0:
                    product_issues.append({"field": "cost", "issue": "exceeds_price", "severity": "high", "cost": cost, "price": price})
                if cost < 0:
                    product_issues.append({"field": "cost", "issue": "negative", "severity": "critical"})

            weight = p.get("weight", 0)
            if isinstance(weight, (int, float)) and weight < 0:
                product_issues.append({"field": "weight", "issue": "negative", "severity": "medium"})

            if product_issues:
                issues.extend([{**pi, "product_index": i, "product_name": p.get("name", f"product_{i}")} for pi in product_issues])
                invalid_products.append(p)
            else:
                valid_products.append(p)

        return {
            "total": len(products),
            "valid": len(valid_products),
            "invalid": len(invalid_products),
            "issues": issues,
            "valid_products": valid_products,
            "invalid_products": invalid_products,
        }

    def _validate_types(self, key: str, value: Any) -> list[dict]:
        issues = []
        key_lower = key.lower()

        # Price fields should be numeric
        if any(p in key_lower for p in ("price", "cost", "amount", "total", "revenue", "spend")):
            if isinstance(value, str):
                issues.append({"field": key, "issue": "string_instead_of_number", "severity": "medium", "auto_repair": True})
            elif value is not None and not isinstance(value, (int, float)):
                issues.append({"field": key, "issue": f"unexpected_type_{type(value).__name__}", "severity": "medium"})

        # Count fields should be int
        if any(p in key_lower for p in ("count", "quantity", "stock", "units")):
            if isinstance(value, float) and value == int(value):
                issues.append({"field": key, "issue": "float_should_be_int", "severity": "low", "auto_repair": True})

        # Email validation
        if "email" in key_lower and isinstance(value, str):
            if value and not re.match(r'^[^@]+@[^@]+\.[^@]+$', value):
                issues.append({"field": key, "issue": "invalid_email_format", "severity": "medium"})

        # URL validation
        if "url" in key_lower and isinstance(value, str):
            if value and not value.startswith(("http://", "https://", "/")):
                issues.append({"field": key, "issue": "invalid_url_format", "severity": "low"})

        return issues

    def _detect_anomalies(self, data: dict[str, Any]) -> list[dict]:
        """Detect statistical anomalies in numeric data."""
        anomalies = []
        for key, value in data.items():
            if not isinstance(value, (int, float)) or key.startswith("_"):
                continue

            history = self._anomaly_history.setdefault(key, [])
            history.append(float(value))
            if len(history) > 1000:
                self._anomaly_history[key] = history[-1000:]

            if len(history) >= 10:
                mean = sum(history) / len(history)
                std = (sum((v - mean) ** 2 for v in history) / len(history)) ** 0.5
                if std > 0:
                    z = abs(value - mean) / std
                    if z > 3:
                        anomalies.append({
                            "field": key,
                            "issue": "statistical_anomaly",
                            "severity": "medium",
                            "value": value,
                            "z_score": round(z, 2),
                            "expected_range": [round(mean - 2*std, 2), round(mean + 2*std, 2)],
                        })
        return anomalies

    def _auto_repair(self, data: dict[str, Any], issues: list[dict]) -> tuple[dict[str, Any], list[dict]]:
        """Auto-repair common data issues."""
        repairs = []
        for issue in issues:
            if not issue.get("auto_repair"):
                continue

            field = issue["field"]
            if field not in data:
                continue

            if issue["issue"] == "string_instead_of_number":
                try:
                    original = data[field]
                    cleaned = str(original).replace("$", "").replace(",", "").replace(" ", "").strip()
                    data[field] = float(cleaned)
                    repairs.append({"field": field, "action": "converted_to_float", "from": original, "to": data[field]})
                except (ValueError, AttributeError):
                    pass

            elif issue["issue"] == "float_should_be_int":
                original = data[field]
                data[field] = int(original)
                repairs.append({"field": field, "action": "converted_to_int", "from": original, "to": data[field]})

        return data, repairs

    def _apply_rule(self, rule: dict, data: dict) -> dict | None:
        field = rule.get("field", "")
        if field and field not in data:
            if rule.get("required"):
                return {"field": field, "issue": "required_field_missing", "severity": rule.get("severity", "high")}
            return None

        if field and "min" in rule:
            val = data.get(field)
            if isinstance(val, (int, float)) and val < rule["min"]:
                return {"field": field, "issue": f"below_minimum_{rule['min']}", "severity": rule.get("severity", "medium"), "value": val}

        if field and "max" in rule:
            val = data.get(field)
            if isinstance(val, (int, float)) and val > rule["max"]:
                return {"field": field, "issue": f"above_maximum_{rule['max']}", "severity": rule.get("severity", "medium"), "value": val}

        return None

    @staticmethod
    def _default_rules() -> list[dict]:
        return [
            {"field": "price", "min": 0, "severity": "critical"},
            {"field": "cost", "min": 0, "severity": "critical"},
            {"field": "quantity", "min": 0, "severity": "high"},
            {"field": "stock", "min": 0, "severity": "high"},
            {"field": "weight", "min": 0, "severity": "medium"},
            {"field": "discount", "min": 0, "max": 100, "severity": "medium"},
        ]
