"""Schema Registry -- data schema registration, validation and defaults."""
from __future__ import annotations

import re
from typing import Any


# ---- Default schemas ---------------------------------------------------

_DEFAULT_SCHEMAS: dict[str, dict] = {
    "product": {
        "fields": {
            "id": {"type": "str", "required": True},
            "name": {"type": "str", "required": True, "min_length": 1, "max_length": 256},
            "price": {"type": "float", "required": True, "min": 0},
            "currency": {"type": "str", "required": False, "default": "USD"},
            "category": {"type": "str", "required": False},
            "description": {"type": "str", "required": False, "max_length": 5000},
            "tags": {"type": "list", "required": False, "item_type": "str"},
            "in_stock": {"type": "bool", "required": False, "default": True},
        }
    },
    "campaign": {
        "fields": {
            "id": {"type": "str", "required": True},
            "name": {"type": "str", "required": True, "min_length": 1},
            "platform": {"type": "str", "required": True},
            "budget": {"type": "float", "required": True, "min": 0},
            "start_date": {"type": "str", "required": True},
            "end_date": {"type": "str", "required": False},
            "status": {"type": "str", "required": False, "enum": ["draft", "active", "paused", "completed"]},
            "target_audience": {"type": "dict", "required": False},
        }
    },
    "customer": {
        "fields": {
            "id": {"type": "str", "required": True},
            "email": {"type": "str", "required": True, "pattern": r"^[^@\s]+@[^@\s]+\.[^@\s]+$"},
            "name": {"type": "str", "required": False},
            "segment": {"type": "str", "required": False},
            "lifetime_value": {"type": "float", "required": False, "min": 0},
            "tags": {"type": "list", "required": False, "item_type": "str"},
        }
    },
    "order": {
        "fields": {
            "id": {"type": "str", "required": True},
            "customer_id": {"type": "str", "required": True},
            "items": {"type": "list", "required": True},
            "total": {"type": "float", "required": True, "min": 0},
            "currency": {"type": "str", "required": False, "default": "USD"},
            "status": {"type": "str", "required": False, "enum": ["pending", "processing", "shipped", "delivered", "cancelled"]},
            "created_at": {"type": "str", "required": False},
        }
    },
    "analytics_event": {
        "fields": {
            "event_type": {"type": "str", "required": True},
            "timestamp": {"type": "str", "required": True},
            "source": {"type": "str", "required": True},
            "payload": {"type": "dict", "required": False},
            "user_id": {"type": "str", "required": False},
            "session_id": {"type": "str", "required": False},
        }
    },
}

_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "str": str,
    "int": int,
    "float": (int, float),
    "bool": bool,
    "list": list,
    "dict": dict,
}


class SchemaRegistry:
    """Register, retrieve, and validate data against named schemas."""

    def __init__(self, load_defaults: bool = True) -> None:
        self._schemas: dict[str, dict] = {}
        if load_defaults:
            for name, schema in _DEFAULT_SCHEMAS.items():
                self._schemas[name] = schema

    # ---- CRUD ----------------------------------------------------------

    def register(self, schema_name: str, schema: dict) -> None:
        if schema_name in self._schemas:
            raise ValueError(f"Schema '{schema_name}' already exists. Use update() instead.")
        self._schemas[schema_name] = schema

    def get(self, schema_name: str) -> dict:
        if schema_name not in self._schemas:
            raise KeyError(f"Schema '{schema_name}' not found")
        return self._schemas[schema_name]

    def update(self, schema_name: str, schema: dict) -> None:
        if schema_name not in self._schemas:
            raise KeyError(f"Schema '{schema_name}' not found")
        self._schemas[schema_name] = schema

    def delete(self, schema_name: str) -> bool:
        return self._schemas.pop(schema_name, None) is not None

    def list_schemas(self) -> list[str]:
        return sorted(self._schemas.keys())

    # ---- Validation ----------------------------------------------------

    def validate(self, data: dict, schema_name: str) -> tuple[bool, list[str]]:
        """Validate *data* against the named schema.

        Returns (is_valid, errors) where *errors* is a list of human-readable
        strings describing each problem.
        """
        schema = self._schemas.get(schema_name)
        if schema is None:
            return False, [f"Schema '{schema_name}' not found"]

        fields = schema.get("fields", {})
        errors: list[str] = []

        # Check required fields
        for field_name, field_schema in fields.items():
            if field_schema.get("required") and field_name not in data:
                errors.append(f"Missing required field: {field_name}")

        # Validate provided fields
        for field_name, value in data.items():
            field_schema = fields.get(field_name)
            if field_schema is None:
                continue  # allow extra fields
            field_errors = self._validate_field(value, field_schema)
            for err in field_errors:
                errors.append(f"Field '{field_name}': {err}")

        return (len(errors) == 0, errors)

    @staticmethod
    def _validate_field(value: Any, field_schema: dict) -> list[str]:
        errors: list[str] = []

        # Type check
        expected_type = field_schema.get("type")
        if expected_type and expected_type in _TYPE_MAP:
            py_type = _TYPE_MAP[expected_type]
            if not isinstance(value, py_type):
                errors.append(
                    f"expected type '{expected_type}', got '{type(value).__name__}'"
                )
                return errors  # skip further checks if type wrong

        # Numeric constraints
        if "min" in field_schema and isinstance(value, (int, float)):
            if value < field_schema["min"]:
                errors.append(f"value {value} < minimum {field_schema['min']}")
        if "max" in field_schema and isinstance(value, (int, float)):
            if value > field_schema["max"]:
                errors.append(f"value {value} > maximum {field_schema['max']}")

        # String constraints
        if isinstance(value, str):
            if "min_length" in field_schema and len(value) < field_schema["min_length"]:
                errors.append(
                    f"length {len(value)} < min_length {field_schema['min_length']}"
                )
            if "max_length" in field_schema and len(value) > field_schema["max_length"]:
                errors.append(
                    f"length {len(value)} > max_length {field_schema['max_length']}"
                )
            if "pattern" in field_schema:
                if not re.search(field_schema["pattern"], value):
                    errors.append(f"does not match pattern '{field_schema['pattern']}'")

        # Enum constraint
        if "enum" in field_schema and value not in field_schema["enum"]:
            errors.append(f"value '{value}' not in enum {field_schema['enum']}")

        # List item type
        if isinstance(value, list) and "item_type" in field_schema:
            item_py = _TYPE_MAP.get(field_schema["item_type"])
            if item_py:
                for i, item in enumerate(value):
                    if not isinstance(item, item_py):
                        errors.append(
                            f"item [{i}] expected type '{field_schema['item_type']}'"
                        )

        return errors
