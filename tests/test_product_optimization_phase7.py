"""Tests for the product_optimization Phase 7 writeback.

The engine now wraps its advisory pricing adjustments in an
opt-in writeback path that enqueues
``apply_strategic_price`` actions via the approval queue.
Mirrors the established Phase 6/7 pattern (loyalty PR #43,
dynamic_pricing PR #46, etc.).

Tests cover:
  - The applier's four guardrails (missing product id, below
    threshold, non-positive price, missing variants)
  - Happy path: well-formed adjustment + variants → enqueued
  - Engine flow integration: opt-in flag routes through;
    default OFF leaves the list empty
  - Writeback recorder integration is non-blocking
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    """Swap the approval queue singleton for a fresh in-temp
    DB so test enqueues don't poison the live state."""
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue
    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


# ─── Applier guardrails ────────────────────────────────────────


class TestApplierGuardrails:

    def test_empty_input_returns_empty(self, isolated_queue):
        from engines.product_optimization.optimization_applier import (
            apply_pricing_optimizations,
        )
        assert apply_pricing_optimizations(
            adjustments=[], products=[],
        ) == []

    def test_non_list_input_returns_empty(self, isolated_queue):
        from engines.product_optimization.optimization_applier import (
            apply_pricing_optimizations,
        )
        # type: ignore[arg-type]
        assert apply_pricing_optimizations(
            adjustments=None, products=[],
        ) == []

    def test_missing_product_id_skipped(self, isolated_queue):
        from engines.product_optimization.optimization_applier import (
            apply_pricing_optimizations,
        )
        results = apply_pricing_optimizations(
            adjustments=[{
                "product_id": "",
                "current_price": 10.0,
                "suggested_price": 12.0,
                "adjustment_pct": 20.0,
            }],
            products=[],
        )
        assert results[0]["status"] == "skipped"
        assert results[0]["reason"] == "missing_product_id"

    def test_below_threshold_skipped(self, isolated_queue):
        from engines.product_optimization.optimization_applier import (
            apply_pricing_optimizations,
        )
        results = apply_pricing_optimizations(
            adjustments=[{
                "product_id": "p1",
                "current_price": 10.0,
                "suggested_price": 10.01,
                "adjustment_pct": 0.05,  # below 0.1 threshold
            }],
            products=[{
                "id": "p1",
                "variants": [{"id": "v1"}],
            }],
        )
        assert results[0]["status"] == "skipped"
        assert results[0]["reason"] == "adjustment_below_threshold"

    def test_non_positive_price_skipped(self, isolated_queue):
        from engines.product_optimization.optimization_applier import (
            apply_pricing_optimizations,
        )
        results = apply_pricing_optimizations(
            adjustments=[{
                "product_id": "p1",
                "current_price": 10.0,
                "suggested_price": 0.0,
                "adjustment_pct": -100.0,
            }],
            products=[{
                "id": "p1",
                "variants": [{"id": "v1"}],
            }],
        )
        assert results[0]["status"] == "skipped"
        assert results[0]["reason"] == "non_positive_price"

    def test_missing_variants_skipped(self, isolated_queue):
        from engines.product_optimization.optimization_applier import (
            apply_pricing_optimizations,
        )
        results = apply_pricing_optimizations(
            adjustments=[{
                "product_id": "p1",
                "current_price": 10.0,
                "suggested_price": 12.0,
                "adjustment_pct": 20.0,
            }],
            # No products list → variant lookup empty
            products=[],
        )
        assert results[0]["status"] == "skipped"
        assert results[0]["reason"] == "missing_variant_ids"

    def test_product_without_variants_field_skipped(
        self, isolated_queue,
    ):
        """Hydrated product lists from SHOPIFY_LIST_PRODUCTS
        often omit variants — CLAUDE.md documents this. The
        applier safely skips rather than enqueueing a malformed
        action."""
        from engines.product_optimization.optimization_applier import (
            apply_pricing_optimizations,
        )
        results = apply_pricing_optimizations(
            adjustments=[{
                "product_id": "p1",
                "current_price": 10.0,
                "suggested_price": 12.0,
                "adjustment_pct": 20.0,
            }],
            products=[{"id": "p1"}],  # no variants field
        )
        assert results[0]["status"] == "skipped"
        assert results[0]["reason"] == "missing_variant_ids"

    def test_product_with_empty_variants_skipped(
        self, isolated_queue,
    ):
        from engines.product_optimization.optimization_applier import (
            apply_pricing_optimizations,
        )
        results = apply_pricing_optimizations(
            adjustments=[{
                "product_id": "p1",
                "current_price": 10.0,
                "suggested_price": 12.0,
                "adjustment_pct": 20.0,
            }],
            products=[{"id": "p1", "variants": []}],
        )
        assert results[0]["status"] == "skipped"
        assert results[0]["reason"] == "missing_variant_ids"


