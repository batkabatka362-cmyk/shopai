"""Tests for audit-pass-41 fixes — defensive hardening across
the data_pipeline/processing layer (cleaner, validator,
normalizer, transformer).

data_pipeline is the outer boundary where external / webhook
/ scraper data enters ShopAI, so bad data here propagates
into every downstream module. Pre-audit these 4 files
assumed their callers passed clean dict-shaped records and
well-formed config dicts. Real production data from scrapers
and webhooks sometimes includes:

  * raw strings / None / int items in a "list of records"
    (when a parser gave up halfway)
  * schema dicts with missing keys / non-dict values
  * numeric fields as ``"$99.99"`` / ``"N/A"`` strings
  * bool values where int/float was expected
  * unhashable keys (nested dicts) in pivot tables
  * malformed transformation descriptors

Real bugs fixed in this pass:

  * DataValidator.check_field_types accepted ``True`` as a
    valid integer because ``isinstance(True, int)`` is
    ``True`` in Python. The schema now correctly rejects
    bool values where int/float is expected.

Plus the usual None-coercion / non-dict-record-skip at every
public entry point.
"""
from __future__ import annotations

import pytest

from data_pipeline.processing.cleaner import DataCleaner
from data_pipeline.processing.normalizer import DataNormalizer
from data_pipeline.processing.transformer import DataTransformer
from data_pipeline.processing.validator import DataValidator


# ═══════════════════════════════════════════════════════════
# DataCleaner
# ═══════════════════════════════════════════════════════════


class TestDataCleaner:
    def test_none_data_does_not_crash(self):
        c = DataCleaner()
        assert c.clean(None) == []

    def test_non_list_data_does_not_crash(self):
        c = DataCleaner()
        assert c.clean("not a list") == []
        assert c.clean({"not": "a list"}) == []

    def test_mixed_list_skips_non_dicts(self):
        c = DataCleaner()
        result = c.clean([
            None,
            "raw string",
            42,
            {"name": "  valid  "},
            [1, 2, 3],
        ])
        assert len(result) == 1
        assert result[0]["name"] == "valid"

    def test_remove_duplicates_handles_unhashable_keys(self):
        """Regression: pre-audit ``key in seen`` crashed with
        TypeError when the key was an unhashable type (e.g. a
        nested dict value in a legitimate record)."""
        c = DataCleaner()
        result = c.remove_duplicates(
            [
                {"id": {"nested": "dict"}, "x": 1},
                {"id": 1, "x": 2},
                {"id": 1, "x": 3},  # dedup target
            ],
            "id",
        )
        # Unhashable-key record kept, int 1 deduplicated.
        assert len(result) == 2

    def test_remove_duplicates_none_data(self):
        c = DataCleaner()
        assert c.remove_duplicates(None, "id") == []

    def test_fill_missing_non_dict_items_skipped(self):
        c = DataCleaner()
        result = c.fill_missing(
            ["bad", None, {"x": None}, {"x": 5}],
            field="x",
            default_value=0,
        )
        assert len(result) == 2
        assert result[0]["x"] == 0
        assert result[1]["x"] == 5

    def test_strip_whitespace_handles_non_list(self):
        assert DataCleaner.strip_whitespace(None) == []
        assert DataCleaner.strip_whitespace("bad") == []


# ═══════════════════════════════════════════════════════════
# DataValidator (bool-is-not-int regression)
# ═══════════════════════════════════════════════════════════


class TestDataValidatorTypeCheck:
    def test_bool_not_accepted_as_int(self):
        """Regression: ``isinstance(True, int)`` is True in
        Python, so the pre-audit type check silently accepted
        bool values for int-typed fields. A schema saying
        ``"qty": "int"`` should reject ``True``."""
        v = DataValidator()
        valid, invalid = v.validate(
            [{"qty": True}, {"qty": False}, {"qty": 5}],
            {"types": {"qty": "int"}},
        )
        assert len(valid) == 1  # only the real int
        assert len(invalid) == 2  # both bools rejected
        assert "bool" in invalid[0]["_validation_errors"][0].lower()

    def test_bool_not_accepted_as_float(self):
        v = DataValidator()
        valid, invalid = v.validate(
            [{"price": True}, {"price": 1.5}, {"price": 10}],
            {"types": {"price": "float"}},
        )
        # True rejected, 1.5 ok, 10 (int-as-float) ok
        assert len(valid) == 2
        assert len(invalid) == 1

    def test_bool_rejected_in_range_check(self):
        """A bool shouldn't trip the numeric range check either."""
        v = DataValidator()
        valid, invalid = v.validate(
            [{"n": True}],
            {"ranges": {"n": {"min": 0, "max": 10}}},
        )
        # True is not a numeric for range purposes → no range
        # check, no error (the type check is the right place
        # to catch bool-as-int).
        assert len(valid) == 1

    def test_int_still_validates_as_int(self):
        v = DataValidator()
        valid, _ = v.validate(
            [{"qty": 5}, {"qty": 0}, {"qty": -1}],
            {"types": {"qty": "int"}},
        )
        assert len(valid) == 3


