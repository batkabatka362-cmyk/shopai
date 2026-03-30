"""JSONLoader — loads JSON and JSON-Lines files with optional schema validation.

Uses only the Python standard library (``json`` module).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("data_pipeline.json_loader")


class JSONLoaderError(Exception):
    """Raised for unrecoverable JSON loading errors."""


class JSONLoader:
    """Loads JSON / JSON-Lines files into Python objects with schema validation.

    Args:
        encoding: File encoding (default ``utf-8``).
    """

    def __init__(self, encoding: str = "utf-8") -> None:
        self._encoding = encoding

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, filepath: str) -> Any:
        """Load a standard JSON file and return the parsed Python object.

        Args:
            filepath: Path to a ``.json`` file.

        Returns:
            Parsed Python object (dict, list, etc.).

        Raises:
            JSONLoaderError: If the file is missing or contains invalid JSON.
        """
        filepath = os.path.expanduser(filepath)
        if not os.path.isfile(filepath):
            raise JSONLoaderError(f"File not found: {filepath}")

        try:
            with open(filepath, encoding=self._encoding) as fh:
                data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise JSONLoaderError(f"Invalid JSON in {filepath}: {exc}") from exc
        except OSError as exc:
            raise JSONLoaderError(f"Cannot open {filepath}: {exc}") from exc

        count = len(data) if isinstance(data, (list, dict)) else 1
        logger.info("Loaded JSON from %s (%d top-level items)", filepath, count)
        return data

    def load_jsonl(self, filepath: str) -> list[Any]:
        """Load a JSON-Lines file (one JSON object per line).

        Blank lines and comment lines starting with ``#`` are skipped.
        Lines that fail to parse are logged and skipped.

        Args:
            filepath: Path to a ``.jsonl`` / ``.ndjson`` file.

        Returns:
            List of parsed objects (one per valid line).

        Raises:
            JSONLoaderError: If the file cannot be opened.
        """
        filepath = os.path.expanduser(filepath)
        if not os.path.isfile(filepath):
            raise JSONLoaderError(f"File not found: {filepath}")

        records: list[Any] = []
        errors = 0

        try:
            with open(filepath, encoding=self._encoding) as fh:
                for lineno, raw_line in enumerate(fh, start=1):
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        logger.warning("Line %d skipped (JSON error): %s", lineno, exc)
                        errors += 1
        except OSError as exc:
            raise JSONLoaderError(f"Cannot open {filepath}: {exc}") from exc

        logger.info(
            "Loaded %d records from JSONL %s (%d parse errors)",
            len(records),
            filepath,
            errors,
        )
        return records

    def validate_schema(
        self,
        data: Any,
        schema: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        """Validate *data* against a lightweight schema descriptor.

        Schema format::

            {
                "type": "object" | "array",          # top-level type
                "required": ["field1", "field2"],    # required keys (object only)
                "properties": {                      # per-field rules (object only)
                    "field_name": {
                        "type": "str" | "int" | "float" | "bool" | "list" | "dict",
                        "min": number,               # numeric lower bound (optional)
                        "max": number,               # numeric upper bound (optional)
                    }
                }
            }

        For ``type: "array"`` the ``item_schema`` key may hold a nested schema
        applied to every element.

        Args:
            data:   The Python object to validate.
            schema: Schema descriptor dict as above.

        Returns:
            ``(is_valid, errors)`` where *errors* is a list of human-readable
            violation strings (empty when valid).
        """
        errors: list[str] = []
        self._validate_node(data, schema, path="$", errors=errors)
        return (len(errors) == 0, errors)

    # ------------------------------------------------------------------
    # Convenience: parse from a string
    # ------------------------------------------------------------------

    def load_string(self, text: str) -> Any:
        """Parse a JSON string and return the Python object."""
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise JSONLoaderError(f"Invalid JSON string: {exc}") from exc

    # ------------------------------------------------------------------
    # Private validation helpers
    # ------------------------------------------------------------------

    _TYPE_MAP: dict[str, type] = {
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list": list,
        "dict": dict,
    }

    def _validate_node(
        self,
        value: Any,
        schema: dict[str, Any],
        path: str,
        errors: list[str],
    ) -> None:
        expected_type = schema.get("type")

        if expected_type == "object":
            if not isinstance(value, dict):
                errors.append(f"{path}: expected object, got {type(value).__name__}")
                return
            for field in schema.get("required", []):
                if field not in value:
                    errors.append(f"{path}.{field}: required field missing")
            for field, field_schema in schema.get("properties", {}).items():
                if field in value:
                    self._validate_node(value[field], field_schema, f"{path}.{field}", errors)

        elif expected_type == "array":
            if not isinstance(value, list):
                errors.append(f"{path}: expected array, got {type(value).__name__}")
                return
            item_schema = schema.get("item_schema")
            if item_schema:
                for i, item in enumerate(value):
                    self._validate_node(item, item_schema, f"{path}[{i}]", errors)

        elif expected_type in self._TYPE_MAP:
            py_type = self._TYPE_MAP[expected_type]
            # Allow int where float is expected
            if expected_type == "float" and isinstance(value, int):
                value = float(value)
            if not isinstance(value, py_type):
                errors.append(
                    f"{path}: expected {expected_type}, got {type(value).__name__}"
                )
                return
            if expected_type in ("int", "float"):
                if "min" in schema and value < schema["min"]:
                    errors.append(f"{path}: {value} is below minimum {schema['min']}")
                if "max" in schema and value > schema["max"]:
                    errors.append(f"{path}: {value} exceeds maximum {schema['max']}")

        elif expected_type is not None:
            errors.append(f"{path}: unknown schema type '{expected_type}'")
