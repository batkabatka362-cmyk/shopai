"""Tests for engines.wishlist.tag_applier + flow."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.wishlist.tag_applier import apply_wishlist_tags


def _entry(pid="p1", count=5, **extra):
    return {"product_id": pid, "wishlist_count": count, **extra}


def _product(pid, tags=None):
    return {"id": pid, "tags": list(tags or [])}


def _ok_router(applied_pid):
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=True, data={"id": applied_pid, "tags": []},
        error=None,
    )
    return router


class TestThreshold:

    def test_below_threshold_skipped(self):
        with patch(
            "engines.wishlist.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.wishlist.tag_applier.record_writeback",
        ):
            results = apply_wishlist_tags(
                [_entry(pid="p1", count=2)],
                [_product("p1")],
            )
        assert results == []

    def test_at_threshold_tagged(self):
        with patch(
            "engines.wishlist.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.wishlist.tag_applier.record_writeback",
        ):
            results = apply_wishlist_tags(
                [_entry(pid="p1", count=3)],
                [_product("p1")],
            )
        assert len(results) == 1
        assert results[0]["applied"] is True


class TestTagComposition:

    def test_high_demand_only_below_top_tier(self):
        router = _ok_router("p1")
        with patch(
            "engines.wishlist.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.wishlist.tag_applier.record_writeback",
        ):
            apply_wishlist_tags(
                [_entry(pid="p1", count=5)],
                [_product("p1")],
            )
        params = router.execute.call_args.args[1]
        assert "wishlist:high_demand" in params["tags"]
        assert "wishlist:top_tier" not in params["tags"]

    def test_top_tier_added_above_threshold(self):
        router = _ok_router("p1")
        with patch(
            "engines.wishlist.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.wishlist.tag_applier.record_writeback",
        ):
            apply_wishlist_tags(
                [_entry(pid="p1", count=15)],
                [_product("p1")],
            )
        params = router.execute.call_args.args[1]
        assert "wishlist:high_demand" in params["tags"]
        assert "wishlist:top_tier" in params["tags"]

    def test_existing_tags_preserved(self):
        router = _ok_router("p1")
        with patch(
            "engines.wishlist.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.wishlist.tag_applier.record_writeback",
        ):
            apply_wishlist_tags(
                [_entry(pid="p1", count=5)],
                [_product("p1", tags=["existing"])],
            )
        params = router.execute.call_args.args[1]
        assert "existing" in params["tags"]
        assert "wishlist:high_demand" in params["tags"]


class TestPatternZ:

    def test_success_records(self):
        with patch(
            "engines.wishlist.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.wishlist.tag_applier.record_writeback",
        ) as record_mock:
            apply_wishlist_tags(
                [_entry(pid="p1", count=15)],
                [_product("p1")],
            )
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "wishlist"
        assert kw["action_type"] == "apply_wishlist_tags"
        assert kw["success"] is True


class TestFlowOptIn:

    def _seed(self, *, apply_tags=False):
        return {
            "status": "success",
            "data": {
                "wishlists": [
                    {"customer_id": f"c{i}", "items": ["p1", "p2"]}
                    for i in range(5)
                ],
                "products": [
                    {"id": "p1", "title": "Widget", "price": 100, "tags": []},
                    {"id": "p2", "title": "Gadget", "price": 50, "tags": []},
                ],
                "customers": [{"id": f"c{i}"} for i in range(5)],
                "apply_wishlist_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.wishlist.flow import WishlistEngine
        with patch(
            "engines.wishlist.tag_applier.apply_wishlist_tags",
        ) as apply_mock:
            result = WishlistEngine().run(self._seed(apply_tags=False))
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_wishlist"] == []

    def test_opt_in_invokes_applier(self):
        from engines.wishlist.flow import WishlistEngine
        with patch(
            "engines.wishlist.tag_applier.apply_wishlist_tags",
            return_value=[
                {
                    "product_id": "p1", "applied": True,
                    "tags_added": 1, "merged_tags": [],
                    "wishlist_count": 5, "error": None,
                },
            ],
        ) as apply_mock:
            result = WishlistEngine().run(self._seed(apply_tags=True))
        apply_mock.assert_called_once()
        assert result["data"]["tagged_wishlist"]

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.wishlist.flow import WishlistEngine
        with patch(
            "engines.wishlist.tag_applier.apply_wishlist_tags",
            side_effect=RuntimeError("boom"),
        ):
            result = WishlistEngine().run(self._seed(apply_tags=True))
        assert result["status"] == "success"
        assert result["data"]["tagged_wishlist"] == []
