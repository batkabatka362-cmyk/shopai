"""Tests for catalog's Shopify wire-up — read-side hydrator
+ write-side tag applier."""
from __future__ import annotations

from unittest.mock import patch

from engines.catalog.shopify_applier import apply_tag_assignments
from engines.catalog.shopify_hydrator import hydrate_products


# ─── Stubs ────────────────────────────────────────────────────────


class _StubResult:
    def __init__(self, *, ok, data=None, error=None):
        self.ok = ok
        self.data = data or {}
        self.error = error


class _StubRouter:
    def __init__(self, *, result):
        self.result = result
        self.calls: list[tuple] = []

    def execute(self, capability, params):
        self.calls.append((capability, params))
        return self.result


# ─── Hydrator (read side) ─────────────────────────────────────────


class TestHydrateProducts:

    def test_supplied_passes_through(self):
        supplied = [
            {"id": "gid://shopify/Product/1", "title": "Widget"},
        ]
        with patch(
            "engines.catalog.shopify_hydrator._get_router",
        ) as mock_router:
            result = hydrate_products(supplied)
        assert result is supplied
        mock_router.assert_not_called()

    def test_empty_triggers_fetch(self):
        from core.adapters.base import Capability

        stub = _StubRouter(result=_StubResult(
            ok=True,
            data={
                "products": [
                    {
                        "id": "gid://shopify/Product/1",
                        "title": "Widget",
                    },
                ],
            },
        ))
        with patch(
            "engines.catalog.shopify_hydrator._get_router",
            return_value=stub,
        ):
            result = hydrate_products([])

        cap, _ = stub.calls[0]
        assert cap == Capability.SHOPIFY_LIST_PRODUCTS
        assert len(result) == 1

    def test_router_unavailable_returns_empty(self):
        with patch(
            "engines.catalog.shopify_hydrator._get_router",
            return_value=None,
        ):
            assert hydrate_products([]) == []

    def test_adapter_failure_returns_empty(self):
        stub = _StubRouter(result=_StubResult(
            ok=False, error="scope missing",
        ))
        with patch(
            "engines.catalog.shopify_hydrator._get_router",
            return_value=stub,
        ):
            assert hydrate_products([]) == []

    def test_query_filter_passes_through(self):
        stub = _StubRouter(result=_StubResult(
            ok=True, data={"products": []},
        ))
        with patch(
            "engines.catalog.shopify_hydrator._get_router",
            return_value=stub,
        ):
            hydrate_products([], query="status:active")
        _, params = stub.calls[0]
        assert params["query"] == "status:active"


# ─── Applier (write side) ─────────────────────────────────────────


def _three_assignments():
    return [
        {
            "product_id": "gid://shopify/Product/1",
            "tags": ["budget", "winter"],
            "tag_count": 2,
        },
        {
            "product_id": "gid://shopify/Product/2",
            "tags": ["premium", "summer"],
            "tag_count": 2,
        },
        {
            "product_id": "gid://shopify/Product/3",
            "tags": ["mid-range"],
            "tag_count": 1,
        },
    ]


class TestApplierOptInGate:

    def test_default_opt_out_no_router_calls(self):
        assignments = _three_assignments()
        with patch(
            "engines.catalog.shopify_applier._get_router",
        ) as mock_router:
            apply_tag_assignments(assignments)
        # Master switch defaults False → no router lookup.
        mock_router.assert_not_called()
        # Every assignment stamped with the "disabled" reason.
        for a in assignments:
            assert a["applied"] is False
            assert a["apply_error"] == "apply disabled by caller"

    def test_opt_in_calls_router_per_assignment(self):
        from core.adapters.base import Capability

        assignments = _three_assignments()
        stub = _StubRouter(result=_StubResult(
            ok=True, data={"node_id": "ok"},
        ))
        with patch(
            "engines.catalog.shopify_applier._get_router",
            return_value=stub,
        ):
            apply_tag_assignments(assignments, apply=True)

        # 3 router calls, all to SHOPIFY_ADD_TAGS.
        assert len(stub.calls) == 3
        for cap, params in stub.calls:
            assert cap == Capability.SHOPIFY_ADD_TAGS
            assert "id" in params
            assert isinstance(params["tags"], list)

        # Every assignment marked applied=True.
        for a in assignments:
            assert a["applied"] is True
            assert a["apply_error"] == ""

    def test_empty_assignments_returned_unchanged(self):
        with patch(
            "engines.catalog.shopify_applier._get_router",
        ) as mock_router:
            result = apply_tag_assignments([])
        assert result == []
        mock_router.assert_not_called()


