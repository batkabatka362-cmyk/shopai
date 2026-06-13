"""Tests for engines.product_filter.tag_applier + flow."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.product_filter.tag_applier import (
    apply_filter_tags,
)


def _accepted(pid="p1", **extra):
    return {"id": pid, **extra}


def _product(pid, tags=None):
    return {"id": pid, "tags": list(tags or [])}


def _ok_router(applied_pid):
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=True, data={"id": applied_pid, "tags": []},
        error=None,
    )
    return router


class TestBasic:

    def test_accepted_tagged(self):
        with patch(
            "engines.product_filter.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.product_filter.tag_applier.record_writeback",
        ):
            results = apply_filter_tags(
                [_accepted(pid="p1")],
                [_product("p1")],
            )
        assert len(results) == 1
        assert results[0]["applied"] is True

    def test_tag_composition(self):
        router = _ok_router("p1")
        with patch(
            "engines.product_filter.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.product_filter.tag_applier.record_writeback",
        ):
            apply_filter_tags(
                [_accepted(pid="p1")],
                [_product("p1", tags=["existing"])],
            )
        params = router.execute.call_args.args[1]
        assert set(params["tags"]) == {"existing", "filter:accepted"}

    def test_empty_returns_empty(self):
        assert apply_filter_tags([], []) == []

    def test_no_pid_skipped(self):
        with patch(
            "engines.product_filter.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.product_filter.tag_applier.record_writeback",
        ):
            results = apply_filter_tags(
                [{}], [_product("p1")],
            )
        assert results == []


class TestPatternZ:

    def test_success_records(self):
        with patch(
            "engines.product_filter.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.product_filter.tag_applier.record_writeback",
        ) as record_mock:
            apply_filter_tags(
                [_accepted(pid="p1")],
                [_product("p1")],
            )
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "product_filter"
        assert kw["action_type"] == "apply_filter_tags"
        assert kw["success"] is True


class TestFlowOptIn:

    def _seed(self, *, apply_tags=False):
        return {
            "status": "success",
            "data": {
                "products": [
                    {
                        "id": "p1", "title": "Widget",
                        "price": 100, "cost": 30,
                        "tags": [], "brand": "Acme",
                        "country": "US",
                    },
                ],
                "apply_filter_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.product_filter.flow import (
            ProductFilterEngine,
        )
        with patch(
            "engines.product_filter.tag_applier.apply_filter_tags",
        ) as apply_mock:
            result = ProductFilterEngine().run(self._seed(apply_tags=False))
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_accepted"] == []

    def test_opt_in_invokes_applier(self):
        from engines.product_filter.flow import (
            ProductFilterEngine,
        )
        with patch(
            "engines.product_filter.tag_applier.apply_filter_tags",
            return_value=[
                {
                    "product_id": "p1", "applied": True,
                    "tags_added": 1, "merged_tags": [],
                    "error": None,
                },
            ],
        ) as apply_mock:
            result = ProductFilterEngine().run(self._seed(apply_tags=True))
        apply_mock.assert_called_once()
        assert result["data"]["tagged_accepted"]

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.product_filter.flow import (
            ProductFilterEngine,
        )
        with patch(
            "engines.product_filter.tag_applier.apply_filter_tags",
            side_effect=RuntimeError("boom"),
        ):
            result = ProductFilterEngine().run(self._seed(apply_tags=True))
        assert result["status"] == "success"
        assert result["data"]["tagged_accepted"] == []
