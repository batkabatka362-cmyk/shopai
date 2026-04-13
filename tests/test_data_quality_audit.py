"""Tests for audit-pass-47 fixes — defensive hardening in
``data_pipeline.quality.validator.DataQualityPipeline``.

This is the data quality gate that runs after Shopify sync and
before every engine sees a product. Bugs here propagate into
EVERY downstream engine's input — so defensive coverage matters.

Real bugs fixed:

  * ``title_not_empty`` rule did
    ``bool(str(p.get("title", "")).strip())``. When ``title``
    was present-but-None, ``str(None)`` produced the literal
    string ``"None"`` (non-empty, non-whitespace) and the
    rule silently PASSED. Every product with a null title
    was flagged as valid. Same class of bug for
    ``has_description``.

  * Every lambda rule that used ``float()`` / ``int()``
    crashed on real payloads: ``"$99.99"``, ``"1,234"``,
    ``"N/A"``, or None. Rules caught the exception via a
    bare ``except`` in ``_validate_records`` so the crash
    was silent — the rule just counted as failed — but
    that masked real data-quality signal (a product with a
    currency-formatted price was marked "bad" when it was
    fine).

  * ``_clean_products`` wrapped ``float()`` in try/except
    but ``int(rec.get("inventory_quantity", 0))`` was NOT
    wrapped — crashed loudly on non-numeric inventory.

  * ``_detect_anomalies`` did ``p["price"] > 0`` on raw
    values. ``"$99.99" > 0`` raises TypeError in Python 3.

  * ``_detect_anomalies`` did ``p.get("title", "").lower()``
    — ``None.lower()`` crashed on present-but-None titles.

  * Zero-inventory detection used ``p.get("inventory_quantity",
    0) == 0``. Shopify JSON often returns ``"0"`` as a
    string; ``"0" == 0`` is False in Python so string-zero
    inventory was silently missed.

  * ``run()`` had no input coercion; None / non-dict
    ``store_data`` crashed the very first ``.get()`` call.

  * ``get_data_quality()`` singleton was not thread-safe.
"""
from __future__ import annotations

import threading

import pytest

from data_pipeline.quality.validator import (
    CUSTOMER_RULES,
    DataQualityPipeline,
    ORDER_RULES,
    PRODUCT_RULES,
    _first_nonempty,
    _nonempty_str,
    get_data_quality,
)


# ═══════════════════════════════════════════════════════════
# String helpers
# ═══════════════════════════════════════════════════════════


class TestStringHelpers:
    def test_nonempty_str_none(self):
        assert _nonempty_str(None) == ""

    def test_nonempty_str_actual_string(self):
        assert _nonempty_str("  hello  ") == "hello"

    def test_nonempty_str_non_string(self):
        assert _nonempty_str(42) == "42"

    def test_first_nonempty_all_none(self):
        assert _first_nonempty(None, None, None) == ""

    def test_first_nonempty_picks_first(self):
        assert _first_nonempty(None, "  ", "valid", "other") == "valid"


# ═══════════════════════════════════════════════════════════
# Product rules (real bug fixes)
# ═══════════════════════════════════════════════════════════


class TestProductRulesNullSafety:
    def test_title_none_fails(self):
        """Regression: pre-audit ``str(None)`` → ``"None"``
        (non-empty), so null titles silently passed."""
        assert PRODUCT_RULES["title_not_empty"]({"title": None}) is False

    def test_title_empty_string_fails(self):
        assert PRODUCT_RULES["title_not_empty"]({"title": ""}) is False

    def test_title_whitespace_fails(self):
        assert PRODUCT_RULES["title_not_empty"]({"title": "   "}) is False

    def test_title_valid_passes(self):
        assert PRODUCT_RULES["title_not_empty"]({"title": "Valid Product"}) is True

    def test_title_falls_back_to_name(self):
        assert PRODUCT_RULES["title_not_empty"]({"title": None, "name": "Fallback"}) is True

    def test_description_none_fails(self):
        """Same null-vs-'None' bug on has_description."""
        assert PRODUCT_RULES["has_description"]({"body_html": None, "description": None}) is False

    def test_description_fallback(self):
        assert PRODUCT_RULES["has_description"]({"body_html": None, "description": "Real desc"}) is True


