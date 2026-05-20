"""Tests for ``engines.product_validation.tag_applier``.

Pushes ``shopai-validation-failed`` tags on failed-validation
products via SHOPIFY_ADD_TAGS. Two paths (queue / direct)
selected by ``require_approval``.

Coverage:
  1. Input filtering (empty / non-list / non-dict / missing id /
     "unknown" literal / passed=True skipped / worst-risk dedup /
     case-insensitive level).
  2. Direct path: SHOPIFY_ADD_TAGS called per failed product;
     router unavailable, adapter failure, raise all handled.
  3. Queue path: each failed product enqueues with correct
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

from engines.product_validation.tag_applier import (
    apply_validation_tags,
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


def _validated(
    *,
    pid="gid://shopify/Product/1",
    risk_level="high",
    passed=False,
    recommendation="reject",
):
    return {
        "id": pid,
        "title": "P1",
        "risk_level": risk_level,
        "recommendation": recommendation,
        "passed": passed,
    }


# ─── Input filtering ──────────────────────────────────────────


class TestInputFiltering:

    def test_empty_input(self, isolated_queue):
        assert apply_validation_tags([]) == []

    def test_non_list_input(self, isolated_queue):
        assert apply_validation_tags(None) == []  # type: ignore

    def test_non_dict_entry_skipped(self, isolated_queue):
        results = apply_validation_tags(
            ["bad", 42, _validated(pid="gid://p/2")],  # type: ignore
        )
        assert len(results) == 1

    def test_missing_id_skipped(self, isolated_queue):
        results = apply_validation_tags(
            [_validated(pid="")],
        )
        assert results == []

    def test_unknown_id_skipped(self, isolated_queue):
        results = apply_validation_tags(
            [_validated(pid="unknown")],
        )
        assert results == []

    def test_passed_products_skipped(self, isolated_queue):
        results = apply_validation_tags(
            [
                _validated(pid="gid://p/1", passed=True),
                _validated(pid="gid://p/2", passed=False),
            ],
        )
        assert len(results) == 1
        assert results[0]["product_id"] == "gid://p/2"

    def test_dedup_keeps_worst_risk(self, isolated_queue):
        # Same product appears twice (defensive); critical
        # wins over high.
        results = apply_validation_tags(
            [
                _validated(pid="gid://p/1", risk_level="high",
                           passed=False),
                _validated(pid="gid://p/1", risk_level="critical",
                           passed=False),
            ],
        )
        assert len(results) == 1
        assert results[0]["risk_level"] == "critical"

    def test_case_insensitive_risk_level(self, isolated_queue):
        # The engine emits lowercase but tolerate any case.
        results = apply_validation_tags(
            [
                _validated(pid="gid://p/1",
                           risk_level="HIGH", passed=False),
                _validated(pid="gid://p/2",
                           risk_level="Critical", passed=False),
            ],
        )
        assert len(results) == 2

    def test_default_passed_true_treats_as_passed(
        self, isolated_queue,
    ):
        # Entry without explicit passed key — defaults to True
        # (the applier is defensive; real engine output always
        # includes passed).
        results = apply_validation_tags(
            [{"id": "gid://p/1", "risk_level": "high"}],
        )
        assert results == []


# ─── Direct path ──────────────────────────────────────────────


class TestDirectPath:

    def _run_direct(self, validated, **kwargs):
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
            results = apply_validation_tags(
                validated, require_approval=False, **kwargs,
            )
        return results, captured

    def test_failed_product_tagged(self):
        results, captured = self._run_direct([_validated()])
        assert results[0]["applied"] is True
        assert results[0]["tag"] == "shopai-validation-failed"
        assert captured["calls"][0]["cap"].name == "SHOPIFY_ADD_TAGS"
        assert captured["calls"][0]["params"]["id"] == (
            "gid://shopify/Product/1"
        )

    def test_router_unavailable_per_product_error(self):
        with patch(
            "core.adapters.get_router", return_value=None,
        ):
            results = apply_validation_tags(
                [_validated()], require_approval=False,
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
            results = apply_validation_tags(
                [_validated()], require_approval=False,
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
            results = apply_validation_tags(
                [_validated()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "adapter_raised" in results[0]["error"]


# ─── Queue path ──────────────────────────────────────────────


class TestQueuePath:

    def test_failed_product_enqueues(self, isolated_queue):
        results = apply_validation_tags([
            _validated(pid="gid://p/1", risk_level="critical",
                       recommendation="reject"),
        ])
        assert len(results) == 1
        assert "pending_action_id" in results[0]
        assert results[0]["applied"] is False
        action = isolated_queue.get(
            results[0]["pending_action_id"],
        )
        assert action.params["product_id"] == "gid://p/1"
        assert action.params["tag"] == "shopai-validation-failed"
        assert action.params["risk_level"] == "critical"
        assert action.params["recommendation"] == "reject"
        assert action.action_type == "tag_validation_failed"
        assert action.capability == "SHOPIFY_ADD_TAGS"

    def test_queue_unavailable_per_product_error(self):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            results = apply_validation_tags([_validated()])
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
        results = apply_validation_tags([
            _validated(pid="gid://p/1"),
            _validated(pid="gid://p/2"),
            _validated(pid="gid://p/3"),
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
            "engines.product_validation.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_validation_tags(
                [_validated()], require_approval=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "product_validation"
        assert kwargs["capability"] == "SHOPIFY_ADD_TAGS"
        assert kwargs["success"] is True

    def test_record_called_on_direct_failure(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.product_validation.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_validation_tags(
                [_validated()], require_approval=False,
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False

    def test_record_called_on_queue_enqueue(self, isolated_queue):
        with patch(
            "engines.product_validation.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_validation_tags([_validated()])
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True


# ─── Flow integration ────────────────────────────────────────


class TestFlowIntegration:

    def _input(self, *, apply=False, require_approval=None):
        # Product missing compliance signals → fail validation
        data = {
            "products": [
                {
                    "id": "gid://p/1",
                    "title": "Risky",
                    "category": "restricted",
                    "country_compliance": [],
                    "supplier_id": "",
                    "quality_score": 0.2,
                },
            ],
            "compliance_standards": ["fda", "ce"],
        }
        if apply:
            data["apply_validation_tags"] = True
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
        from engines.product_validation.flow import (
            ProductValidationEngine,
        )
        with patch(
            "engines.product_validation.tag_applier."
            "apply_validation_tags",
        ) as applier_mock:
            result = ProductValidationEngine().run(self._input())
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []

    def test_opt_in_calls_applier(self, isolated_queue):
        from engines.product_validation.flow import (
            ProductValidationEngine,
        )
        with patch(
            "engines.product_validation.tag_applier."
            "apply_validation_tags",
            return_value=[
                {"product_id": "gid://p/1",
                 "risk_level": "high",
                 "recommendation": "reject",
                 "tag": "shopai-validation-failed",
                 "applied": True, "error": None},
            ],
        ) as applier_mock:
            result = ProductValidationEngine().run(
                self._input(apply=True),
            )
        applier_mock.assert_called_once()
        kwargs = applier_mock.call_args.kwargs
        # Default require_approval=True propagates
        assert kwargs["require_approval"] is True
        assert len(result["data"]["tag_results"]) == 1

    def test_explicit_require_approval_false_propagates(
        self, isolated_queue,
    ):
        from engines.product_validation.flow import (
            ProductValidationEngine,
        )
        with patch(
            "engines.product_validation.tag_applier."
            "apply_validation_tags",
            return_value=[],
        ) as applier_mock:
            ProductValidationEngine().run(
                self._input(apply=True, require_approval=False),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is False
