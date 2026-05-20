"""Tests for ``engines.product_risk.tag_applier``.

Pushes ``shopai-risk-{level}`` tags on at-risk products via
SHOPIFY_ADD_TAGS. Two paths (queue / direct) selected by
``require_approval``.

Coverage:
  1. Input filtering (empty / non-list / non-dict / missing
     product_id / "unknown" literal / non-critical default /
     high gated by include_high / worst-risk dedup /
     case-insensitive level).
  2. Direct path: SHOPIFY_ADD_TAGS called per at-risk product;
     router unavailable, adapter failure, raise all handled.
  3. Queue path: each at-risk product enqueues with correct
     params; queue unavailable; per-enqueue raise doesn't
     abort.
  4. Pattern Z: record_writeback fires on every outcome.
  5. Flow integration: default off / opt-in calls applier /
     require_approval / include_high propagate.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from engines.product_risk.tag_applier import (
    apply_risk_tags,
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
    level="critical",
    overall=0.85,
):
    return {
        "product_id": pid,
        "market_risk": 0.5,
        "supply_risk": 0.6,
        "legal_risk": 0.7,
        "financial_risk": 0.9,
        "overall": overall,
        "risk_level": level,
    }


# ─── Input filtering ──────────────────────────────────────────


class TestInputFiltering:

    def test_empty_input(self, isolated_queue):
        assert apply_risk_tags([]) == []

    def test_non_list_input(self, isolated_queue):
        assert apply_risk_tags(None) == []  # type: ignore

    def test_non_dict_entry_skipped(self, isolated_queue):
        results = apply_risk_tags(
            ["bad", 42, _risk(pid="gid://p/2")],  # type: ignore
        )
        assert len(results) == 1

    def test_missing_product_id_skipped(self, isolated_queue):
        results = apply_risk_tags(
            [_risk(pid="")],
        )
        assert results == []

    def test_unknown_product_id_skipped(self, isolated_queue):
        # The engine uses "unknown" as a default for a
        # product missing an id — don't tag.
        results = apply_risk_tags(
            [_risk(pid="unknown")],
        )
        assert results == []

    def test_only_critical_tagged_by_default(self, isolated_queue):
        results = apply_risk_tags(
            [
                _risk(pid="gid://p/1", level="critical"),
                _risk(pid="gid://p/2", level="high"),
                _risk(pid="gid://p/3", level="moderate"),
                _risk(pid="gid://p/4", level="low"),
            ],
        )
        assert len(results) == 1
        assert results[0]["risk_level"] == "critical"
        assert results[0]["tag"] == "shopai-risk-critical"

    def test_include_high_opts_in(self, isolated_queue):
        results = apply_risk_tags(
            [
                _risk(pid="gid://p/1", level="critical"),
                _risk(pid="gid://p/2", level="high"),
                _risk(pid="gid://p/3", level="moderate"),
            ],
            include_high=True,
        )
        assert len(results) == 2
        levels = {r["risk_level"] for r in results}
        assert levels == {"critical", "high"}

    def test_dedup_keeps_worst_risk(self, isolated_queue):
        # Same product appears twice with different levels;
        # critical wins over high.
        results = apply_risk_tags(
            [
                _risk(pid="gid://p/1", level="high"),
                _risk(pid="gid://p/1", level="critical"),
            ],
            include_high=True,
        )
        assert len(results) == 1
        assert results[0]["risk_level"] == "critical"

    def test_case_insensitive_level(self, isolated_queue):
        results = apply_risk_tags(
            [
                _risk(pid="gid://p/1", level="CRITICAL"),
                _risk(pid="gid://p/2", level="Critical"),
            ],
        )
        assert len(results) == 2

    def test_bad_overall_coerced_to_zero(self, isolated_queue):
        results = apply_risk_tags(
            [{
                "product_id": "gid://p/1",
                "risk_level": "critical",
                "overall": "very high",
            }],
        )
        assert len(results) == 1
        assert results[0]["overall"] == 0.0


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
            results = apply_risk_tags(
                risks, require_approval=False, **kwargs,
            )
        return results, captured

    def test_critical_product_tagged(self):
        results, captured = self._run_direct([_risk()])
        assert results[0]["applied"] is True
        assert results[0]["tag"] == "shopai-risk-critical"
        assert captured["calls"][0]["cap"].name == "SHOPIFY_ADD_TAGS"
        assert captured["calls"][0]["params"]["id"] == (
            "gid://shopify/Product/1"
        )

    def test_router_unavailable_per_product_error(self):
        with patch(
            "core.adapters.get_router", return_value=None,
        ):
            results = apply_risk_tags(
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
            results = apply_risk_tags(
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
            results = apply_risk_tags(
                [_risk()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "adapter_raised" in results[0]["error"]


# ─── Queue path ──────────────────────────────────────────────


class TestQueuePath:

    def test_critical_product_enqueues(self, isolated_queue):
        results = apply_risk_tags([
            _risk(pid="gid://p/1", level="critical", overall=0.85),
        ])
        assert len(results) == 1
        assert "pending_action_id" in results[0]
        assert results[0]["applied"] is False
        action = isolated_queue.get(
            results[0]["pending_action_id"],
        )
        assert action.params["product_id"] == "gid://p/1"
        assert action.params["tag"] == "shopai-risk-critical"
        assert action.params["risk_level"] == "critical"
        assert action.params["overall"] == 0.85
        assert action.action_type == "tag_product_risk"
        assert action.capability == "SHOPIFY_ADD_TAGS"

    def test_queue_unavailable_per_product_error(self):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            results = apply_risk_tags([_risk()])
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
        results = apply_risk_tags([
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
            "engines.product_risk.tag_applier.record_writeback",
        ) as record_mock:
            apply_risk_tags(
                [_risk()], require_approval=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "product_risk"
        assert kwargs["capability"] == "SHOPIFY_ADD_TAGS"
        assert kwargs["success"] is True

    def test_record_called_on_direct_failure(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.product_risk.tag_applier.record_writeback",
        ) as record_mock:
            apply_risk_tags(
                [_risk()], require_approval=False,
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False

    def test_record_called_on_queue_enqueue(self, isolated_queue):
        with patch(
            "engines.product_risk.tag_applier.record_writeback",
        ) as record_mock:
            apply_risk_tags([_risk()])
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True


# ─── Flow integration ────────────────────────────────────────


class TestFlowIntegration:

    def _input(
        self, *, apply=False, require_approval=None,
        include_high=None,
    ):
        # Build a product with a "restricted" category +
        # missing legal docs → high legal risk
        data = {
            "products": [
                {
                    "id": "gid://shopify/Product/1",
                    "title": "Risky",
                    "category": "restricted_chemicals",
                    "country_compliance": [],
                    "margin_pct": 5.0,
                    "sale_price": 100.0,
                    "unit_cost": 95.0,
                },
            ],
            "market_data": [],
            "suppliers": [],
        }
        if apply:
            data["apply_risk_tags"] = True
        if require_approval is not None:
            data["require_approval"] = require_approval
        if include_high is not None:
            data["include_high"] = include_high
        return {
            "status": "success",
            "data": data,
            "meta": {},
            "error": None,
        }

    def test_default_off_keeps_tag_results_empty(
        self, isolated_queue,
    ):
        from engines.product_risk.flow import ProductRiskEngine
        with patch(
            "engines.product_risk.tag_applier.apply_risk_tags",
        ) as applier_mock:
            result = ProductRiskEngine().run(self._input())
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []

    def test_opt_in_calls_applier(self, isolated_queue):
        from engines.product_risk.flow import ProductRiskEngine
        with patch(
            "engines.product_risk.tag_applier.apply_risk_tags",
            return_value=[
                {"product_id": "gid://p/1",
                 "risk_level": "critical",
                 "overall": 0.85,
                 "tag": "shopai-risk-critical",
                 "applied": True, "error": None},
            ],
        ) as applier_mock:
            result = ProductRiskEngine().run(
                self._input(apply=True),
            )
        applier_mock.assert_called_once()
        kwargs = applier_mock.call_args.kwargs
        # Defaults propagate
        assert kwargs["require_approval"] is True
        assert kwargs["include_high"] is False
        assert len(result["data"]["tag_results"]) == 1

    def test_explicit_require_approval_false_propagates(
        self, isolated_queue,
    ):
        from engines.product_risk.flow import ProductRiskEngine
        with patch(
            "engines.product_risk.tag_applier.apply_risk_tags",
            return_value=[],
        ) as applier_mock:
            ProductRiskEngine().run(
                self._input(apply=True, require_approval=False),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is False

    def test_include_high_propagates(self, isolated_queue):
        from engines.product_risk.flow import ProductRiskEngine
        with patch(
            "engines.product_risk.tag_applier.apply_risk_tags",
            return_value=[],
        ) as applier_mock:
            ProductRiskEngine().run(
                self._input(apply=True, include_high=True),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["include_high"] is True
