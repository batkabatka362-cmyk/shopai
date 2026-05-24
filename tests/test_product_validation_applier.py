"""Tests for engines.product_validation.tag_applier + flow."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from engines.product_validation.tag_applier import (
    apply_validation_tags,
)


def _validated(pid="p1", passed=False, risk_level="high", **extra):
    return {
        "id": pid, "passed": passed,
        "risk_level": risk_level, **extra,
    }


def _product(pid, tags=None):
    return {"id": pid, "tags": list(tags or [])}


def _ok_router(applied_pid):
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=True, data={"id": applied_pid, "tags": []},
        error=None,
    )
    return router


class TestPassedFilter:

    def test_failed_product_tagged(self):
        with patch(
            "engines.product_validation.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.product_validation.tag_applier."
            "record_writeback",
        ):
            results = apply_validation_tags(
                [_validated(pid="p1", passed=False)],
                [_product("p1")],
            )
        assert len(results) == 1
        assert results[0]["applied"] is True

    def test_passed_product_silently_skipped(self):
        with patch(
            "engines.product_validation.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.product_validation.tag_applier."
            "record_writeback",
        ):
            results = apply_validation_tags(
                [_validated(pid="p1", passed=True)],
                [_product("p1")],
            )
        assert results == []


class TestTagComposition:

    @pytest.mark.parametrize("risk", [
        "high", "critical", "medium", "low", "unknown",
    ])
    def test_risk_level_appears_in_tag(self, risk):
        router = _ok_router("p1")
        with patch(
            "engines.product_validation.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.product_validation.tag_applier."
            "record_writeback",
        ):
            apply_validation_tags(
                [_validated(pid="p1", passed=False, risk_level=risk)],
                [_product("p1")],
            )
        params = router.execute.call_args.args[1]
        assert f"validation:risk_{risk}" in params["tags"]
        assert "validation:failed" in params["tags"]


class TestPatternZ:

    def test_success_records(self):
        with patch(
            "engines.product_validation.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.product_validation.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_validation_tags(
                [_validated(pid="p1", passed=False)],
                [_product("p1")],
            )
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "product_validation"
        assert kw["action_type"] == "apply_validation_tags"
        assert kw["success"] is True


class TestRouter:

    def test_router_unavailable_per_failed(self):
        with patch(
            "engines.product_validation.tag_applier._get_router",
            return_value=None,
        ), patch(
            "engines.product_validation.tag_applier."
            "record_writeback",
        ):
            results = apply_validation_tags(
                [
                    _validated(pid="p1", passed=False),
                    _validated(pid="p2", passed=True),  # filtered
                ],
                [_product("p1"), _product("p2")],
            )
        assert len(results) == 1
        assert results[0]["error"] == "router_unavailable"


class TestFlowOptIn:

    def _seed_input(self, *, apply_tags=False):
        return {
            "status": "success",
            "data": {
                "products": [
                    {
                        "id": "p1", "title": "Widget",
                        "tags": [],
                    },
                ],
                "apply_validation_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.product_validation.flow import (
            ProductValidationEngine,
        )
        with patch(
            "engines.product_validation.tag_applier."
            "apply_validation_tags",
        ) as apply_mock:
            result = ProductValidationEngine().run(
                self._seed_input(apply_tags=False),
            )
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_failures"] == []

    def test_opt_in_invokes_applier(self):
        from engines.product_validation.flow import (
            ProductValidationEngine,
        )
        with patch(
            "engines.product_validation.tag_applier."
            "apply_validation_tags",
            return_value=[
                {
                    "product_id": "p1", "applied": True,
                    "tags_added": 2, "merged_tags": [],
                    "risk_level": "high", "error": None,
                },
            ],
        ) as apply_mock:
            result = ProductValidationEngine().run(
                self._seed_input(apply_tags=True),
            )
        apply_mock.assert_called_once()
        assert result["data"]["tagged_failures"]

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.product_validation.flow import (
            ProductValidationEngine,
        )
        with patch(
            "engines.product_validation.tag_applier."
            "apply_validation_tags",
            side_effect=RuntimeError("boom"),
        ):
            result = ProductValidationEngine().run(
                self._seed_input(apply_tags=True),
            )
        assert result["status"] == "success"
        assert result["data"]["tagged_failures"] == []
