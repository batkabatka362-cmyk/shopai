"""Tests for ``engines.product_scoring.tag_applier``.

Pushes ``shopai-tier-{A|B}`` tags on top-tier products via
SHOPIFY_ADD_TAGS. Two paths (queue / direct) selected by
``require_approval``.

Coverage:
  1. Input filtering (empty / non-list / non-dict / missing
     id / "unknown" literal / non-A tier default / B gated /
     best-tier dedup / case-insensitive tier).
  2. Direct path: SHOPIFY_ADD_TAGS called per top-tier
     product; router unavailable, adapter failure, raise all
     handled.
  3. Queue path: each top-tier product enqueues with correct
     params; queue unavailable; per-enqueue raise doesn't
     abort.
  4. Pattern Z: record_writeback fires on every outcome.
  5. Flow integration: default off / opt-in calls applier /
     require_approval / include_b propagate.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from engines.product_scoring.tag_applier import (
    apply_scoring_tags,
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


def _scored(
    *,
    pid="gid://shopify/Product/1",
    tier="A",
    score=8.0,
    title="P1",
):
    return {
        "id": pid,
        "title": title,
        "composite_score": score,
        "demand_score": 8.0,
        "margin_score": 8.0,
        "competition_score": 8.0,
        "tier": tier,
    }


# ─── Input filtering ──────────────────────────────────────────


class TestInputFiltering:

    def test_empty_input(self, isolated_queue):
        assert apply_scoring_tags([]) == []

    def test_non_list_input(self, isolated_queue):
        assert apply_scoring_tags(None) == []  # type: ignore

    def test_non_dict_entry_skipped(self, isolated_queue):
        results = apply_scoring_tags(
            ["bad", 42, _scored(pid="gid://p/2")],  # type: ignore
        )
        assert len(results) == 1

    def test_missing_id_skipped(self, isolated_queue):
        results = apply_scoring_tags(
            [_scored(pid="")],
        )
        assert results == []

    def test_unknown_id_skipped(self, isolated_queue):
        # The engine uses "unknown" as a default — not a real
        # product, don't tag.
        results = apply_scoring_tags(
            [_scored(pid="unknown")],
        )
        assert results == []

    def test_only_a_tagged_by_default(self, isolated_queue):
        results = apply_scoring_tags(
            [
                _scored(pid="gid://p/1", tier="A"),
                _scored(pid="gid://p/2", tier="B"),
                _scored(pid="gid://p/3", tier="C"),
                _scored(pid="gid://p/4", tier="D"),
            ],
        )
        assert len(results) == 1
        assert results[0]["tier"] == "A"
        assert results[0]["tag"] == "shopai-tier-A"

    def test_include_b_opts_in(self, isolated_queue):
        results = apply_scoring_tags(
            [
                _scored(pid="gid://p/1", tier="A"),
                _scored(pid="gid://p/2", tier="B"),
                _scored(pid="gid://p/3", tier="C"),
            ],
            include_b=True,
        )
        assert len(results) == 2
        tiers = {r["tier"] for r in results}
        assert tiers == {"A", "B"}

    def test_dedup_keeps_best_tier(self, isolated_queue):
        # Same product appears twice; A wins over B.
        results = apply_scoring_tags(
            [
                _scored(pid="gid://p/1", tier="B"),
                _scored(pid="gid://p/1", tier="A"),
            ],
            include_b=True,
        )
        assert len(results) == 1
        assert results[0]["tier"] == "A"

    def test_case_insensitive_tier(self, isolated_queue):
        # The engine emits uppercase but tolerate any case.
        results = apply_scoring_tags(
            [
                _scored(pid="gid://p/1", tier="a"),
                _scored(pid="gid://p/2", tier="A"),
            ],
        )
        assert len(results) == 2

    def test_bad_composite_score_coerced_to_zero(
        self, isolated_queue,
    ):
        results = apply_scoring_tags(
            [{
                "id": "gid://p/1",
                "tier": "A",
                "composite_score": "very high",
            }],
        )
        assert len(results) == 1
        assert results[0]["composite_score"] == 0.0


# ─── Direct path ──────────────────────────────────────────────


class TestDirectPath:

    def _run_direct(self, scored, **kwargs):
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
            results = apply_scoring_tags(
                scored, require_approval=False, **kwargs,
            )
        return results, captured

    def test_a_tier_product_tagged(self):
        results, captured = self._run_direct([_scored()])
        assert results[0]["applied"] is True
        assert results[0]["tag"] == "shopai-tier-A"
        assert captured["calls"][0]["cap"].name == "SHOPIFY_ADD_TAGS"
        assert captured["calls"][0]["params"]["id"] == (
            "gid://shopify/Product/1"
        )

    def test_router_unavailable_per_product_error(self):
        with patch(
            "core.adapters.get_router", return_value=None,
        ):
            results = apply_scoring_tags(
                [_scored()], require_approval=False,
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
            results = apply_scoring_tags(
                [_scored()], require_approval=False,
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
            results = apply_scoring_tags(
                [_scored()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "adapter_raised" in results[0]["error"]


# ─── Queue path ──────────────────────────────────────────────


class TestQueuePath:

    def test_a_tier_product_enqueues(self, isolated_queue):
        results = apply_scoring_tags([
            _scored(pid="gid://p/1", tier="A", score=8.5,
                    title="Hero"),
        ])
        assert len(results) == 1
        assert "pending_action_id" in results[0]
        assert results[0]["applied"] is False
        action = isolated_queue.get(
            results[0]["pending_action_id"],
        )
        assert action.params["product_id"] == "gid://p/1"
        assert action.params["tag"] == "shopai-tier-A"
        assert action.params["tier"] == "A"
        assert action.params["composite_score"] == 8.5
        assert action.params["title"] == "Hero"
        assert action.action_type == "tag_product_tier"
        assert action.capability == "SHOPIFY_ADD_TAGS"

    def test_queue_unavailable_per_product_error(self):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            results = apply_scoring_tags([_scored()])
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
        results = apply_scoring_tags([
            _scored(pid="gid://p/1"),
            _scored(pid="gid://p/2"),
            _scored(pid="gid://p/3"),
        ])
        failed = [
            r for r in results
            if r.get("error") and "enqueue_raised" in r["error"]
        ]
        assert len(failed) == 1


# ─── Pattern Z ───────────────────────────────────────────────


class TestRecordWritebackIntegration:

    def test_record_called_on_direct_success(self):
        router = SimpleNamespace(execute=lambda c, p: _ok())
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.product_scoring.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_scoring_tags(
                [_scored()], require_approval=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "product_scoring"
        assert kwargs["capability"] == "SHOPIFY_ADD_TAGS"
        assert kwargs["success"] is True

    def test_record_called_on_direct_failure(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.product_scoring.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_scoring_tags(
                [_scored()], require_approval=False,
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False

    def test_record_called_on_queue_enqueue(self, isolated_queue):
        with patch(
            "engines.product_scoring.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_scoring_tags([_scored()])
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True


# ─── Flow integration ────────────────────────────────────────


class TestFlowIntegration:

    def _input(
        self, *, apply=False, require_approval=None,
        include_b=None,
    ):
        # Two products with strong demand/margin/competition
        # signals → likely A-tier; the applier mock returns
        # canned data anyway.
        data = {
            "products": [
                {
                    "id": "gid://p/1",
                    "title": "Top",
                    "monthly_sales": 1000,
                    "avg_margin_pct": 60.0,
                    "competition_score": 0.2,
                },
            ],
            "criteria": {},
        }
        if apply:
            data["apply_scoring_tags"] = True
        if require_approval is not None:
            data["require_approval"] = require_approval
        if include_b is not None:
            data["include_b"] = include_b
        return {
            "status": "success",
            "data": data,
            "meta": {},
            "error": None,
        }

    def test_default_off_keeps_tag_results_empty(
        self, isolated_queue,
    ):
        from engines.product_scoring.flow import (
            ProductScoringEngine,
        )
        with patch(
            "engines.product_scoring.tag_applier."
            "apply_scoring_tags",
        ) as applier_mock:
            result = ProductScoringEngine().run(self._input())
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []

    def test_opt_in_calls_applier(self, isolated_queue):
        from engines.product_scoring.flow import (
            ProductScoringEngine,
        )
        with patch(
            "engines.product_scoring.tag_applier."
            "apply_scoring_tags",
            return_value=[
                {"product_id": "gid://p/1",
                 "tier": "A",
                 "composite_score": 8.0,
                 "tag": "shopai-tier-A",
                 "applied": True, "error": None},
            ],
        ) as applier_mock:
            result = ProductScoringEngine().run(
                self._input(apply=True),
            )
        applier_mock.assert_called_once()
        kwargs = applier_mock.call_args.kwargs
        # Defaults propagate
        assert kwargs["require_approval"] is True
        assert kwargs["include_b"] is False
        assert len(result["data"]["tag_results"]) == 1

    def test_explicit_require_approval_false_propagates(
        self, isolated_queue,
    ):
        from engines.product_scoring.flow import (
            ProductScoringEngine,
        )
        with patch(
            "engines.product_scoring.tag_applier."
            "apply_scoring_tags",
            return_value=[],
        ) as applier_mock:
            ProductScoringEngine().run(
                self._input(apply=True, require_approval=False),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is False

    def test_include_b_propagates(self, isolated_queue):
        from engines.product_scoring.flow import (
            ProductScoringEngine,
        )
        with patch(
            "engines.product_scoring.tag_applier."
            "apply_scoring_tags",
            return_value=[],
        ) as applier_mock:
            ProductScoringEngine().run(
                self._input(apply=True, include_b=True),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["include_b"] is True
