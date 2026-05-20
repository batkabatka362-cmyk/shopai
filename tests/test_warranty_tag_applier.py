"""Tests for ``engines.warranty.tag_applier``.

Pushes ``shopai-warranty-high-risk`` tags on high-warranty-risk
products via SHOPIFY_ADD_TAGS. Two paths (queue / direct)
selected by ``require_approval``.

Coverage:
  1. Input filtering (empty / non-list / non-dict / missing
     product_id / non-high level skipped / case-insensitive
     level / dedup / bad numerics coerced).
  2. Direct path: SHOPIFY_ADD_TAGS called per high-risk product;
     router unavailable, adapter failure, raise all handled.
  3. Queue path: each high-risk product enqueues with correct
     params; queue unavailable; per-enqueue raise doesn't abort.
  4. Pattern Z: record_writeback fires on every outcome.
  5. Flow integration: default off / opt-in calls applier /
     require_approval propagates.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from engines.warranty.tag_applier import (
    apply_warranty_tags,
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


def _risk(
    *,
    pid="gid://shopify/Product/1",
    level="high",
    claims=5,
    score=0.7,
):
    return {
        "product_id": pid,
        "claim_count": claims,
        "total_cost": 250.0,
        "risk_score": score,
        "risk_level": level,
    }


# ─── Input filtering ──────────────────────────────────────────


class TestInputFiltering:

    def test_empty_input(self, isolated_queue):
        assert apply_warranty_tags([]) == []

    def test_non_list_input(self, isolated_queue):
        assert apply_warranty_tags(None) == []  # type: ignore

    def test_non_dict_entry_skipped(self, isolated_queue):
        results = apply_warranty_tags(
            ["bad", 42, _risk(pid="gid://p/2")],  # type: ignore
        )
        assert len(results) == 1

    def test_missing_product_id_skipped(self, isolated_queue):
        results = apply_warranty_tags(
            [_risk(pid="")],
        )
        assert results == []

    def test_only_high_tagged(self, isolated_queue):
        results = apply_warranty_tags(
            [
                _risk(pid="gid://p/1", level="high"),
                _risk(pid="gid://p/2", level="medium"),
                _risk(pid="gid://p/3", level="low"),
            ],
        )
        assert len(results) == 1
        assert results[0]["product_id"] == "gid://p/1"
        assert results[0]["tag"] == "shopai-warranty-high-risk"

    def test_case_insensitive_level(self, isolated_queue):
        results = apply_warranty_tags(
            [
                _risk(pid="gid://p/1", level="HIGH"),
                _risk(pid="gid://p/2", level="High"),
            ],
        )
        assert len(results) == 2

    def test_dedup_last_seen_wins(self, isolated_queue):
        # Same product appears twice; last-seen wins.
        results = apply_warranty_tags(
            [
                _risk(pid="gid://p/1", claims=3),
                _risk(pid="gid://p/1", claims=10),  # dup, later
            ],
        )
        assert len(results) == 1
        assert results[0]["claim_count"] == 10

    def test_bad_numerics_coerced_to_zero(self, isolated_queue):
        results = apply_warranty_tags(
            [{
                "product_id": "gid://p/1",
                "risk_level": "high",
                "claim_count": "many",
                "risk_score": "very",
            }],
        )
        assert len(results) == 1
        assert results[0]["claim_count"] == 0
        assert results[0]["risk_score"] == 0.0


# ─── Direct path ──────────────────────────────────────────────


class TestDirectPath:

    def _run_direct(self, risks, **kwargs):
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
            results = apply_warranty_tags(
                risks, require_approval=False, **kwargs,
            )
        return results, captured

    def test_high_risk_product_tagged(self):
        results, captured = self._run_direct([_risk()])
        assert results[0]["applied"] is True
        assert results[0]["tag"] == "shopai-warranty-high-risk"
        assert captured["calls"][0]["cap"].name == "SHOPIFY_ADD_TAGS"
        assert captured["calls"][0]["params"]["id"] == (
            "gid://shopify/Product/1"
        )

    def test_router_unavailable_per_product_error(self):
        with patch(
            "core.adapters.get_router", return_value=None,
        ):
            results = apply_warranty_tags(
                [_risk()], require_approval=False,
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
            results = apply_warranty_tags(
                [_risk()], require_approval=False,
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
            results = apply_warranty_tags(
                [_risk()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "adapter_raised" in results[0]["error"]


# ─── Queue path ──────────────────────────────────────────────


class TestQueuePath:

    def test_high_risk_product_enqueues(self, isolated_queue):
        results = apply_warranty_tags([
            _risk(pid="gid://p/1", claims=8, score=0.75),
        ])
        assert len(results) == 1
        assert "pending_action_id" in results[0]
        assert results[0]["applied"] is False
        action = isolated_queue.get(
            results[0]["pending_action_id"],
        )
        assert action.params["product_id"] == "gid://p/1"
        assert action.params["tag"] == "shopai-warranty-high-risk"
        assert action.params["claim_count"] == 8
        assert action.params["risk_score"] == 0.75
        assert action.action_type == "tag_warranty_risk"
        assert action.capability == "SHOPIFY_ADD_TAGS"

    def test_queue_unavailable_per_product_error(self):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            results = apply_warranty_tags([_risk()])
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
        results = apply_warranty_tags([
            _risk(pid="gid://p/1"),
            _risk(pid="gid://p/2"),
            _risk(pid="gid://p/3"),
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
            "engines.warranty.tag_applier.record_writeback",
        ) as record_mock:
            apply_warranty_tags(
                [_risk()], require_approval=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "warranty"
        assert kwargs["capability"] == "SHOPIFY_ADD_TAGS"
        assert kwargs["success"] is True

    def test_record_called_on_direct_failure(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.warranty.tag_applier.record_writeback",
        ) as record_mock:
            apply_warranty_tags(
                [_risk()], require_approval=False,
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False

    def test_record_called_on_queue_enqueue(self, isolated_queue):
        with patch(
            "engines.warranty.tag_applier.record_writeback",
        ) as record_mock:
            apply_warranty_tags([_risk()])
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True


# ─── Flow integration ────────────────────────────────────────


class TestFlowIntegration:

    def _input(
        self, *, apply=False, require_approval=None,
    ):
        # Build a product + many claims to force a high
        # warranty risk classification.
        data = {
            "products": [
                {"id": "gid://p/1", "title": "Defective gadget",
                 "price": 50.0},
            ],
            "claims": [
                {"product_id": "gid://p/1", "cost": 50.0,
                 "date": "2026-04-01"},
                {"product_id": "gid://p/1", "cost": 50.0,
                 "date": "2026-04-15"},
                {"product_id": "gid://p/1", "cost": 50.0,
                 "date": "2026-05-01"},
                {"product_id": "gid://p/1", "cost": 50.0,
                 "date": "2026-05-15"},
                {"product_id": "gid://p/1", "cost": 50.0,
                 "date": "2026-05-20"},
            ],
            "policies": [],
        }
        if apply:
            data["apply_warranty_tags"] = True
        if require_approval is not None:
            data["require_approval"] = require_approval
        return {
            "status": "success",
            "data": data,
            "meta": {},
            "error": None,
        }

    def test_default_off_keeps_tag_results_empty(
        self, isolated_queue,
    ):
        from engines.warranty.flow import WarrantyEngine
        with patch(
            "engines.warranty.tag_applier.apply_warranty_tags",
        ) as applier_mock:
            result = WarrantyEngine().run(self._input())
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []

    def test_opt_in_calls_applier(self, isolated_queue):
        from engines.warranty.flow import WarrantyEngine
        with patch(
            "engines.warranty.tag_applier.apply_warranty_tags",
            return_value=[
                {"product_id": "gid://p/1",
                 "claim_count": 5, "risk_score": 0.7,
                 "tag": "shopai-warranty-high-risk",
                 "applied": True, "error": None},
            ],
        ) as applier_mock:
            result = WarrantyEngine().run(self._input(apply=True))
        applier_mock.assert_called_once()
        kwargs = applier_mock.call_args.kwargs
        # Default require_approval=True propagates
        assert kwargs["require_approval"] is True
        assert len(result["data"]["tag_results"]) == 1

    def test_explicit_require_approval_false_propagates(
        self, isolated_queue,
    ):
        from engines.warranty.flow import WarrantyEngine
        with patch(
            "engines.warranty.tag_applier.apply_warranty_tags",
            return_value=[],
        ) as applier_mock:
            WarrantyEngine().run(
                self._input(apply=True, require_approval=False),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is False