class TestProductRulesNumericSafety:
    def test_price_positive_currency_string(self):
        """Regression: ``float("$99.99")`` crashed."""
        assert PRODUCT_RULES["price_positive"]({"price": "$99.99"}) is True

    def test_price_positive_none(self):
        assert PRODUCT_RULES["price_positive"]({"price": None}) is False

    def test_price_positive_zero(self):
        assert PRODUCT_RULES["price_positive"]({"price": 0}) is False

    def test_price_positive_missing(self):
        assert PRODUCT_RULES["price_positive"]({}) is False

    def test_inventory_non_negative_string(self):
        """Numeric strings parse; garbage coerces to 0 (not
        negative) instead of crashing."""
        assert PRODUCT_RULES["inventory_non_negative"]({"inventory_quantity": "5"}) is True
        assert PRODUCT_RULES["inventory_non_negative"]({"inventory_quantity": "garbage"}) is True  # → 0, >= 0

    def test_inventory_non_negative_none(self):
        assert PRODUCT_RULES["inventory_non_negative"]({"inventory_quantity": None}) is True

    def test_cost_less_than_price_currency(self):
        assert PRODUCT_RULES["cost_less_than_price"]({
            "cost": "$50.00", "price": "$100.00"
        }) is True
        assert PRODUCT_RULES["cost_less_than_price"]({
            "cost": "$150.00", "price": "$100.00"
        }) is False

    def test_cost_less_than_price_no_cost_data(self):
        """Rule should short-circuit to True when cost is
        missing (can't assess without data)."""
        assert PRODUCT_RULES["cost_less_than_price"]({"price": "100"}) is True

    def test_has_cost_currency_string(self):
        assert PRODUCT_RULES["has_cost"]({"cost": "$50.00"}) is True

    def test_has_cost_zero(self):
        assert PRODUCT_RULES["has_cost"]({"cost": 0}) is False
        assert PRODUCT_RULES["has_cost"]({"cost": "0"}) is False


class TestOrderAndCustomerRules:
    def test_order_total_currency(self):
        assert ORDER_RULES["has_total"]({"total_price": "$500.00"}) is True

    def test_order_total_falls_back_to_total(self):
        assert ORDER_RULES["has_total"]({"total": "100"}) is True

    def test_order_total_zero(self):
        assert ORDER_RULES["has_total"]({"total_price": 0}) is False

    def test_customer_orders_string(self):
        assert CUSTOMER_RULES["has_orders"]({"orders_count": "5"}) is True

    def test_customer_orders_none(self):
        assert CUSTOMER_RULES["has_orders"]({"orders_count": None}) is True

    def test_customer_email_none(self):
        assert CUSTOMER_RULES["has_email"]({"email": None}) is False


# ═══════════════════════════════════════════════════════════
# run() defensive entry
# ═══════════════════════════════════════════════════════════


class TestRunDefensive:
    def test_none_store_data(self):
        p = DataQualityPipeline()
        r = p.run(None)
        assert r["status"] == "success"
        assert r["products"]["total"] == 0

    def test_non_dict_store_data(self):
        p = DataQualityPipeline()
        r = p.run("not a dict")
        assert r["status"] == "success"

    def test_null_products_field(self):
        p = DataQualityPipeline()
        r = p.run({"products": None})
        assert r["products"]["total"] == 0

    def test_non_list_products_field(self):
        p = DataQualityPipeline()
        r = p.run({"products": "not a list"})
        assert r["products"]["total"] == 0

    def test_mixed_product_list(self):
        """Non-dict items in the product list must not crash
        validation / cleaning / anomaly detection."""
        p = DataQualityPipeline()
        r = p.run({
            "products": [
                None,
                "raw string",
                42,
                {"id": "1", "price": 100, "title": "Good"},
                ["list item"],
            ],
        })
        assert r["products"]["total"] == 1  # only the dict survived


# ═══════════════════════════════════════════════════════════
# _clean_products (int crash regression)
# ═══════════════════════════════════════════════════════════