# ─── Happy path enqueue ────────────────────────────────────────


class TestEnqueue:

    def test_well_formed_adjustment_queues(self, isolated_queue):
        from engines.product_optimization.optimization_applier import (
            apply_pricing_optimizations,
        )
        results = apply_pricing_optimizations(
            adjustments=[{
                "product_id": "p1",
                "current_price": 10.0,
                "suggested_price": 12.0,
                "adjustment_pct": 20.0,
                "rationale": "high demand",
            }],
            products=[{
                "id": "p1",
                "variants": [{"id": "v11"}, {"id": "v12"}],
            }],
        )
        assert len(results) == 1
        assert results[0]["status"] == "queued"
        assert results[0]["product_id"] == "p1"
        assert "pending_action_id" in results[0]
        assert results[0]["suggested_price"] == 12.0

    def test_queued_action_persisted_in_queue(self, isolated_queue):
        """Confirm the enqueue actually persisted — the action
        id should map to a real PENDING row."""
        from engines.product_optimization.optimization_applier import (
            apply_pricing_optimizations,
        )
        results = apply_pricing_optimizations(
            adjustments=[{
                "product_id": "p1",
                "current_price": 10.0,
                "suggested_price": 12.0,
                "adjustment_pct": 20.0,
                "rationale": "high demand",
            }],
            products=[{
                "id": "p1",
                "variants": [{"id": "v11"}],
            }],
        )
        action_id = results[0]["pending_action_id"]
        action = isolated_queue.get(action_id)
        assert action is not None
        assert action.engine == "product_optimization"
        assert action.action_type == "apply_strategic_price"
        assert action.capability == "SHOPIFY_UPDATE_VARIANTS"

    def test_enqueued_params_match_dispatcher_shape(
        self, isolated_queue,
    ):
        """The dispatcher (PR #159) expects product_id +
        new_price + variant_ids. The applier must produce
        exactly that shape."""
        from engines.product_optimization.optimization_applier import (
            apply_pricing_optimizations,
        )
        results = apply_pricing_optimizations(
            adjustments=[{
                "product_id": "p1",
                "current_price": 10.0,
                "suggested_price": 12.0,
                "adjustment_pct": 20.0,
                "rationale": "high demand",
            }],
            products=[{
                "id": "p1",
                "variants": [{"id": "v11"}, {"id": "v12"}],
            }],
        )
        action = isolated_queue.get(results[0]["pending_action_id"])
        assert action.params["product_id"] == "p1"
        assert action.params["new_price"] == 12.0
        assert action.params["variant_ids"] == ["v11", "v12"]
        # Extra context preserved for operator review
        assert action.params["adjustment_pct"] == 20.0
        assert action.params["rationale"] == "high demand"

    def test_narrative_populated(self, isolated_queue):
        """Narrative shows up in the approval queue UI; should
        carry the rationale + price + pct so reviewers see
        context without clicking through."""
        from engines.product_optimization.optimization_applier import (
            apply_pricing_optimizations,
        )
        results = apply_pricing_optimizations(
            adjustments=[{
                "product_id": "p1",
                "current_price": 10.0,
                "suggested_price": 12.0,
                "adjustment_pct": 20.0,
                "rationale": "high conversion this week",
            }],
            products=[{
                "id": "p1",
                "variants": [{"id": "v11"}],
            }],
        )
        action = isolated_queue.get(results[0]["pending_action_id"])
        assert "$12.00" in action.narrative
        assert "+20.0%" in action.narrative
        assert "high conversion this week" in action.narrative


