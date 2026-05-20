"""Tests for ``engines.nps_engine.tag_applier``.

Pushes ``shopai-nps-{bucket}`` tags on each NPS respondent via
SHOPIFY_TAG_CUSTOMER. Two paths (queue / direct) selected by
``require_approval``.

Coverage:
  1. Input filtering (empty / non-list / non-dict / missing
     customer_id / out-of-range score / non-int score /
     passives gated by include_passives / last-wins dedup).
  2. Direct path: SHOPIFY_TAG_CUSTOMER called per respondent;
     router unavailable, adapter failure, raise all handled.
  3. Queue path: each respondent enqueues with correct params;
     queue unavailable; per-enqueue raise doesn't abort.
  4. Pattern Z: record_writeback fires on every outcome.
  5. Flow integration: default off / opt-in calls applier /
     require_approval propagates / include_passives flows.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from engines.nps_engine.tag_applier import (
    apply_nps_tags,
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


def _resp(*, cid="gid://shopify/Customer/1", score=10):
    return {
        "customer_id": cid,
        "score": score,
        "comment": "great",
        "date": "2026-01-01",
        "segment": "default",
    }


# ─── Input filtering ──────────────────────────────────────────


class TestInputFiltering:

    def test_empty_input(self, isolated_queue):
        assert apply_nps_tags([]) == []

    def test_non_list_input(self, isolated_queue):
        assert apply_nps_tags(None) == []  # type: ignore

    def test_non_dict_response_skipped(self, isolated_queue):
        results = apply_nps_tags(
            ["bad", 42, _resp(cid="gid://c/1", score=10)],  # type: ignore
        )
        assert len(results) == 1

    def test_missing_customer_id_skipped(self, isolated_queue):
        results = apply_nps_tags(
            [_resp(cid="", score=10)],
        )
        assert results == []

    def test_out_of_range_score_skipped(self, isolated_queue):
        results = apply_nps_tags(
            [_resp(score=11), _resp(score=-1), _resp(score=10, cid="gid://c/2")],
        )
        assert len(results) == 1
        assert results[0]["customer_id"] == "gid://c/2"

    def test_non_int_score_skipped(self, isolated_queue):
        results = apply_nps_tags(
            [{"customer_id": "gid://c/1", "score": "high"}],
        )
        assert results == []

    def test_none_score_skipped(self, isolated_queue):
        results = apply_nps_tags(
            [{"customer_id": "gid://c/1", "score": None}],
        )
        assert results == []

    def test_passive_excluded_by_default(self, isolated_queue):
        # score 7 and 8 are passives — excluded by default
        results = apply_nps_tags(
            [
                _resp(cid="gid://c/1", score=7),
                _resp(cid="gid://c/2", score=8),
                _resp(cid="gid://c/3", score=10),  # promoter — kept
            ],
        )
        assert len(results) == 1
        assert results[0]["bucket"] == "promoter"

    def test_passive_included_when_opted_in(self, isolated_queue):
        results = apply_nps_tags(
            [_resp(cid="gid://c/1", score=7)],
            include_passives=True,
        )
        assert len(results) == 1
        assert results[0]["bucket"] == "passive"
        assert results[0]["tag"] == "shopai-nps-passive"

    def test_last_wins_dedup(self, isolated_queue):
        # Same customer re-surveyed with different scores;
        # last score (10, promoter) wins.
        results = apply_nps_tags(
            [
                _resp(cid="gid://c/1", score=3),  # detractor
                _resp(cid="gid://c/1", score=10),  # promoter (wins)
            ],
        )
        assert len(results) == 1
        assert results[0]["score"] == 10
        assert results[0]["bucket"] == "promoter"

    def test_correct_bucketing(self, isolated_queue):
        # Verify bucket math: 0-6 detractor, 7-8 passive,
        # 9-10 promoter (include passives so all visible).
        results = apply_nps_tags(
            [
                _resp(cid="gid://c/1", score=0),
                _resp(cid="gid://c/2", score=6),
                _resp(cid="gid://c/3", score=7),
                _resp(cid="gid://c/4", score=8),
                _resp(cid="gid://c/5", score=9),
                _resp(cid="gid://c/6", score=10),
            ],
            include_passives=True,
        )
        buckets = {r["customer_id"]: r["bucket"] for r in results}
        assert buckets["gid://c/1"] == "detractor"
        assert buckets["gid://c/2"] == "detractor"
        assert buckets["gid://c/3"] == "passive"
        assert buckets["gid://c/4"] == "passive"
        assert buckets["gid://c/5"] == "promoter"
        assert buckets["gid://c/6"] == "promoter"


# ─── Direct path ──────────────────────────────────────────────


class TestDirectPath:

    def _run_direct(self, responses, **kwargs):
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
            results = apply_nps_tags(
                responses, require_approval=False, **kwargs,
            )
        return results, captured

    def test_promoter_and_detractor_tagged(self):
        results, captured = self._run_direct([
            _resp(cid="gid://c/1", score=10),
            _resp(cid="gid://c/2", score=3),
        ])
        assert all(r["applied"] for r in results)
        assert len(results) == 2
        tags = sorted(r["tag"] for r in results)
        assert tags == [
            "shopai-nps-detractor",
            "shopai-nps-promoter",
        ]
        assert len(captured["calls"]) == 2
        assert captured["calls"][0]["cap"].name == "SHOPIFY_TAG_CUSTOMER"

    def test_router_unavailable_per_customer_error(self):
        with patch(
            "core.adapters.get_router", return_value=None,
        ):
            results = apply_nps_tags(
                [_resp()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert results[0]["error"] == "router_unavailable"

    def test_adapter_failure_per_customer_error(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_nps_tags(
                [_resp()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "rate_limited" in results[0]["error"]

    def test_adapter_raise_per_customer_error(self):
        def _raises(c, p):
            raise RuntimeError("boom")
        router = SimpleNamespace(execute=_raises)
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_nps_tags(
                [_resp()], require_approval=False,
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
            results = apply_nps_tags(
                [
                    _resp(cid="gid://c/1", score=10),
                    _resp(cid="gid://c/2", score=3),
                    _resp(cid="gid://c/3", score=10),
                ],
                require_approval=False,
            )
        assert len(results) == 3
        # Use bucket presence rather than order — proposals
        # come from a dict so iteration order is insertion
        # order but tests should not be coupled to that.
        applied = [r["applied"] for r in results]
        assert applied.count(True) == 2
        assert applied.count(False) == 1


# ─── Queue path ──────────────────────────────────────────────


class TestQueuePath:

    def test_each_response_enqueues(self, isolated_queue):
        results = apply_nps_tags([
            _resp(cid="gid://c/1", score=10),
            _resp(cid="gid://c/2", score=3),
        ])
        assert len(results) == 2
        assert all("pending_action_id" in r for r in results)
        assert all(r["applied"] is False for r in results)
        # Bucket propagates into params
        promoter_action = isolated_queue.get(
            next(r["pending_action_id"] for r in results if r["bucket"] == "promoter"),
        )
        assert promoter_action.params["bucket"] == "promoter"
        assert promoter_action.params["tag"] == "shopai-nps-promoter"
        assert promoter_action.action_type == "tag_nps_customer"
        assert promoter_action.capability == "SHOPIFY_TAG_CUSTOMER"

    def test_queue_unavailable_per_customer_error(self):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            results = apply_nps_tags([_resp()])
        assert results[0]["applied"] is False
        assert results[0]["error"] == "approval_queue_unavailable"

    def test_enqueue_raise_per_customer(self, isolated_queue):
        original = isolated_queue.enqueue
        call_count = {"n": 0}

        def _enqueue(**kw):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("boom")
            return original(**kw)

        isolated_queue.enqueue = _enqueue
        results = apply_nps_tags([
            _resp(cid="gid://c/1", score=10),
            _resp(cid="gid://c/2", score=3),
            _resp(cid="gid://c/3", score=10),
        ])
        outcomes = [
            ("pending_action_id" in r, r.get("error"))
            for r in results
        ]
        # Exactly 1 should have failed with enqueue_raised
        assert sum(
            1 for has_id, err in outcomes
            if not has_id and err and "enqueue_raised" in err
        ) == 1


# ─── Pattern Z ───────────────────────────────────────────────


class TestRecordWritebackIntegration:

    def test_record_called_on_direct_success(self):
        router = SimpleNamespace(execute=lambda c, p: _ok())
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.nps_engine.tag_applier.record_writeback",
        ) as record_mock:
            apply_nps_tags(
                [_resp()], require_approval=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "nps_engine"
        assert kwargs["capability"] == "SHOPIFY_TAG_CUSTOMER"
        assert kwargs["success"] is True

    def test_record_called_on_direct_failure(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.nps_engine.tag_applier.record_writeback",
        ) as record_mock:
            apply_nps_tags(
                [_resp()], require_approval=False,
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False

    def test_record_called_on_queue_enqueue(self, isolated_queue):
        with patch(
            "engines.nps_engine.tag_applier.record_writeback",
        ) as record_mock:
            apply_nps_tags([_resp()])
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True


# ─── Flow integration ────────────────────────────────────────


class TestFlowIntegration:

    def _input(
        self, *, apply=False, require_approval=None,
        include_passives=None,
    ):
        data = {
            "responses": [
                {"customer_id": "gid://shopify/Customer/1",
                 "score": 10,
                 "date": "2026-01-01"},
                {"customer_id": "gid://shopify/Customer/2",
                 "score": 3,
                 "date": "2026-01-01"},
            ],
            "segments": [],
        }
        if apply:
            data["apply_nps_tags"] = True
        if require_approval is not None:
            data["require_approval"] = require_approval
        if include_passives is not None:
            data["include_passives"] = include_passives
        return {
            "status": "success",
            "data": data,
            "meta": {},
            "error": None,
        }

    def test_default_off_keeps_tag_results_empty(
        self, isolated_queue,
    ):
        from engines.nps_engine.flow import NpsEngine
        with patch(
            "engines.nps_engine.tag_applier.apply_nps_tags",
        ) as applier_mock:
            result = NpsEngine().run(self._input())
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []

    def test_opt_in_calls_applier(self, isolated_queue):
        from engines.nps_engine.flow import NpsEngine
        with patch(
            "engines.nps_engine.tag_applier.apply_nps_tags",
            return_value=[
                {"customer_id": "gid://c/1",
                 "score": 10,
                 "bucket": "promoter",
                 "tag": "shopai-nps-promoter",
                 "applied": True, "error": None},
            ],
        ) as applier_mock:
            result = NpsEngine().run(self._input(apply=True))
        applier_mock.assert_called_once()
        kwargs = applier_mock.call_args.kwargs
        # Default require_approval=True propagates
        assert kwargs["require_approval"] is True
        # Default include_passives=False propagates
        assert kwargs["include_passives"] is False
        assert len(result["data"]["tag_results"]) == 1

    def test_explicit_require_approval_false_propagates(
        self, isolated_queue,
    ):
        from engines.nps_engine.flow import NpsEngine
        with patch(
            "engines.nps_engine.tag_applier.apply_nps_tags",
            return_value=[],
        ) as applier_mock:
            NpsEngine().run(
                self._input(apply=True, require_approval=False),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is False

    def test_include_passives_propagates(self, isolated_queue):
        from engines.nps_engine.flow import NpsEngine
        with patch(
            "engines.nps_engine.tag_applier.apply_nps_tags",
            return_value=[],
        ) as applier_mock:
            NpsEngine().run(
                self._input(apply=True, include_passives=True),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["include_passives"] is True
