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
        if not isinstance(filepath, str) or not filepath:
            raise JSONLoaderError("filepath must be a non-empty string")
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
        if not isinstance(filepath, str) or not filepath:
            raise JSONLoaderError("filepath must be a non-empty string")
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
        if not isinstance(schema, dict):
            # No schema → everything is trivially valid
            # (matches the processing/validator.py pass-41
            # convention).
            return True, []
        errors: list[str] = []
        self._validate_node(data, schema, path="$", errors=errors)
        return (len(errors) == 0, errors)

    # ------------------------------------------------------------------
    # Convenience: parse from a string
    # ------------------------------------------------------------------

    def load_string(self, text: str) -> Any:
        """Parse a JSON string and return the Python object."""
        if not isinstance(text, (str, bytes, bytearray)):
            # Pre-audit ``json.loads(None)`` raised TypeError
            # which the ``except json.JSONDecodeError`` clause
            # did NOT catch, so the error propagated with a
            # confusing "expected str/bytes" message instead
            # of the JSONLoaderError the docstring implies.
            # Audit pass 45.
            raise JSONLoaderError(
                f"load_string expected str/bytes, got {type(text).__name__}"
            )
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
        if not isinstance(schema, dict):
            # Malformed schema sub-node → report once, don't
            # crash.
            errors.append(f"{path}: invalid schema (not a dict)")
            return
        expected_type = schema.get("type")

        if expected_type == "object":
            if not isinstance(value, dict):
                errors.append(f"{path}: expected object, got {type(value).__name__}")
                return
            required = schema.get("required") or []
            if isinstance(required, list):
                for field in required:
                    if isinstance(field, str) and field not in value:
                        errors.append(f"{path}.{field}: required field missing")
            properties = schema.get("properties") or {}
            if isinstance(properties, dict):
                for field, field_schema in properties.items():
                    if field in value:
                        self._validate_node(
                            value[field], field_schema, f"{path}.{field}", errors
                        )

        elif expected_type == "array":
            if not isinstance(value, list):
                errors.append(f"{path}: expected array, got {type(value).__name__}")
                return
            item_schema = schema.get("item_schema")
            if isinstance(item_schema, dict):
                for i, item in enumerate(value):
                    self._validate_node(item, item_schema, f"{path}[{i}]", errors)

        elif expected_type in self._TYPE_MAP:
            py_type = self._TYPE_MAP[expected_type]
            # ``bool`` is a subclass of ``int`` in Python, so
            # ``isinstance(True, int)`` is ``True``. Reject
            # bool explicitly when the schema expects int or
            # float — same bug class fixed in pass 41 for
            # ``data_pipeline.processing.validator``. Audit
            # pass 45.
            if expected_type == "int" and isinstance(value, bool):
                errors.append(f"{path}: expected int, got bool")
                return
            if expected_type == "float":
                if isinstance(value, bool):
                    errors.append(f"{path}: expected float, got bool")
                    return
                if isinstance(value, int):
                    value = float(value)
            if not isinstance(value, py_type):
                errors.append(
                    f"{path}: expected {expected_type}, got {type(value).__name__}"
                )
                return
            if expected_type in ("int", "float"):
                lo = schema.get("min")
                hi = schema.get("max")
                if isinstance(lo, (int, float)) and not isinstance(lo, bool) and value < lo:
                    errors.append(f"{path}: {value} is below minimum {lo}")
                if isinstance(hi, (int, float)) and not isinstance(hi, bool) and value > hi:
                    errors.append(f"{path}: {value} exceeds maximum {hi}")

        elif expected_type is not None:
            errors.append(f"{path}: unknown schema type '{expected_type}'")
