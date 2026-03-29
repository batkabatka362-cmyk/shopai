"""TestGenerator — auto-generates test cases for engines."""
from __future__ import annotations

import copy
import random
from typing import Any


class TestGenerator:
    """Generates test cases from engine specs and examples."""

    def generate_for_engine(self, engine_name: str, input_fields: list[str], output_fields: list[str], count: int = 5) -> list[dict[str, Any]]:
        """Generate test cases based on engine input/output spec."""
        cases = []

        # Case 1: Happy path with all fields
        cases.append(self._happy_path(engine_name, input_fields, output_fields))

        # Case 2: Minimal input (only required fields)
        cases.append(self._minimal_input(engine_name, input_fields))

        # Case 3: Empty values
        cases.append(self._empty_values(engine_name, input_fields))

        # Case 4: Large input
        cases.append(self._large_input(engine_name, input_fields))

        # Case 5+: Random variations
        for i in range(max(0, count - 4)):
            cases.append(self._random_case(engine_name, input_fields, i))

        return cases

    def generate_edge_cases(self, engine_name: str, input_fields: list[str]) -> list[dict[str, Any]]:
        """Generate edge case tests."""
        cases = []
        cases.append({"name": f"{engine_name}_empty_input", "input": {}, "expect_status": "failed"})
        cases.append({"name": f"{engine_name}_null_values", "input": {f: None for f in input_fields}, "expect_status": "failed"})
        cases.append({"name": f"{engine_name}_wrong_types", "input": {f: 12345 for f in input_fields}, "expect_status": ["completed", "failed"]})
        cases.append({"name": f"{engine_name}_unicode", "input": {f: "日本語テスト🎉" for f in input_fields}, "expect_status": ["completed", "failed"]})
        cases.append({"name": f"{engine_name}_huge_string", "input": {f: "x" * 100000 for f in input_fields}, "expect_status": ["completed", "failed"]})
        return cases

    def _happy_path(self, engine_name: str, fields: list[str], outputs: list[str]) -> dict[str, Any]:
        return {
            "name": f"{engine_name}_happy_path",
            "input": {f: self._sample_value(f) for f in fields},
            "expect_status": "completed",
            "expect_output_fields": outputs,
        }

    def _minimal_input(self, engine_name: str, fields: list[str]) -> dict[str, Any]:
        return {
            "name": f"{engine_name}_minimal",
            "input": {f: self._minimal_value(f) for f in fields},
            "expect_status": ["completed", "failed"],
        }

    def _empty_values(self, engine_name: str, fields: list[str]) -> dict[str, Any]:
        return {
            "name": f"{engine_name}_empty_values",
            "input": {f: {} if "data" in f or "config" in f else [] if "list" in f else "" for f in fields},
            "expect_status": ["completed", "failed"],
        }

    def _large_input(self, engine_name: str, fields: list[str]) -> dict[str, Any]:
        return {
            "name": f"{engine_name}_large_input",
            "input": {f: [self._sample_value(f)] * 100 if isinstance(self._sample_value(f), dict) else self._sample_value(f) for f in fields},
            "expect_status": ["completed", "failed"],
        }

    def _random_case(self, engine_name: str, fields: list[str], idx: int) -> dict[str, Any]:
        return {
            "name": f"{engine_name}_random_{idx}",
            "input": {f: self._random_value(f) for f in fields},
            "expect_status": ["completed", "failed"],
        }

    @staticmethod
    def _sample_value(field: str) -> Any:
        f = field.lower()
        if "product" in f: return [{"name": "Test Product", "price": 29.99, "cost": 10}]
        if "customer" in f: return [{"name": "Test Customer", "orders": 5, "total_spent": 200}]
        if "campaign" in f: return {"name": "Test Campaign", "budget": 1000}
        if "order" in f: return [{"id": "ord_1", "total": 49.99, "status": "completed"}]
        if "keyword" in f: return [{"keyword": "test keyword", "volume": 1000}]
        if "config" in f or "criteria" in f: return {"enabled": True}
        if "data" in f: return {"key": "value"}
        return "test_value"

    @staticmethod
    def _minimal_value(field: str) -> Any:
        f = field.lower()
        if "product" in f or "customer" in f or "order" in f: return [{}]
        if "config" in f or "criteria" in f: return {}
        return ""

    @staticmethod
    def _random_value(field: str) -> Any:
        f = field.lower()
        if "product" in f:
            return [{"name": f"Product_{random.randint(1,100)}", "price": round(random.uniform(5, 200), 2), "cost": round(random.uniform(1, 50), 2)}]
        if "config" in f or "criteria" in f:
            return {"threshold": random.uniform(0, 10)}
        return f"random_{random.randint(1,9999)}"
