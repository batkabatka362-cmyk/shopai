"""Tests for ``engines.wishlist.tag_applier``.

Pushes ``shopai-wishlisted-hot`` tags on each top-wishlisted
product via SHOPIFY_ADD_TAGS. Two paths (queue / direct)
selected by ``require_approval``.

Coverage:
  1. Input filtering (empty / non-list / non-dict / missing
     product_id / count below threshold / duplicate dedup /
     bad count coerced to 0).
  2. Direct path: SHOPIFY_ADD_TAGS called per top product;
     router unavailable, adapter failure, raise all handled.
  3. Queue path: each top product enqueues with correct
     params; queue unavailable; per-enqueue raise doesn't
     abort.
  4. Pattern Z: record_writeback fires on every outcome.
  5. Flow integration: default off / opt-in calls applier /
     require_approval propagates / min_wishlist_count flows.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from engines.wishlist.tag_applier import (
    apply_wishlist_tags,
)


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue
    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


def _ok(data=None):
    return SimpleNamespace(ok=True, data=data or {}, error=None)


def _fail(err="rejected"):
    return SimpleNamespace(ok=False, data=None, error=err)


def _entry(*, pid="gid://shopify/Product/1", title="Item", count=5):
    return {
        "product_id": pid,
        "title": title,
        "wishlist_count": count,
        "price": 25.0,
    }


# ─── Input filtering ──────────────────────────────────────────


class TestInputFiltering:

    def test_empty_input(self, isolated_queue):
        assert apply_wishlist_tags([]) == []

    def test_non_list_input(self, isolated_queue):
        assert apply_wishlist_tags(None) == []  # type: ignore

    def test_non_dict_entry_skipped(self, isolated_queue):
        results = apply_wishlist_tags(
            ["not a dict", 42, _entry(pid="gid://p/2")],  # type: ignore
        )
        assert len(results) == 1

    def test_missing_product_id_skipped(self, isolated_queue):
        results = apply_wishlist_tags(
            [_entry(pid="")],
        )
        assert results == []

    def test_below_threshold_skipped(self, isolated_queue):
        # Default threshold is 3; an entry with count=2 should
        # be filtered out.
        results = apply_wishlist_tags(
            [_entry(count=2)],
        )
        assert results == []

    def test_custom_threshold(self, isolated_queue):
        results = apply_wishlist_tags(
            [
                _entry(pid="gid://p/1", count=5),
                _entry(pid="gid://p/2", count=15),
            ],
            min_wishlist_count=10,
        )
        assert len(results) == 1
        assert results[0]["product_id"] == "gid://p/2"

    def test_duplicate_product_ids_deduped(self, isolated_queue):
        results = apply_wishlist_tags(
            [
                _entry(pid="gid://p/1", count=5),
                _entry(pid="gid://p/1", count=8),  # dup
                _entry(pid="gid://p/2", count=4),
            ],
        )
        assert len(results) == 2
        pids = {r["product_id"] for r in results}
        assert pids == {"gid://p/1", "gid://p/2"}

    def test_bad_count_treated_as_zero(self, isolated_queue):
        # "many" can't be coerced to int — treat as 0 (below
        # threshold), skip.
        results = apply_wishlist_tags(
            [{"product_id": "gid://p/1", "wishlist_count": "many"}],
        )
        assert results == []


# ─── Direct path ──────────────────────────────────────────────


class TestDirectPath:

    def _run_direct(self, entries, **kwargs):
        captured = {}

        def _exec(cap, params):
            captured.setdefault("calls", []).append({
                "cap": cap, "params": params,
            })
            return _ok()

        router = SimpleNamespace(execute=_exec)
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_wishlist_tags(
                entries, require_approval=False, **kwargs,
            )
        return results, captured

    def test_each_top_product_tagged(self):
        results, captured = self._run_direct([
            _entry(pid="gid://p/1", title="Hat", count=10),
            _entry(pid="gid://p/2", title="Mug", count=5),
        ])
        assert all(r["applied"] for r in results)
        assert len(results) == 2
        for r in results:
            assert r["tag"] == "shopai-wishlisted-hot"
        assert len(captured["calls"]) == 2
        assert captured["calls"][0]["cap"].name == "SHOPIFY_ADD_TAGS"
        assert captured["calls"][0]["params"]["id"] == "gid://p/1"
        assert captured["calls"][0]["params"]["tags"] == [
            "shopai-wishlisted-hot",
        ]

    def test_router_unavailable_per_product_error(self):
        with patch(
            "core.adapters.get_router", return_value=None,
        ):
            results = apply_wishlist_tags(
                [_entry()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert results[0]["error"] == "router_unavailable"

    def test_adapter_failure_per_product_error(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_wishlist_tags(
                [_entry()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "rate_limited" in results[0]["error"]

    def test_adapter_raise_per_product_error(self):
        def _raises(c, p):
            raise RuntimeError("boom")
        router = SimpleNamespace(execute=_raises)
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_wishlist_tags(
                [_entry()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "adapter_raised" in results[0]["error"]

    def test_batch_continues_through_failure(self):
        call_count = {"n": 0}

        def _exec(c, p):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("transient")
            return _ok()

        router = SimpleNamespace(execute=_exec)
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_wishlist_tags(
                [
                    _entry(pid="gid://p/1"),
                    _entry(pid="gid://p/2"),
                    _entry(pid="gid://p/3"),
                ],
                require_approval=False,
            )
        assert len(results) == 3
        assert results[0]["applied"] is True
        assert results[1]["applied"] is False
        assert results[2]["applied"] is True


# ─── Queue path ──────────────────────────────────────────────


class TestQueuePath:

    def test_each_top_product_enqueues(self, isolated_queue):
        results = apply_wishlist_tags([
            _entry(pid="gid://p/1", title="Hat", count=10),
            _entry(pid="gid://p/2", title="Mug", count=5),
        ])
        assert len(results) == 2
        assert all("pending_action_id" in r for r in results)
        assert all(r["applied"] is False for r in results)
        action = isolated_queue.get(
            results[0]["pending_action_id"],
        )
        assert action.params["product_id"] == "gid://p/1"
        assert action.params["tag"] == "shopai-wishlisted-hot"
        assert action.params["title"] == "Hat"
        assert action.params["wishlist_count"] == 10
        assert action.action_type == "tag_wishlisted_hot"
        assert action.capability == "SHOPIFY_ADD_TAGS"

    def test_queue_unavailable_per_product_error(self):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            results = apply_wishlist_tags([_entry()])
        assert results[0]["applied"] is False
        assert results[0]["error"] == "approval_queue_unavailable"

    def test_enqueue_raise_per_product(self, isolated_queue):
        original = isolated_queue.enqueue
        call_count = {"n": 0}

        def _enqueue(**kw):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("boom")
            return original(**kw)

        isolated_queue.enqueue = _enqueue
        results = apply_wishlist_tags([
            _entry(pid="gid://p/1"),
            _entry(pid="gid://p/2"),
            _entry(pid="gid://p/3"),
        ])
        assert "pending_action_id" in results[0]
        assert "enqueue_raised" in results[1]["error"]
        assert "pending_action_id" in results[2]


# ─── Pattern Z ───────────────────────────────────────────────


class TestRecordWritebackIntegration:

    def test_record_called_on_direct_success(self):
        router = SimpleNamespace(execute=lambda c, p: _ok())
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.wishlist.tag_applier.record_writeback",
        ) as record_mock:
            apply_wishlist_tags(
                [_entry()], require_approval=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "wishlist"
        assert kwargs["capability"] == "SHOPIFY_ADD_TAGS"
        assert kwargs["success"] is True

    def test_record_called_on_direct_failure(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.wishlist.tag_applier.record_writeback",
        ) as record_mock:
            apply_wishlist_tags(
                [_entry()], require_approval=False,
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False

    def test_record_called_on_queue_enqueue(self, isolated_queue):
        with patch(
            "engines.wishlist.tag_applier.record_writeback",
        ) as record_mock:
            apply_wishlist_tags([_entry()])
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True


# ─── Flow integration ────────────────────────────────────────


class TestFlowIntegration:

    def _input(
        self, *, apply=False, require_approval=None,
        min_count=None,
    ):
        data = {
            "wishlists": [
                {"customer_id": "gid://c/1",
                 "items": [{"product_id": "gid://p/1"}]},
                {"customer_id": "gid://c/2",
                 "items": [{"product_id": "gid://p/1"}]},
                {"customer_id": "gid://c/3",
                 "items": [{"product_id": "gid://p/1"}]},
            ],
            "products": [
                {"id": "gid://p/1", "title": "Hat", "price": 25.0},
            ],
            "customers": [],
        }
        if apply:
            data["apply_wishlist_tags"] = True
        if require_approval is not None:
            data["require_approval"] = require_approval
        if min_count is not None:
            data["min_wishlist_count"] = min_count
        return {
            "status": "success",
            "data": data,
            "meta": {},
            "error": None,
        }

    def test_default_off_keeps_tag_results_empty(
        self, isolated_queue,
    ):
        from engines.wishlist.flow import WishlistEngine
        with patch(
            "engines.wishlist.tag_applier.apply_wishlist_tags",
        ) as applier_mock:
            result = WishlistEngine().run(self._input())
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []

    def test_opt_in_calls_applier(self, isolated_queue):
        from engines.wishlist.flow import WishlistEngine
        with patch(
            "engines.wishlist.tag_applier.apply_wishlist_tags",
            return_value=[
                {"product_id": "gid://p/1",
                 "title": "Hat",
                 "wishlist_count": 3,
                 "tag": "shopai-wishlisted-hot",
                 "applied": True, "error": None},
            ],
        ) as applier_mock:
            result = WishlistEngine().run(self._input(apply=True))
        applier_mock.assert_called_once()
        # Default require_approval=True propagates
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is True
        # Default min_wishlist_count=3 propagates
        assert kwargs["min_wishlist_count"] == 3
        assert len(result["data"]["tag_results"]) == 1

    def test_explicit_require_approval_false_propagates(
        self, isolated_queue,
    ):
        from engines.wishlist.flow import WishlistEngine
        with patch(
            "engines.wishlist.tag_applier.apply_wishlist_tags",
            return_value=[],
        ) as applier_mock:
            WishlistEngine().run(
                self._input(apply=True, require_approval=False),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is False

    def test_min_wishlist_count_propagates(self, isolated_queue):
        from engines.wishlist.flow import WishlistEngine
        with patch(
            "engines.wishlist.tag_applier.apply_wishlist_tags",
            return_value=[],
        ) as applier_mock:
            WishlistEngine().run(
                self._input(apply=True, min_count=10),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["min_wishlist_count"] == 10
