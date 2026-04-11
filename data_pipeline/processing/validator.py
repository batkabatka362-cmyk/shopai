"""DataValidator — validates data records against schema-like rules."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("data_pipeline.validator")

# Python type names accepted in type_map
_PYTHON_TYPES: dict[str, type] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
}


class DataValidator:
    """Validates records against a schema dict and separates valid from invalid.

    Schema format passed to :meth:`validate` / :meth:`validate_record`::

        {
            "required": ["id", "price"],
            "types": {
                "id":    "str",
                "price": "float",
                "qty":   "int",
            },
            "ranges": {
                "price": {"min": 0.0, "max": 1_000_000},
                "qty":   {"min": 0},
            },
        }
    """

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    def validate(
        self,
        data: list[dict[str, Any]],
        schema: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Validate every record in *data* against *schema*.

        Args:
            data:   List of input records.
            schema: Validation schema (see class docstring).

        Returns:
            ``(valid_records, invalid_records)`` where invalid records have
            a ``"_validation_errors"`` key listing failure reasons.
        """
        # Defensive coercion of the public entry point.
        # Audit pass 41.
        if not isinstance(data, list):
            return [], []
        if not isinstance(schema, dict):
            # No schema → everything is "valid" (pass-through).
            return [r for r in data if isinstance(r, dict)], []

        valid: list[dict[str, Any]] = []
        invalid: list[dict[str, Any]] = []

        for record in data:
            if not isinstance(record, dict):
                # Non-dict items can't be validated and can't
                # be annotated with errors. Report them as
                # invalid with a synthetic marker.
                invalid.append({
                    "_validation_errors": [
                        f"Record is not a dict (got {type(record).__name__})"
                    ],
                })
                continue
            is_valid, errors = self.validate_record(record, schema)
            if is_valid:
                valid.append(record)
            else:
                annotated = dict(record)
                annotated["_validation_errors"] = errors
                invalid.append(annotated)

        logger.info(
            "Validation complete: %d valid, %d invalid (of %d total)",
            len(valid),
            len(invalid),
            len(data),
        )
        return valid, invalid

    def validate_record(
        self,
        record: dict[str, Any],
        schema: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        """Validate a single *record* against *schema*.

        Args:
            record: The record dict to validate.
            schema: Validation schema.

        Returns:
            ``(is_valid, error_messages)``
        """
        if not isinstance(record, dict):
            return False, [f"Record is not a dict (got {type(record).__name__})"]
        if not isinstance(schema, dict):
            return True, []

        errors: list[str] = []

        required = schema.get("required") or []
        if isinstance(required, list):
            errors.extend(self.check_required_fields(record, required))

        type_map = schema.get("types") or {}
        if isinstance(type_map, dict):
            errors.extend(self.check_field_types(record, type_map))

        range_map = schema.get("ranges") or {}
        if isinstance(range_map, dict):
            errors.extend(self.check_value_ranges(record, range_map))

        return (len(errors) == 0, errors)

    # ------------------------------------------------------------------
    # Individual check helpers
    # ------------------------------------------------------------------

    @staticmethod
    def check_required_fields(
        record: dict[str, Any],
        required_fields: list[str],
    ) -> list[str]:
        """Return a list of error strings for any required fields that are missing
        or whose value is ``None`` or empty string.

        Args:
            record:          The record to check.
            required_fields: Field names that must be present and non-empty.

        Returns:
            List of error strings; empty if all required fields are present.
        """
        errors: list[str] = []
        if not isinstance(record, dict) or not isinstance(required_fields, list):
            return errors
        for field in required_fields:
            if not isinstance(field, str):
                continue
            val = record.get(field)
            if val is None or val == "":
                errors.append(f"Required field missing or empty: '{field}'")
        return errors

    @staticmethod
    def check_field_types(
        record: dict[str, Any],
        type_map: dict[str, str],
    ) -> list[str]:
        """Return error strings for fields whose value does not match the expected type.

        Args:
            record:   The record to check.
            type_map: Mapping of ``field_name → type_name`` where type_name is one of
                      ``str``, ``int``, ``float``, ``bool``, ``list``, ``dict``.
                      Fields absent from the record are skipped.

        Returns:
            List of type-mismatch error strings.
        """
        errors: list[str] = []
        if not isinstance(record, dict) or not isinstance(type_map, dict):
            return errors
        for field, type_name in type_map.items():
            if not isinstance(field, str) or not isinstance(type_name, str):
                continue
            if field not in record or record[field] is None:
                continue  # absence checked by check_required_fields
            expected = _PYTHON_TYPES.get(type_name)
            if expected is None:
                errors.append(f"Unknown type '{type_name}' for field '{field}'")
                continue
            value = record[field]
            # ``bool`` is a subclass of ``int`` in Python, so
            # ``isinstance(True, int)`` is True. When the
            # schema says ``"qty": "int"`` we do NOT want
            # ``True`` to validate as a valid integer. Audit
            # pass 41 bug fix.
            if expected is int and isinstance(value, bool):
                errors.append(
                    f"Field '{field}': expected int, got bool"
                )
                continue
            # Similarly, allow int where float is expected, but
            # reject bool-masquerading-as-int.
            if expected is float:
                if isinstance(value, bool):
                    errors.append(
                        f"Field '{field}': expected float, got bool"
                    )
                    continue
                if isinstance(value, int):
                    continue
            if not isinstance(value, expected):
                errors.append(
                    f"Field '{field}': expected {type_name}, got {type(value).__name__}"
                )
        return errors

    @staticmethod
    def check_value_ranges(
        record: dict[str, Any],
        range_map: dict[str, dict[str, Any]],
    ) -> list[str]:
        """Return error strings for numeric fields that fall outside defined bounds.

        Args:
            record:    The record to check.
            range_map: Mapping of ``field_name → {"min": ..., "max": ...}``.
                       Either ``min`` or ``max`` (or both) may be present.
                       Fields absent from the record or with non-numeric values
                       are skipped.

        Returns:
            List of range-violation error strings.
        """
        errors: list[str] = []
        if not isinstance(record, dict) or not isinstance(range_map, dict):
            return errors
        for field, bounds in range_map.items():
            if not isinstance(field, str) or not isinstance(bounds, dict):
                continue
            if field not in record or record[field] is None:
                continue
            value = record[field]
            # Reject bool masquerading as numeric — same rule
            # as check_field_types.
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            lo = bounds.get("min")
            hi = bounds.get("max")
            if lo is not None and isinstance(lo, (int, float)) and value < lo:
                errors.append(
                    f"Field '{field}': value {value} is below minimum {lo}"
                )
            if hi is not None and isinstance(hi, (int, float)) and value > hi:
                errors.append(
                    f"Field '{field}': value {value} exceeds maximum {hi}"
                )
        return errors