class TestApplierGracefulFallbacks:

    def test_router_unavailable_stamps_skipped_on_all(self):
        assignments = _three_assignments()
        with patch(
            "engines.catalog.shopify_applier._get_router",
            return_value=None,
        ):
            apply_tag_assignments(assignments, apply=True)

        for a in assignments:
            assert a["applied"] is False
            assert a["apply_error"] == "router unavailable"

    def test_per_assignment_failure_doesnt_block_rest(self):
        assignments = _three_assignments()
        # Router returns ok=True for first call, ok=False for second,
        # raises for third.
        responses = iter([
            _StubResult(ok=True, data={}),
            _StubResult(ok=False, error="taggable not found"),
            _StubResult(ok=True, data={}),
        ])
        call_count = {"n": 0}

        class _SeqRouter:
            def execute(self, capability, params):
                call_count["n"] += 1
                if call_count["n"] == 3:
                    raise RuntimeError("network blip")
                return next(responses)

        with patch(
            "engines.catalog.shopify_applier._get_router",
            return_value=_SeqRouter(),
        ):
            apply_tag_assignments(assignments, apply=True)

        # 1st: succeeded.
        assert assignments[0]["applied"] is True
        # 2nd: adapter ok=False with error message.
        assert assignments[1]["applied"] is False
        assert "taggable not found" in assignments[1]["apply_error"]
        # 3rd: adapter raised — stamped with "adapter raised: ..."
        assert assignments[2]["applied"] is False
        assert "adapter raised" in assignments[2]["apply_error"]

    def test_assignment_with_no_product_id_skipped(self):
        assignments = [{
            "product_id": "",
            "tags": ["x"],
        }]
        stub = _StubRouter(result=_StubResult(
            ok=True, data={},
        ))
        with patch(
            "engines.catalog.shopify_applier._get_router",
            return_value=stub,
        ):
            apply_tag_assignments(assignments, apply=True)
        # No router call.
        assert stub.calls == []
        assert assignments[0]["applied"] is False
        assert assignments[0]["apply_error"] == "missing product_id"

    def test_assignment_with_no_tags_skipped(self):
        assignments = [{
            "product_id": "gid://shopify/Product/1",
            "tags": [],
        }]
        stub = _StubRouter(result=_StubResult(
            ok=True, data={},
        ))
        with patch(
            "engines.catalog.shopify_applier._get_router",
            return_value=stub,
        ):
            apply_tag_assignments(assignments, apply=True)
        assert stub.calls == []
        assert assignments[0]["applied"] is False
        assert assignments[0]["apply_error"] == "no tags to apply"

    def test_assignment_with_garbage_tags_skipped(self):
        # tags is a list but contains non-string / blank entries.
        assignments = [{
            "product_id": "gid://shopify/Product/1",
            "tags": ["", "   ", None, 42],
        }]
        stub = _StubRouter(result=_StubResult(
            ok=True, data={},
        ))
        with patch(
            "engines.catalog.shopify_applier._get_router",
            return_value=stub,
        ):
            apply_tag_assignments(assignments, apply=True)
        assert stub.calls == []
        assert assignments[0]["applied"] is False
        assert assignments[0]["apply_error"] == "no tags to apply"


# ─── Flow integration ────────────────────────────────────────────


class TestFlowIntegration:

    def _input_with_no_products(self):
        return {"data": {"products": [], "tags": ["budget", "premium"]}}

    def test_flow_hydrates_when_products_empty(self):
        from engines.catalog.flow import CatalogEngine

        injected = [
            {
                "id": "gid://shopify/Product/1",
                "title": "Widget",
                "category": "Tools",
                "price": 50,
                "description": "premium widget",
            },
        ]
        with patch(
            "engines.catalog.flow.hydrate_products",
            return_value=injected,
        ):
            output = CatalogEngine().run(
                self._input_with_no_products(),
            )

        # Hydrator filled in products → "Products list is required"
        # error must NOT fire.
        if output["status"] == "error":
            assert "Products list is required" not in (
                output.get("error") or ""
            )

    def test_flow_falls_back_when_hydrator_empty(self):
        from engines.catalog.flow import CatalogEngine

        with patch(
            "engines.catalog.flow.hydrate_products",
            return_value=[],
        ):
            output = CatalogEngine().run(
                self._input_with_no_products(),
            )
        assert output["status"] == "error"
        assert "Products list is required" in output["error"]

    def test_flow_calls_applier_with_apply_default_off(self):
        from engines.catalog.flow import CatalogEngine

        captured: dict = {}

        def _record(assignments, *, apply=False):
            captured["apply"] = apply
            for a in assignments:
                a["applied"] = False
                a["apply_error"] = "apply disabled by caller"
            return assignments

        with patch(
            "engines.catalog.flow.apply_tag_assignments",
            side_effect=_record,
        ):
            CatalogEngine().run({
                "data": {
                    "products": [
                        {
                            "id": "gid://shopify/Product/1",
                            "title": "Widget",
                            "category": "Tools",
                            "price": 50,
                        },
                    ],
                    "tags": ["budget"],
                },
            })

        # Default opt-out — apply=False.
        assert captured["apply"] is False

    def test_flow_calls_applier_with_apply_on_when_opted_in(self):
        from engines.catalog.flow import CatalogEngine

        captured: dict = {}

        def _record(assignments, *, apply=False):
            captured["apply"] = apply
            for a in assignments:
                a["applied"] = apply
                a["apply_error"] = "" if apply else "off"
            return assignments

        with patch(
            "engines.catalog.flow.apply_tag_assignments",
            side_effect=_record,
        ):
            output = CatalogEngine().run({
                "data": {
                    "products": [
                        {
                            "id": "gid://shopify/Product/1",
                            "title": "Widget",
                            "category": "Tools",
                            "price": 50,
                        },
                    ],
                    "tags": ["budget"],
                    "apply_tags": True,
                },
            })

        assert captured["apply"] is True
        # And the applied=True flag flows through to the engine
        # output's tag_assignments.
        if output["status"] == "success":
            for a in output["data"]["tag_assignments"]:
                assert a["applied"] is True