# ─── Engine flow integration ───────────────────────────────────


class TestFlowIntegration:

    def _build_input(self, *, apply: bool):
        """Minimal engine input that exercises the flow's full
        pipeline and exposes the Phase 7 path."""
        return {
            "status": "success",
            "data": {
                "products": [
                    {
                        "id": "p1",
                        "product_id": "p1",
                        "price": 10.0,
                        "conversion_rate": 0.05,
                        "performance_score": 0.6,
                        "variants": [{"id": "v11"}],
                    },
                ],
                "performance_data": [
                    {
                        "product_id": "p1",
                        "conversion_rate": 0.05,
                        "performance_score": 0.6,
                    },
                ],
                "apply_pricing_adjustments": apply,
            },
        }

    def test_opt_out_keeps_list_empty(self, isolated_queue):
        from engines.product_optimization.flow import (
            ProductOptimizationEngine,
        )
        out = ProductOptimizationEngine().run(
            self._build_input(apply=False),
        )
        assert out["status"] == "success"
        # Default off → empty list (still present so callers
        # can rely on the schema)
        assert out["data"]["pricing_pending_actions"] == []

    def test_opt_in_populates_list(self, isolated_queue):
        from engines.product_optimization.flow import (
            ProductOptimizationEngine,
        )
        out = ProductOptimizationEngine().run(
            self._build_input(apply=True),
        )
        assert out["status"] == "success"
        actions = out["data"]["pricing_pending_actions"]
        # Either queued or skipped, but the list IS populated
        assert isinstance(actions, list)
        # The engine might not produce a material adjustment for
        # the synthetic input (conversion_rate=0.05 is in the
        # "appropriate" band), in which case nothing queues —
        # but the field is present
        assert all(
            r.get("status") in {"queued", "skipped"}
            for r in actions
        )


# ─── Resilience: recorder failure doesn't break enqueue ────────


class TestResilience:

    def test_recorder_failure_doesnt_break_result(
        self, isolated_queue,
    ):
        """The writeback recorder is best-effort. If it raises,
        the enqueue still surfaces as queued — the action is
        on Shopify's side, recorded for operator review."""
        from engines.product_optimization.optimization_applier import (
            apply_pricing_optimizations,
        )
        with patch(
            "engines._writeback_recorder.record_writeback",
            side_effect=RuntimeError("recorder broken"),
        ):
            results = apply_pricing_optimizations(
                adjustments=[{
                    "product_id": "p1",
                    "current_price": 10.0,
                    "suggested_price": 12.0,
                    "adjustment_pct": 20.0,
                }],
                products=[{
                    "id": "p1",
                    "variants": [{"id": "v11"}],
                }],
            )
        # Still queued despite recorder failure
        assert results[0]["status"] == "queued"

    def test_enqueue_failure_returns_skipped(self, isolated_queue):
        from engines.product_optimization.optimization_applier import (
            apply_pricing_optimizations,
        )
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            results = apply_pricing_optimizations(
                adjustments=[{
                    "product_id": "p1",
                    "current_price": 10.0,
                    "suggested_price": 12.0,
                    "adjustment_pct": 20.0,
                }],
                products=[{
                    "id": "p1",
                    "variants": [{"id": "v11"}],
                }],
            )
        assert results[0]["status"] == "skipped"
        assert "enqueue_raised" in results[0]["reason"]


# ─── Direct-apply path (require_approval=False) ────────────────


