"""Tests for ``engines.store_setup.product_seeder``.

Niche-aware starter-product seeder that closes the audit's
``active_products`` gap on a freshly launched store. Per-niche
sets of 4 placeholder products, ACTIVE status, tagged
``starter`` so operators can bulk-archive once their real
catalog lands.

Coverage:
  1. Each known niche generates 4 specs with the required
     friendly call shape.
  2. Unknown niche falls back to general.
  3. Vendor override flows into each spec; empty vendor omits.
  4. Handles are valid URL slugs derived from titles.
  5. Status is ACTIVE (anything else defeats the seeder).
  6. Tags include ``starter`` so operators can bulk-archive.
  7. apply_starter_products: empty list short-circuits.
  8. Happy path: router.ok=True -> applied_count = len(specs).
  9. Partial failure: some ok, some not.
  10. Router unavailable -> all results error.
  11. Router raise -> per-spec error captured, loop continues.
  12. Pattern Z recording on apply.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from engines.store_setup.product_seeder import (
    apply_starter_products,
    generate_starter_products,
)


def _ok(data=None):
    return SimpleNamespace(ok=True, data=data, error=None)


def _fail(error="x"):
    return SimpleNamespace(ok=False, data=None, error=error)


class TestGenerate:

    def test_beauty_four_specs(self):
        specs = generate_starter_products(niche="beauty")
        assert len(specs) == 4
        titles = [s["title"] for s in specs]
        assert "Hydrating Vitamin C Serum" in titles

    def test_unknown_niche_falls_back_to_general(self):
        specs = generate_starter_products(niche="nonsense")
        general = generate_starter_products(niche="general")
        assert [s["title"] for s in specs] == [
            s["title"] for s in general
        ]

    def test_each_spec_has_required_fields(self):
        for niche in ("beauty", "fashion", "tech", "home",
                      "food", "general"):
            specs = generate_starter_products(niche=niche)
            for spec in specs:
                assert "title" in spec
                assert "handle" in spec
                assert "description_html" in spec
                assert "product_type" in spec
                assert "tags" in spec
                assert "status" in spec
                # No empty titles allowed
                assert spec["title"].strip()

    def test_handle_is_slug(self):
        specs = generate_starter_products(niche="beauty")
        for spec in specs:
            h = spec["handle"]
            # lowercase, no whitespace, no special chars
            assert h == h.lower()
            assert " " not in h
            assert all(c.isalnum() or c == "-" for c in h)

    def test_status_is_ACTIVE(self):
        """ACTIVE status is mandatory -- DRAFT defeats the
        whole point of the seeder (audit's active_products
        check ignores DRAFT)."""
        for niche in ("beauty", "fashion", "tech", "home",
                      "food", "general"):
            for spec in generate_starter_products(niche=niche):
                assert spec["status"] == "ACTIVE"

    def test_tags_include_starter_marker(self):
        for niche in ("beauty", "fashion", "tech", "home",
                      "food", "general"):
            for spec in generate_starter_products(niche=niche):
                assert "starter" in spec["tags"]

    def test_vendor_omitted_when_empty(self):
        for spec in generate_starter_products(niche="beauty"):
            assert "vendor" not in spec

    def test_vendor_flows_to_each_spec(self):
        specs = generate_starter_products(
            niche="beauty", vendor="Acme Beauty",
        )
        for spec in specs:
            assert spec["vendor"] == "Acme Beauty"


class TestApplyEmpty:

    def test_empty_list_short_circuits(self):
        result = apply_starter_products([])
        assert result == {"applied_count": 0, "results": []}

    def test_non_list_input_short_circuits(self):
        result = apply_starter_products(None)  # type: ignore
        assert result["applied_count"] == 0


class TestApplyHappyPath:

    def test_all_create_calls_succeed(self):
        specs = generate_starter_products(niche="beauty")
        router = type("R", (), {})()
        router.execute = lambda cap, params: _ok({"product": {}})
        with patch(
            "engines.store_setup.product_seeder._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.product_seeder.record_writeback",
        ):
            result = apply_starter_products(specs)
        assert result["applied_count"] == len(specs)
        assert all(r["ok"] for r in result["results"])
        assert all(r["error"] is None for r in result["results"])

    def test_results_carry_title_and_handle(self):
        specs = generate_starter_products(niche="beauty")
        router = type("R", (), {})()
        router.execute = lambda cap, params: _ok({})
        with patch(
            "engines.store_setup.product_seeder._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.product_seeder.record_writeback",
        ):
            result = apply_starter_products(specs)
        for spec, r in zip(specs, result["results"]):
            assert r["title"] == spec["title"]
            assert r["handle"] == spec["handle"]


class TestApplyPartialFailure:

    def test_mixed_ok_and_fail(self):
        specs = generate_starter_products(niche="beauty")
        # First 2 succeed, last 2 fail
        responses = iter([
            _ok({}), _ok({}),
            _fail("rate_limited"), _fail("rate_limited"),
        ])
        router = type("R", (), {})()
        router.execute = lambda cap, params: next(responses)
        with patch(
            "engines.store_setup.product_seeder._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.product_seeder.record_writeback",
        ):
            result = apply_starter_products(specs)
        assert result["applied_count"] == 2
        ok_count = sum(1 for r in result["results"] if r["ok"])
        assert ok_count == 2
        # Failures carry the adapter's error message
        fails = [r for r in result["results"] if not r["ok"]]
        assert all("rate_limited" in (r["error"] or "")
                   for r in fails)


class TestApplyResilience:

    def test_router_unavailable_marks_all_failed(self):
        specs = generate_starter_products(niche="beauty")
        with patch(
            "engines.store_setup.product_seeder._get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.product_seeder.record_writeback",
        ):
            result = apply_starter_products(specs)
        assert result["applied_count"] == 0
        assert all(not r["ok"] for r in result["results"])
        assert all(r["error"] == "router_unavailable"
                   for r in result["results"])

    def test_one_spec_raise_doesnt_break_loop(self):
        specs = generate_starter_products(niche="beauty")
        call_count = {"n": 0}

        def _exec(cap, params):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("network blip")
            return _ok({})

        router = type("R", (), {})()
        router.execute = _exec
        with patch(
            "engines.store_setup.product_seeder._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.product_seeder.record_writeback",
        ):
            result = apply_starter_products(specs)
        # 3 of 4 succeeded; index 1 captured the raise
        assert result["applied_count"] == 3
        raised = result["results"][1]
        assert raised["ok"] is False
        assert "network blip" in (raised["error"] or "")


class TestPatternZ:

    def test_record_called_per_spec(self):
        specs = generate_starter_products(niche="beauty")
        router = type("R", (), {})()
        router.execute = lambda cap, params: _ok({})
        with patch(
            "engines.store_setup.product_seeder._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.product_seeder.record_writeback",
        ) as record_mock:
            apply_starter_products(specs, store_id="store-a")
        # One record per spec
        assert record_mock.call_count == len(specs)
        # store_id propagates
        first_call = record_mock.call_args_list[0]
        params = first_call.kwargs["params"]
        assert params["store_id"] == "store-a"
        # action_type + capability shape correct
        assert first_call.kwargs["action_type"] == "seed_product"
        assert (
            first_call.kwargs["capability"]
            == "SHOPIFY_CREATE_PRODUCT"
        )

    def test_failure_records_with_success_false(self):
        specs = generate_starter_products(niche="beauty")[:1]
        router = type("R", (), {})()
        router.execute = lambda cap, params: _fail("nope")
        with patch(
            "engines.store_setup.product_seeder._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.product_seeder.record_writeback",
        ) as record_mock:
            apply_starter_products(specs)
        kwargs = record_mock.call_args.kwargs
        assert kwargs["success"] is False
        assert "nope" in (kwargs["error"] or "")
