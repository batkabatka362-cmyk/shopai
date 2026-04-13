"""Tests for audit-pass-45 fixes — defensive hardening across
``data_pipeline.ingestion.file_loader.csv_loader`` and
``json_loader``.

Real bugs fixed:

  * CSVLoader._cast_row did ``k.strip()`` on every key. But
    ``csv.DictReader`` places values from EXTRA fields (rows
    with more columns than the header) under the ``None``
    key as a list — so ``None.strip()`` raised
    AttributeError. Real crash on any malformed CSV row.

  * CSVLoader.load used the caller's encoding (``"utf-8"``
    by default). Excel / Google Sheets export CSVs with a
    UTF-8 BOM on the first cell, which then became part of
    the first column name (``"\\ufeffid"`` instead of
    ``"id"``) and all downstream ``row["id"]`` lookups
    silently returned None. Now forces ``"utf-8-sig"`` when
    the encoding is utf-8.

  * CSVLoader._apply_schema reimplemented the float / int
    parser inline and got corner cases wrong. Replaced with
    ``safe_float`` / ``safe_int`` which already handle
    ``"$1,234.56"`` / None / empty / garbage.

  * JSONLoader.load_string did ``json.loads(text)`` inside
    an ``except json.JSONDecodeError`` block. But
    ``json.loads(None)`` raises ``TypeError`` ("the JSON
    object must be str, bytes or bytearray, not
    NoneType"), NOT JSONDecodeError, so the error leaked
    out with a confusing type. The docstring implies all
    errors come back as ``JSONLoaderError``.

  * JSONLoader.validate_schema did ``self._validate_node(
    data, schema, ...)`` unconditionally. If schema was
    None / non-dict, the first ``schema.get("type")``
    inside ``_validate_node`` crashed.

  * JSONLoader._validate_node used ``isinstance(value,
    int)`` for the "int" schema type — but ``bool`` is a
    subclass of ``int``, so ``True`` silently validated as
    a valid integer. Same bug class fixed in pass 41 for
    ``data_pipeline.processing.validator``.

Plus defensive None-input coercion on every public method.
"""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from data_pipeline.ingestion.file_loader.csv_loader import (
    CSVLoader,
    CSVLoaderError,
)
from data_pipeline.ingestion.file_loader.json_loader import (
    JSONLoader,
    JSONLoaderError,
)


# ═══════════════════════════════════════════════════════════
# CSVLoader
# ═══════════════════════════════════════════════════════════


class TestCSVLoaderDefensive:
    def test_none_filepath_raises(self):
        cl = CSVLoader()
        with pytest.raises(CSVLoaderError, match="non-empty string"):
            cl.load(None)  # type: ignore[arg-type]

    def test_empty_filepath_raises(self):
        cl = CSVLoader()
        with pytest.raises(CSVLoaderError, match="non-empty string"):
            cl.load("")

    def test_non_string_filepath_raises(self):
        cl = CSVLoader()
        with pytest.raises(CSVLoaderError):
            cl.load(42)  # type: ignore[arg-type]

    def test_load_string_none(self):
        cl = CSVLoader()
        assert cl.load_string(None) == []  # type: ignore[arg-type]

    def test_validate_columns_empty_rows(self):
        cl = CSVLoader()
        missing = cl.validate_columns([], ["id", "name"])
        assert missing == ["id", "name"]

    def test_validate_columns_none_required(self):
        cl = CSVLoader()
        assert cl.validate_columns([{"id": 1}], None) == []  # type: ignore[arg-type]


class TestCSVLoaderBOM:
    def test_bom_stripped_from_header(self):
        """Regression: UTF-8 BOM from Excel exports glued to
        the first column name silently broke every lookup."""
        cl = CSVLoader()
        bom_csv = "\ufeffname,price\nfoo,10\nbar,20"
        rows = cl.load_string(bom_csv)
        assert len(rows) == 2
        assert "name" in rows[0]
        assert "\ufeffname" not in rows[0]

    def test_bom_stripped_from_file(self, tmp_path):
        path = tmp_path / "bom.csv"
        path.write_bytes("\ufeffid,label\n1,hello\n".encode("utf-8"))
        cl = CSVLoader()
        rows = cl.load(str(path))
        assert rows == [{"id": "1", "label": "hello"}]
        # The first-column name is exactly "id" with no BOM prefix.
        assert list(rows[0].keys())[0] == "id"