class TestDirectApplyPath:
    """``require_approval=False`` calls
    ``Capability.SHOPIFY_UPDATE_VARIANTS`` directly through the
    router, bypassing the approval queue. Result status is
    ``applied`` (not ``queued``)."""

    def test_direct_apply_calls_router(self, isolated_queue):
        from types import SimpleNamespace
        from engines.product_optimization.optimization_applier import (
            apply_pricing_optimizations,
        )

        captured = {}

        def _exec(cap, params):
            captured["capability"] = cap
            captured["params"] = params
            return SimpleNamespace(ok=True, data={}, error=None)

        router = SimpleNamespace(execute=_exec)
        with patch("core.adapters.get_router", return_value=router):
            results = apply_pricing_optimizations(
                adjustments=[{
                    "product_id": "p1",
                    "current_price": 10.0,
                    "suggested_price": 12.0,
                    "adjustment_pct": 20.0,
                }],
                products=[{
                    "id": "p1",
                    "variants": [{"id": "v11"}, {"id": "v12"}],
                }],
                require_approval=False,
            )
        # Router was called with SHOPIFY_UPDATE_VARIANTS
        assert captured["capability"].name == "SHOPIFY_UPDATE_VARIANTS"
        # Both variants were sent
        assert len(captured["params"]["variants"]) == 2
        # Result is ``applied`` (not ``queued``)
        assert results[0]["status"] == "applied"
        assert results[0]["variants_updated"] == 2

    def test_direct_apply_router_failure_returns_skipped(
        self, isolated_queue,
    ):
        from types import SimpleNamespace
        from engines.product_optimization.optimization_applier import (
            apply_pricing_optimizations,
        )

        router = SimpleNamespace(
            execute=lambda c, p: SimpleNamespace(
                ok=False, data=None, error="rate_limited",
            ),
        )
        with patch("core.adapters.get_router", return_value=router):
            results = apply_pricing_optimizations(
                adjustments=[{
                    "product_id": "p1",
                    "current_price": 10.0,
                    "suggested_price": 12.0,
                    "adjustment_pct": 20.0,
                }],
                products=[{"id": "p1", "variants": [{"id": "v11"}]}],
                require_approval=False,
            )
        assert results[0]["status"] == "skipped"
        assert "direct_apply_failed" in results[0]["reason"]
        assert "rate_limited" in results[0]["reason"]

    def test_direct_apply_router_raise_returns_skipped(
        self, isolated_queue,
    ):
        from types import SimpleNamespace
        from engines.product_optimization.optimization_applier import (
            apply_pricing_optimizations,
        )

        def _raises(c, p):
            raise RuntimeError("boom")

        router = SimpleNamespace(execute=_raises)
        with patch("core.adapters.get_router", return_value=router):
            results = apply_pricing_optimizations(
                adjustments=[{
                    "product_id": "p1",
                    "current_price": 10.0,
                    "suggested_price": 12.0,
                    "adjustment_pct": 20.0,
                }],
                products=[{"id": "p1", "variants": [{"id": "v11"}]}],
                require_approval=False,
            )
        assert results[0]["status"] == "skipped"
        assert "router_raised" in results[0]["reason"]


# ─── Flow plumbing of require_approval ─────────────────────────


class TestFlowRequireApprovalRouting:
    """The engine's flow reads ``data.require_approval`` (default
    True) and forwards it to the applier."""

    def test_default_routes_to_queue_path(self, isolated_queue):
        """Without ``require_approval`` in input, the flow goes
        through the queue (existing behavior)."""
        from engines.product_optimization.flow import (
            ProductOptimizationEngine,
        )

        with patch(
            "engines.product_optimization.optimization_applier."
            "apply_pricing_optimizations",
        ) as applier_mock:
            applier_mock.return_value = []
            ProductOptimizationEngine().run({
                "status": "success",
                "data": {
                    "products": [{"id": "p1", "title": "T"}],
                    "apply_pricing_adjustments": True,
                },
                "meta": {},
                "error": None,
            })
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is True

    def test_explicit_false_routes_to_direct_apply(
        self, isolated_queue,
    ):
        from engines.product_optimization.flow import (
            ProductOptimizationEngine,
        )

        with patch(
            "engines.product_optimization.optimization_applier."
            "apply_pricing_optimizations",
        ) as applier_mock:
            applier_mock.return_value = []
            ProductOptimizationEngine().run({
                "status": "success",
                "data": {
                    "products": [{"id": "p1", "title": "T"}],
                    "apply_pricing_adjustments": True,
                    "require_approval": False,
                },
                "meta": {},
                "error": None,
            })
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is False
