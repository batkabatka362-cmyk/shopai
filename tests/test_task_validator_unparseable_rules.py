"""Tests for ``engines.execution_intelligence.task_validator``
-- silent-fail fix on business rule checks.

Before: when ``float(price)`` / ``int(quantity)`` raised, the
business-rule check silently fell through to nothing -- the
validator reported neither pass nor fail nor warning for that
record. Callers couldn't tell ""rule legitimately satisfied""
from ""rule check broken on bad input"".

After: unparseable numbers now surface as a ``warnings``
entry (not a failed check -- keeping the pass/fail counts
unchanged is the conservative choice). The validation result
now SHOWS that the rule didn't actually run for that input.
"""
from __future__ import annotations

import pytest

from engines.execution_intelligence.task_validator import (
    validate_tasks,
)


def _make_task(action_type: str, **parameters) -> dict:
    return {
        "task_id": "t-1",
        "action_type": action_type,
        "parameters": parameters,
    }


def _warnings_for(result: dict, task_id: str = "t-1") -> list[str]:
    """Pull the warnings list for the named task out of the
    validate_tasks return envelope."""
    for t in result.get("valid_tasks", []) + result.get(
        "invalid_tasks", [],
    ):
        if t.get("task_id") == task_id:
            validation = t.get("validation") or {}
            return validation.get("warnings", [])
    return []


class TestUnparseablePriceLogs:

    def test_unparseable_create_product_price(self):
        result = validate_tasks([
            _make_task("create_product", title="T", price="oops"),
        ])
        warns = _warnings_for(result)
        assert any(
            "price not a valid number" in w
            and "oops" in w
            for w in warns
        )

    def test_unparseable_ad_budget(self):
        result = validate_tasks([
            _make_task(
                "launch_ad", platform="facebook",
                budget="lots",
            ),
        ])
        warns = _warnings_for(result)
        assert any(
            "ad budget not a valid number" in w
            and "lots" in w
            for w in warns
        )

    def test_unparseable_inventory_quantity(self):
        result = validate_tasks([
            _make_task(
                "update_inventory",
                product_id="p1", quantity="some",
            ),
        ])
        warns = _warnings_for(result)
        assert any(
            "inventory quantity not a valid integer" in w
            and "some" in w
            for w in warns
        )

    def test_unparseable_discount_percentage(self):
        result = validate_tasks([
            _make_task(
                "create_discount", code="X",
                percentage="oh",
            ),
        ])
        warns = _warnings_for(result)
        assert any(
            "discount percentage not a valid number" in w
            and "oh" in w
            for w in warns
        )


class TestHappyPathStillWorks:
    """Behavior contract preserved -- valid inputs still
    produce passed/failed/warnings as before."""

    def test_valid_price_passes(self):
        result = validate_tasks([
            _make_task("create_product", title="T", price="9.99"),
        ])
        # The existing string-coercion-to-float path still
        # populates passed for a positive price -- the new
        # warning only fires on UNparseable values.
        warns = _warnings_for(result)
        assert not any(
            "price not a valid number" in w for w in warns
        )

    def test_zero_price_is_warning_not_unparseable(self):
        result = validate_tasks([
            _make_task("create_product", title="T", price="0"),
        ])
        warns = _warnings_for(result)
        # The pre-existing "price is zero" warning fires
        assert any("price is zero" in w for w in warns)
        # NOT the new unparseable warning
        assert not any(
            "price not a valid number" in w for w in warns
        )

    def test_missing_price_emits_no_unparseable_warning(self):
        result = validate_tasks([
            _make_task("create_product", title="T"),
        ])
        warns = _warnings_for(result)
        assert not any(
            "price not a valid number" in w for w in warns
        )