class TestCSVLoaderMalformedRows:
    def test_extra_fields_drops_none_key(self):
        """Regression: rows with more fields than the header
        produce a ``None`` key in csv.DictReader's output.
        Pre-audit ``k.strip()`` crashed on that None key."""
        cl = CSVLoader()
        # 2-column header, 4-column data row.
        csv_text = "name,price\nfoo,10,extra1,extra2"
        rows = cl.load_string(csv_text)
        assert len(rows) == 1
        # Only the header columns survive.
        assert rows[0] == {"name": "foo", "price": "10"}

    def test_missing_fields_row(self):
        cl = CSVLoader()
        # 3-column header, 2-column row → third column is None.
        csv_text = "a,b,c\n1,2"
        rows = cl.load_string(csv_text)
        # DictReader pads with None for missing columns.
        assert rows[0]["a"] == "1"
        assert rows[0]["b"] == "2"
        assert rows[0]["c"] is None


class TestCSVLoaderSchemaCast:
    def test_schema_uses_safe_float(self):
        """Non-numeric / None / empty values no longer crash."""
        cl = CSVLoader()
        rows = [
            {"price": "99.99"},
            {"price": "$1,234.56"},
            {"price": ""},
            {"price": "N/A"},
            {"price": None},
        ]
        casted = [cl._apply_schema(r, {"price": float}) for r in rows]
        assert casted[0]["price"] == 99.99
        assert casted[1]["price"] == 1234.56
        assert casted[2]["price"] == 0.0
        assert casted[3]["price"] == 0.0
        assert casted[4]["price"] is None  # None stays None

    def test_schema_uses_safe_int(self):
        cl = CSVLoader()
        casted = cl._apply_schema({"qty": "42"}, {"qty": int})
        assert casted["qty"] == 42
        # Garbage does not crash.
        casted2 = cl._apply_schema({"qty": "bad"}, {"qty": int})
        assert casted2["qty"] == 0

    def test_schema_bool_from_string(self):
        cl = CSVLoader()
        assert cl._apply_schema({"ok": "true"}, {"ok": bool})["ok"] is True
        assert cl._apply_schema({"ok": "False"}, {"ok": bool})["ok"] is False
        assert cl._apply_schema({"ok": "yes"}, {"ok": bool})["ok"] is True

    def test_schema_non_dict_row(self):
        assert CSVLoader._apply_schema(None, {"x": int}) == {}  # type: ignore[arg-type]
        assert CSVLoader._apply_schema("string", {"x": int}) == {}  # type: ignore[arg-type]

    def test_schema_non_dict_schema(self):
        row = {"x": "42"}
        # Non-dict schema → pass-through copy.
        assert CSVLoader._apply_schema(row, None) == row  # type: ignore[arg-type]

    def test_load_with_schema_non_dict_schema(self, tmp_path):
        path = tmp_path / "a.csv"
        path.write_text("x\n42\n")
        cl = CSVLoader()
        rows = cl.load_with_schema(str(path), None)  # type: ignore[arg-type]
        assert len(rows) == 1


# ═══════════════════════════════════════════════════════════
# JSONLoader
# ═══════════════════════════════════════════════════════════


class TestJSONLoaderDefensive:
    def test_none_filepath_raises(self):
        jl = JSONLoader()
        with pytest.raises(JSONLoaderError, match="non-empty string"):
            jl.load(None)  # type: ignore[arg-type]

    def test_empty_filepath_raises(self):
        jl = JSONLoader()
        with pytest.raises(JSONLoaderError):
            jl.load("")

    def test_load_jsonl_none_filepath(self):
        jl = JSONLoader()
        with pytest.raises(JSONLoaderError):
            jl.load_jsonl(None)  # type: ignore[arg-type]

    def test_load_string_none(self):
        """Regression: ``json.loads(None)`` raises TypeError
        which the except block did NOT catch — pre-audit the
        TypeError leaked out bypassing the JSONLoaderError
        contract."""
        jl = JSONLoader()
        with pytest.raises(JSONLoaderError):
            jl.load_string(None)  # type: ignore[arg-type]

    def test_load_string_int(self):
        jl = JSONLoader()
        with pytest.raises(JSONLoaderError):
            jl.load_string(42)  # type: ignore[arg-type]

    def test_load_string_valid_bytes(self):
        jl = JSONLoader()
        result = jl.load_string(b'{"a": 1}')
        assert result == {"a": 1}