class TestDataValidatorDefensive:
    def test_none_data_returns_empty(self):
        v = DataValidator()
        assert v.validate(None, {"required": ["id"]}) == ([], [])

    def test_none_schema_passes_everything_through(self):
        v = DataValidator()
        valid, invalid = v.validate([{"id": 1}, {"id": 2}], None)
        assert len(valid) == 2
        assert len(invalid) == 0

    def test_non_dict_record_reported_as_invalid(self):
        v = DataValidator()
        valid, invalid = v.validate(
            ["raw string", None, {"id": 1}],
            {"required": ["id"]},
        )
        assert len(valid) == 1
        assert len(invalid) == 2

    def test_malformed_schema_does_not_crash(self):
        """Schema with non-list ``required`` / non-dict
        ``types`` / non-dict ``ranges`` must not crash."""
        v = DataValidator()
        valid, invalid = v.validate(
            [{"id": 1}],
            {
                "required": "not a list",
                "types": "not a dict",
                "ranges": 42,
            },
        )
        assert len(valid) == 1  # Nothing to validate.


# ═══════════════════════════════════════════════════════════
# DataNormalizer
# ═══════════════════════════════════════════════════════════


class TestDataNormalizer:
    def test_none_data_does_not_crash(self):
        n = DataNormalizer()
        assert n.normalize(None) == []

    def test_non_list_data_does_not_crash(self):
        n = DataNormalizer()
        assert n.normalize("not a list") == []

    def test_no_config_deep_copies(self):
        n = DataNormalizer()
        src = [{"x": 1}]
        result = n.normalize(src)
        assert result == src
        # Mutation of returned dict must not affect source.
        result[0]["x"] = 999
        assert src[0]["x"] == 1

    def test_non_numeric_min_max_field_does_not_crash(self):
        """Regression: pre-audit ``float(value)`` crashed on
        ``"N/A"`` / ``"$99.99"`` / None strings from dirty
        webhook data. Now uses safe_float."""
        n = DataNormalizer()
        result = n.normalize(
            [{"views": "N/A"}, {"views": "$500"}, {"views": 750}],
            {"min_max_fields": {"views": {"min": 0, "max": 1000}}},
        )
        # N/A → 0.0, $500 → 0.5, 750 → 0.75
        assert result[0]["views"] == 0.0
        assert result[1]["views"] == 0.5
        assert result[2]["views"] == 0.75

    def test_malformed_min_max_cfg_does_not_crash(self):
        n = DataNormalizer()
        # cfg is not a dict
        result = n.normalize(
            [{"v": 5}],
            {"min_max_fields": {"v": "not a dict"}},
        )
        assert result[0]["v"] == 5  # passed through

    def test_malformed_config_fields_non_list(self):
        n = DataNormalizer()
        result = n.normalize(
            [{"price": "$100"}],
            {"price_fields": "not a list"},
        )
        # Pass-through since price_fields is malformed.
        assert "price" in result[0]

    def test_mixed_list_skips_non_dicts(self):
        n = DataNormalizer()
        result = n.normalize(
            ["bad", None, {"x": 1}],
            {"rename": {"x": "y"}},
        )
        assert len(result) == 1
        assert result[0]["y"] == 1


# ═══════════════════════════════════════════════════════════
# DataTransformer
# ═══════════════════════════════════════════════════════════


class TestDataTransformer:
    def test_none_data_does_not_crash(self):
        t = DataTransformer()
        assert t.transform(None, []) == []
        assert t.transform([{"x": 1}], None) == [{"x": 1}]

    def test_non_dict_records_filtered(self):
        t = DataTransformer()
        result = t.transform(
            ["bad", None, {"x": 1}, 42],
            [{"op": "keep", "fields": ["x"]}],
        )
        assert len(result) == 1

    def test_malformed_transformation_descriptor_skipped(self):
        t = DataTransformer()
        result = t.transform(
            [{"x": 1}],
            ["not a dict", None, {"op": "rename", "field_map": "not a dict"}],
        )
        # All transforms were malformed → pass-through.
        assert result == [{"x": 1}]

    def test_flatten_non_dict_returns_empty(self):
        t = DataTransformer()
        assert t.flatten(None) == {}
        assert t.flatten("string") == {}

    def test_rename_fields_non_dict_record(self):
        result = DataTransformer.rename_fields(None, {"a": "b"})
        assert result == {}

    def test_pivot_unhashable_key_skipped(self):
        """Pivot uses record values as dict keys — if the key
        value is unhashable (e.g. a nested dict) it can't go
        into the output dict. Skip rather than crash."""
        t = DataTransformer()
        result = t.pivot(
            [
                {"k": {"nested": "dict"}, "v": 1},
                {"k": "ok", "v": 2},
            ],
            "k", "v",
        )
        assert result == {"ok": 2}

    def test_pivot_non_list(self):
        t = DataTransformer()
        assert t.pivot(None, "k", "v") == {}

    def test_compute_derived_field_non_dict_record(self):
        result = DataTransformer.compute_derived_field(
            None, "margin", "price - cost",
        )
        assert result == {"margin": None}

    def test_compute_derived_field_non_string_expression(self):
        result = DataTransformer.compute_derived_field(
            {"price": 10}, "margin", 42,
        )
        assert result["margin"] is None