class TestCleanProducts:
    def test_non_numeric_inventory_quantity(self):
        """Regression: pre-audit ``int(rec.get("inventory_quantity",
        0))`` was NOT wrapped in try/except (``float()`` was)
        — crashed loudly on strings like ``"5 units"`` and None.
        safe_int silently coerces garbage to 0 instead."""
        p = DataQualityPipeline()
        cleaned = p._clean_products([
            {"id": "1", "price": 100, "cost": 50, "inventory_quantity": "5 units"},
            {"id": "2", "price": 100, "cost": 50, "inventory_quantity": None},
            {"id": "3", "price": 100, "cost": 50, "inventory_quantity": "10"},
        ])
        assert len(cleaned) == 3
        # Garbage and None both coerce to 0, numeric strings parse.
        assert cleaned[0]["inventory_quantity"] == 0
        assert cleaned[1]["inventory_quantity"] == 0
        assert cleaned[2]["inventory_quantity"] == 10

    def test_non_numeric_price(self):
        p = DataQualityPipeline()
        cleaned = p._clean_products([
            {"id": "1", "price": "$99.99", "cost": "$50.00"},
        ])
        assert cleaned[0]["price"] == 99.99
        assert cleaned[0]["cost"] == 50.0
        assert cleaned[0]["margin"] == round((99.99 - 50.0) / 99.99, 3)

    def test_non_dict_items_skipped(self):
        p = DataQualityPipeline()
        cleaned = p._clean_products([None, "string", {"id": "1", "price": 100}])
        assert len(cleaned) == 1


# ═══════════════════════════════════════════════════════════
# _detect_anomalies (None title + string zero)
# ═══════════════════════════════════════════════════════════


class TestDetectAnomalies:
    def test_null_title_duplicate_detection(self):
        """Regression: pre-audit ``p.get("title", "").lower()``
        crashed on ``"title": null``."""
        p = DataQualityPipeline()
        anomalies = p._detect_anomalies(
            [
                {"id": "1", "price": 100, "title": None},
                {"id": "2", "price": 100, "title": None},
            ],
            [],
        )
        # No crash; null titles are not duplicates (filtered out).
        assert not any(a["type"] == "duplicate_products" for a in anomalies)

    def test_string_zero_inventory_detected(self):
        """Regression: pre-audit ``p.get("inventory_quantity",
        0) == 0`` compared ``"0" == 0`` which is False in
        Python. Now uses safe_int."""
        p = DataQualityPipeline()
        anomalies = p._detect_anomalies(
            [
                {"id": "1", "price": 100, "inventory_quantity": "0", "title": "out"},
                {"id": "2", "price": 100, "inventory_quantity": 5, "title": "ok"},
            ],
            [],
        )
        zero = [a for a in anomalies if a["type"] == "zero_inventory"]
        assert len(zero) == 1
        assert zero[0]["count"] == 1

    def test_non_numeric_price_in_anomaly_detection(self):
        """Regression: ``p["price"] > 0`` on ``"$99.99"``
        crashed with TypeError."""
        p = DataQualityPipeline()
        # Just check it doesn't crash.
        anomalies = p._detect_anomalies(
            [
                {"id": "1", "price": "$99.99", "title": "a"},
                {"id": "2", "price": "$200.00", "title": "b"},
                {"id": "3", "price": "$2000.00", "title": "c"},  # outlier
            ],
            [],
        )
        assert isinstance(anomalies, list)

    def test_bool_margin_not_treated_as_negative(self):
        """``bool`` subclass of int — ``False < 0`` is False,
        but pre-audit would have treated bool values in
        margin as numeric."""
        p = DataQualityPipeline()
        anomalies = p._detect_anomalies(
            [{"id": "1", "price": 100, "margin": False, "title": "ok"}],
            [],
        )
        assert not any(a["type"] == "negative_margin" for a in anomalies)

    def test_real_negative_margin_flagged(self):
        p = DataQualityPipeline()
        anomalies = p._detect_anomalies(
            [{"id": "1", "price": 100, "margin": -0.5, "title": "bad"}],
            [],
        )
        assert any(a["type"] == "negative_margin" for a in anomalies)


# ═══════════════════════════════════════════════════════════
# Singleton thread safety
# ═══════════════════════════════════════════════════════════


class TestSingletonThreadSafety:
    def test_single_instance(self):
        # Clear any cached instance.
        if hasattr(get_data_quality, "_instance"):
            delattr(get_data_quality, "_instance")

        instances: list[DataQualityPipeline] = []
        barrier = threading.Barrier(8)

        def fire():
            barrier.wait()
            instances.append(get_data_quality())

        threads = [threading.Thread(target=fire) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All 8 threads should see the same instance.
        assert len({id(i) for i in instances}) == 1