class TestJSONLoaderValidateSchema:
    def test_none_schema_returns_valid(self):
        """Pre-audit ``schema.get("type")`` crashed on None
        schema. Now returns (True, [])."""
        jl = JSONLoader()
        ok, errors = jl.validate_schema({"any": "data"}, None)  # type: ignore[arg-type]
        assert ok is True
        assert errors == []

    def test_non_dict_schema_returns_valid(self):
        jl = JSONLoader()
        ok, errors = jl.validate_schema({"x": 1}, "not a dict")  # type: ignore[arg-type]
        assert ok is True

    def test_object_required_fields(self):
        jl = JSONLoader()
        ok, errors = jl.validate_schema(
            {"a": 1},
            {"type": "object", "required": ["a", "b"]},
        )
        assert ok is False
        assert any("b" in e for e in errors)

    def test_malformed_sub_schema_does_not_crash(self):
        """A sub-schema that isn't a dict should report once
        and not propagate a Python exception."""
        jl = JSONLoader()
        ok, errors = jl.validate_schema(
            {"x": 1},
            {"type": "object", "properties": {"x": "not a dict"}},
        )
        assert ok is False
        assert any("invalid schema" in e for e in errors)

    def test_non_list_required_ignored(self):
        jl = JSONLoader()
        ok, errors = jl.validate_schema(
            {"a": 1},
            {"type": "object", "required": "not a list"},
        )
        # Non-list required → no required checks, object is valid.
        assert ok is True

    def test_non_dict_properties_ignored(self):
        jl = JSONLoader()
        ok, errors = jl.validate_schema(
            {"a": 1},
            {"type": "object", "properties": "not a dict"},
        )
        assert ok is True


class TestJSONLoaderBoolIsNotInt:
    """Regression: ``isinstance(True, int)`` is True in
    Python, so the pre-audit type check silently accepted
    bool values for int-typed schema fields."""

    def test_bool_not_accepted_as_int(self):
        jl = JSONLoader()
        ok, errors = jl.validate_schema(
            {"qty": True},
            {"type": "object", "properties": {"qty": {"type": "int"}}},
        )
        assert ok is False
        assert any("bool" in e.lower() for e in errors)

    def test_bool_not_accepted_as_float(self):
        jl = JSONLoader()
        ok, errors = jl.validate_schema(
            {"price": False},
            {"type": "object", "properties": {"price": {"type": "float"}}},
        )
        assert ok is False
        assert any("bool" in e.lower() for e in errors)

    def test_int_still_validates_as_int(self):
        jl = JSONLoader()
        ok, _ = jl.validate_schema(
            {"qty": 5},
            {"type": "object", "properties": {"qty": {"type": "int"}}},
        )
        assert ok is True

    def test_int_validates_as_float(self):
        jl = JSONLoader()
        ok, _ = jl.validate_schema(
            {"price": 10},
            {"type": "object", "properties": {"price": {"type": "float"}}},
        )
        assert ok is True

    def test_range_bounds_reject_bool_min(self):
        """A bool in the min bound shouldn't pass the numeric
        range check either."""
        jl = JSONLoader()
        ok, _ = jl.validate_schema(
            {"n": 5},
            {"type": "object", "properties": {"n": {"type": "int", "min": True}}},
        )
        # Bool min is ignored, validation passes.
        assert ok is True


class TestJSONLoaderArray:
    def test_non_dict_item_schema_ignored(self):
        jl = JSONLoader()
        ok, _ = jl.validate_schema(
            [1, 2, 3],
            {"type": "array", "item_schema": "not a dict"},
        )
        # Invalid item_schema → array is accepted without per-item check.
        assert ok is True

    def test_valid_array(self):
        jl = JSONLoader()
        ok, _ = jl.validate_schema(
            [1, 2, 3],
            {"type": "array", "item_schema": {"type": "int"}},
        )
        assert ok is True

    def test_array_with_wrong_item_type(self):
        jl = JSONLoader()
        ok, errors = jl.validate_schema(
            [1, "two", 3],
            {"type": "array", "item_schema": {"type": "int"}},
        )
        assert ok is False
        assert any("$[1]" in e for e in errors)
