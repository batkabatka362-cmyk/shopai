"""Tests for ``engines.product_ranking.tag_applier``.

Pushes ``shopai-rank-top`` tags on each top-N ranked product
via SHOPIFY_ADD_TAGS. Two paths (queue / direct) selected by
``require_approval``.

Coverage:
  1. Input filtering (empty / non-list / non-dict / missing
     product_id / missing or bad rank / out-of-window rank /
     duplicate product_ids deduped / custom top_n).
  2. Direct path: SHOPIFY_ADD_TAGS called per top product;
     router unavailable, adapter failure, raise all handled.
  3. Queue path: each top product enqueues with correct
     params; queue unavailable; per-enqueue raise doesn't
     abort.
  4. Pattern Z: record_writeback fires on every outcome.
  5. Flow integration: default off / opt-in calls applier /
     require_approval / top_n propagate.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from engines.product_ranking.tag_applier import (
    apply_ranking_tags,
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


def _ranked(*, pid="gid://shopify/Product/1", title="P1", rank=1):
    return {
        "product_id": pid,
        "title": title,
        "rank": rank,
        "final_score": 100 - rank * 5,
    }


# ─── Input filtering ──────────────────────────────────────────


class TestInputFiltering:

    def test_empty_input(self, isolated_queue):
        assert apply_ranking_tags([]) == []

    def test_non_list_input(self, isolated_queue):
        assert apply_ranking_tags(None) == []  # type: ignore

    def test_non_dict_entry_skipped(self, isolated_queue):
        results = apply_ranking_tags(
            ["bad", 42, _ranked(pid="gid://p/2", rank=2)],  # type: ignore
        )
        assert len(results) == 1

    def test_missing_product_id_skipped(self, isolated_queue):
        results = apply_ranking_tags(
            [_ranked(pid="", rank=1)],
        )
        assert results == []

    def test_missing_rank_skipped(self, isolated_queue):
        results = apply_ranking_tags(
            [{"product_id": "gid://p/1", "title": "x"}],
        )
        assert results == []

    def test_non_integer_rank_skipped(self, isolated_queue):
        results = apply_ranking_tags(
            [{"product_id": "gid://p/1", "rank": "first"}],
        )
        assert results == []

    def test_outside_top_n_skipped(self, isolated_queue):
        # Default top_n=10; rank 15 should be filtered out.
        results = apply_ranking_tags(
            [
                _ranked(pid="gid://p/1", rank=15),
                _ranked(pid="gid://p/2", rank=8),  # in window
            ],
        )
        assert len(results) == 1
        assert results[0]["product_id"] == "gid://p/2"

    def test_custom_top_n(self, isolated_queue):
        results = apply_ranking_tags(
            [
                _ranked(pid="gid://p/1", rank=1),
                _ranked(pid="gid://p/2", rank=2),
                _ranked(pid="gid://p/3", rank=3),
                _ranked(pid="gid://p/4", rank=4),
            ],
            top_n=2,
        )
        assert len(results) == 2
        pids = {r["product_id"] for r in results}
        assert pids == {"gid://p/1", "gid://p/2"}

    def test_invalid_top_n_clamped_to_one(self, isolated_queue):
        # top_n=0 or negative clamps to 1
        results = apply_ranking_tags(
            [
                _ranked(pid="gid://p/1", rank=1),
                _ranked(pid="gid://p/2", rank=2),
            ],
            top_n=0,
        )
        assert len(results) == 1
        assert results[0]["product_id"] == "gid://p/1"

    def test_duplicate_product_ids_deduped(self, isolated_queue):
        results = apply_ranking_tags(
            [
                _ranked(pid="gid://p/1", rank=1),
                _ranked(pid="gid://p/1", rank=2),  # dup
                _ranked(pid="gid://p/2", rank=3),
            ],
        )
        assert len(results) == 2
        pids = {r["product_id"] for r in results}
        assert pids == {"gid://p/1", "gid://p/2"}

    def test_rank_below_one_skipped(self, isolated_queue):
        # rank=0 doesn't make sense (engine starts at 1)
        results = apply_ranking_tags(
            [_ranked(pid="gid://p/1", rank=0)],
        )
        assert results == []


# ─── Direct path ──────────────────────────────────────────────


class TestDirectPath:

    def _run_direct(self, ranked, **kwargs):
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
            results = apply_ranking_tags(
                ranked, require_approval=False, **kwargs,
            )
        return results, captured

    def test_each_top_product_tagged(self):
        results, captured = self._run_direct([
            _ranked(pid="gid://p/1", rank=1),
            _ranked(pid="gid://p/2", rank=5),
        ])
        assert all(r["applied"] for r in results)
        assert len(results) == 2
        for r in results:
            assert r["tag"] == "shopai-rank-top"
        assert len(captured["calls"]) == 2
        assert captured["calls"][0]["cap"].name == "SHOPIFY_ADD_TAGS"
        assert captured["calls"][0]["params"]["id"] == "gid://p/1"

    def test_router_unavailable_per_product_error(self):
        with patch(
            "core.adapters.get_router", return_value=None,
        ):
            results = apply_ranking_tags(
                [_ranked()], require_approval=False,
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
            results = apply_ranking_tags(
                [_ranked()], require_approval=False,
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
            results = apply_ranking_tags(
                [_ranked()], require_approval=False,
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
            results = apply_ranking_tags(
                [
                    _ranked(pid="gid://p/1", rank=1),
                    _ranked(pid="gid://p/2", rank=2),
                    _ranked(pid="gid://p/3", rank=3),
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
        results = apply_ranking_tags([
            _ranked(pid="gid://p/1", title="A", rank=1),
            _ranked(pid="gid://p/2", title="B", rank=2),
        ])
        assert len(results) == 2
        assert all("pending_action_id" in r for r in results)
        assert all(r["applied"] is False for r in results)
        action = isolated_queue.get(
            results[0]["pending_action_id"],
        )
        assert action.params["product_id"] == "gid://p/1"
        assert action.params["tag"] == "shopai-rank-top"
        assert action.params["rank"] == 1
        assert action.params["title"] == "A"
        assert action.action_type == "tag_ranking_top"
        assert action.capability == "SHOPIFY_ADD_TAGS"

    def test_queue_unavailable_per_product_error(self):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            results = apply_ranking_tags([_ranked()])
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
        results = apply_ranking_tags([
            _ranked(pid="gid://p/1", rank=1),
            _ranked(pid="gid://p/2", rank=2),
            _ranked(pid="gid://p/3", rank=3),
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
            "engines.product_ranking.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_ranking_tags(
                [_ranked()], require_approval=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "product_ranking"
        assert kwargs["capability"] == "SHOPIFY_ADD_TAGS"
        assert kwargs["success"] is True

    def test_record_called_on_direct_failure(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.product_ranking.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_ranking_tags(
                [_ranked()], require_approval=False,
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False

    def test_record_called_on_queue_enqueue(self, isolated_queue):
        with patch(
            "engines.product_ranking.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_ranking_tags([_ranked()])
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True


# ─── Flow integration ────────────────────────────────────────


class TestFlowIntegration:

    def _input(
        self, *, apply=False, require_approval=None,
        top_n=None,
    ):
        # Build 12 products so top-10 has spillover candidates.
        products = [
            {
                "product_id": f"gid://p/{i}",
                "title": f"Product {i}",
                "price": 10.0 + i,
                "stock": 5 + i,
                "rating": 3.5 + (i % 5) * 0.3,
                "sales": 100 - i * 5,
            }
            for i in range(1, 13)
        ]
        data = {
            "products": products,
            "criteria": {},
        }
        if apply:
            data["apply_ranking_tags"] = True
        if require_approval is not None:
            data["require_approval"] = require_approval
        if top_n is not None:
            data["top_n"] = top_n
        return {
            "status": "success",
            "data": data,
            "meta": {},
            "error": None,
        }

    def test_default_off_keeps_tag_results_empty(
        self, isolated_queue,
    ):
        from engines.product_ranking.flow import (
            ProductRankingEngine,
        )
        with patch(
            "engines.product_ranking.tag_applier."
            "apply_ranking_tags",
        ) as applier_mock:
            result = ProductRankingEngine().run(self._input())
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []

    def test_opt_in_calls_applier(self, isolated_queue):
        from engines.product_ranking.flow import (
            ProductRankingEngine,
        )
        with patch(
            "engines.product_ranking.tag_applier."
            "apply_ranking_tags",
            return_value=[
                {"product_id": "gid://p/1",
                 "title": "P1",
                 "rank": 1,
                 "tag": "shopai-rank-top",
                 "applied": True, "error": None},
            ],
        ) as applier_mock:
            result = ProductRankingEngine().run(
                self._input(apply=True),
            )
        applier_mock.assert_called_once()
        kwargs = applier_mock.call_args.kwargs
        # Defaults propagate
        assert kwargs["require_approval"] is True
        assert kwargs["top_n"] == 10
        assert len(result["data"]["tag_results"]) == 1

    def test_explicit_require_approval_false_propagates(
        self, isolated_queue,
    ):
        from engines.product_ranking.flow import (
            ProductRankingEngine,
        )
        with patch(
            "engines.product_ranking.tag_applier."
            "apply_ranking_tags",
            return_value=[],
        ) as applier_mock:
            ProductRankingEngine().run(
                self._input(apply=True, require_approval=False),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is False

    def test_top_n_propagates(self, isolated_queue):
        from engines.product_ranking.flow import (
            ProductRankingEngine,
        )
        with patch(
            "engines.product_ranking.tag_applier."
            "apply_ranking_tags",
            return_value=[],
        ) as applier_mock:
            ProductRankingEngine().run(
                self._input(apply=True, top_n=5),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["top_n"] == 5
