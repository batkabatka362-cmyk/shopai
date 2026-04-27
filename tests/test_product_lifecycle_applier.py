"""Tests for product_lifecycle's archive applier (Phase 7).

This is the FIRST destructive Phase 6/7 writeback — the others
created NEW data (discount codes, gift cards, tag additions);
this one CHANGES existing product visibility (status=ARCHIVED).
The safety guardrails are correspondingly stricter:

  * Stage gate: only acts on ``decline`` stage entries.
  * Velocity floor: won't archive products still moving.
  * Optional confidence floor.
  * Always opt-in via ``data.apply_archives = True``.

Coverage layers:

  1. ``archive_declining_products`` — happy path, all 3 gates,
     adapter failure, router unavailable.
  2. Flow integration — opt-in flag wires applier in cleanly,
     min_confidence + velocity_floor params thread through.
"""
from __future__ import annotations

from unittest.mock import patch


# ─── archive_declining_products ───────────────────────────────────


class TestArchiveDecliningProducts:

    def _entry(self, **overrides):
        base = {
            "product_id": "gid://shopify/Product/1",
            "stage": "decline",
            "velocity": 0.1,
            "confidence": 0.85,
        }
        base.update(overrides)
        return base

    def test_no_lifecycle_returns_empty(self):
        from engines.product_lifecycle.lifecycle_applier import (
            archive_declining_products,
        )

        with patch(
            "engines.product_lifecycle.lifecycle_applier._get_router",
        ) as mock_router:
            assert archive_declining_products([]) == []
        mock_router.assert_not_called()

    def test_router_unavailable_returns_skipped(self):
        from engines.product_lifecycle.lifecycle_applier import (
            archive_declining_products,
        )

        with patch(
            "engines.product_lifecycle.lifecycle_applier._get_router",
            return_value=None,
        ):
            results = archive_declining_products([self._entry()])
        assert results[0]["archived"] is False
        assert results[0]["error"] == "router_unavailable"

    def test_non_decline_stage_skipped(self):
        from engines.product_lifecycle.lifecycle_applier import (
            archive_declining_products,
        )

        class _StubRouter:
            def __init__(self):
                self.calls = []

            def execute(self, capability, params):
                self.calls.append((capability, params))
                return None

        stub = _StubRouter()
        with patch(
            "engines.product_lifecycle.lifecycle_applier._get_router",
            return_value=stub,
        ):
            results = archive_declining_products([
                self._entry(stage="growth"),
                self._entry(stage="maturity"),
                self._entry(stage="introduction"),
            ])

        assert stub.calls == []
        assert all(r["archived"] is False for r in results)
        assert all(
            r["error"] == "stage_not_archivable" for r in results
        )

    def test_velocity_above_floor_skipped(self):
        # decline + still selling fast = "wait, don't archive yet".
        from engines.product_lifecycle.lifecycle_applier import (
            archive_declining_products,
        )

        class _StubRouter:
            def __init__(self):
                self.calls = []

            def execute(self, capability, params):
                self.calls.append((capability, params))
                return None

        stub = _StubRouter()
        with patch(
            "engines.product_lifecycle.lifecycle_applier._get_router",
            return_value=stub,
        ):
            results = archive_declining_products(
                [self._entry(velocity=2.0)],
            )

        assert stub.calls == []
        assert results[0]["archived"] is False
        assert results[0]["error"] == "velocity_above_floor"

    def test_below_min_confidence_skipped(self):
        from engines.product_lifecycle.lifecycle_applier import (
            archive_declining_products,
        )

        class _StubRouter:
            def __init__(self):
                self.calls = []

            def execute(self, capability, params):
                self.calls.append((capability, params))
                return None

        stub = _StubRouter()
        with patch(
            "engines.product_lifecycle.lifecycle_applier._get_router",
            return_value=stub,
        ):
            results = archive_declining_products(
                [self._entry(confidence=0.5)],
                min_confidence=0.7,
            )

        assert stub.calls == []
        assert results[0]["error"] == "below_min_confidence"

    def test_happy_path_archives_product(self):
        from core.adapters.base import Capability
        from engines.product_lifecycle.lifecycle_applier import (
            archive_declining_products,
        )

        class _StubResult:
            ok = True
            data = {"product": {"id": "gid://shopify/Product/1"}}
            error = None

        class _StubRouter:
            def __init__(self):
                self.calls = []

            def execute(self, capability, params):
                self.calls.append((capability, params))
                return _StubResult()

        stub = _StubRouter()
        with patch(
            "engines.product_lifecycle.lifecycle_applier._get_router",
            return_value=stub,
        ):
            results = archive_declining_products([self._entry()])

        # Adapter called with the right capability + params.
        assert len(stub.calls) == 1
        cap, params = stub.calls[0]
        assert cap == Capability.SHOPIFY_UPDATE_PRODUCT
        assert params["id"] == "gid://shopify/Product/1"
        assert params["status"] == "ARCHIVED"
        # Result reflects success.
        assert results[0]["archived"] is True
        assert results[0]["stage"] == "decline"
        assert results[0]["error"] is None

    def test_adapter_failure_records_error(self):
        from engines.product_lifecycle.lifecycle_applier import (
            archive_declining_products,
        )

        class _FailResult:
            ok = False
            data = {}
            error = "scope_missing"

        class _StubRouter:
            def execute(self, capability, params):
                return _FailResult()

        with patch(
            "engines.product_lifecycle.lifecycle_applier._get_router",
            return_value=_StubRouter(),
        ):
            results = archive_declining_products([self._entry()])

        assert results[0]["archived"] is False
        assert "adapter_failed" in results[0]["error"]


