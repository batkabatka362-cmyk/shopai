"""Schema Registry — input/output schemas for engines."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("knowledge.schemas")


class SchemaRegistry:
    def __init__(self) -> None:
        self._schemas: dict[str, dict[str, Any]] = {}

    def register(self, name: str, schema: dict[str, Any]) -> None:
        self._schemas[name] = schema

    def get(self, name: str) -> dict[str, Any] | None:
        return self._schemas.get(name)

    def validate(self, name: str, data: dict[str, Any]) -> list[str]:
        schema = self._schemas.get(name)
        if not schema:
            return [f"Schema '{name}' not found"]
        errors = []
        for field, field_type in schema.get("required", {}).items():
            if field not in data:
                errors.append(f"Missing: {field}")
        return errors

    def list_schemas(self) -> list[str]:
        return list(self._schemas.keys())