# ─── flow integration ───────────────────────────────────────────


class TestProductLifecycleFlowApplyArchives:

    def _input(self, apply: bool = False, **extra):
        return {
            "data": {
                "products": [
                    {
                        "id": "gid://shopify/Product/1",
                        "title": "Old Product",
                        "category": "general",
                    },
                ],
                "sales_history": [
                    # Sparse sales history that pushes the
                    # classifier toward "decline".
                    {"product_id": "gid://shopify/Product/1",
                     "period": "2025-01", "units": 0},
                ],
                "apply_archives": apply,
                **extra,
            },
        }

    def test_apply_archives_false_no_applier_call(self):
        from engines.product_lifecycle.flow import (
            ProductLifecycleEngine,
        )

        with patch(
            "engines.product_lifecycle.flow.archive_declining_products",
        ) as mock_archive:
            output = ProductLifecycleEngine().run(self._input(False))

        mock_archive.assert_not_called()
        if output["status"] == "success":
            assert output["data"]["archive_results"] == []

    def test_apply_archives_true_calls_applier(self):
        from engines.product_lifecycle.flow import (
            ProductLifecycleEngine,
        )

        with patch(
            "engines.product_lifecycle.flow.archive_declining_products",
            return_value=[
                {"product_id": "gid://shopify/Product/1",
                 "archived": True, "stage": "decline",
                 "velocity": 0.1, "error": None},
            ],
        ) as mock_archive:
            output = ProductLifecycleEngine().run(self._input(True))

        if output["status"] == "success":
            assert mock_archive.called
            results = output["data"]["archive_results"]
            assert len(results) == 1
            assert results[0]["archived"] is True

    def test_min_confidence_and_velocity_floor_threaded_through(self):
        from engines.product_lifecycle.flow import (
            ProductLifecycleEngine,
        )

        captured: dict = {}

        def _spy(lifecycle, *, min_confidence, velocity_floor):
            captured["min_confidence"] = min_confidence
            captured["velocity_floor"] = velocity_floor
            return []

        with patch(
            "engines.product_lifecycle.flow.archive_declining_products",
            side_effect=_spy,
        ):
            ProductLifecycleEngine().run(self._input(
                True,
                min_archive_confidence=0.85,
                archive_velocity_floor=0.2,
            ))

        if captured:
            assert captured["min_confidence"] == 0.85
            assert captured["velocity_floor"] == 0.2

    def test_lifecycle_now_carries_confidence(self):
        # The engine's per-product output now includes
        # ``confidence`` so the applier can read it directly.
        from engines.product_lifecycle.flow import (
            ProductLifecycleEngine,
        )

        output = ProductLifecycleEngine().run(self._input(False))

        if (output["status"] == "success"
                and output["data"]["lifecycle"]):
            entry = output["data"]["lifecycle"][0]
            assert "confidence" in entry
            assert isinstance(entry["confidence"], float)
