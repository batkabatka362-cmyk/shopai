"""Tests for
``engines.store_setup.support_response_templates``.

Niche-aware canned customer-service response templates.
Operator-facing (vs ``support_kb`` which generates a
storefront Q&A page).

Coverage:
  1. Empty store_name -> empty dict.
  2. 8+ universal responses always present.
  3. Niche-specific stack on top.
  4. Every response has trigger + subject + body +
     tone + next_action.
  5. Every niche resolves.
  6. Unknown niche falls back to general
     (universal-only).
  7. Niche-specific responses surface (resize for
     jewelry, allergens for food/beauty, etc.)
  8. Liquid placeholders preserved (first_name +
     order.number).
  9. Renderer: empty / non-dict.
 10. Renderer: produces sections per response.
 11. Renderer: HTML escape.
 12. Applier: empty short-circuit.
 13. Applier: success + Pattern Z.
 14. Applier: router_unavailable / rejection / raise.
 15. store_id propagation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.support_response_templates import (
    _NICHE_RESPONSES,
    _UNIVERSAL_RESPONSES,
    apply_support_responses,
    generate_support_responses,
    render_responses_html,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_support_responses(
            store_name="",
        ) == {}
        assert generate_support_responses(
            store_name="   ",
        ) == {}
        assert generate_support_responses(
            store_name=None,
        ) == {}


class TestGeneratorShape:

    def test_universal_responses_present(self):
        spec = generate_support_responses(
            store_name="Acme", niche="general",
        )
        # General niche has 0 niche-specific entries
        assert (
            len(spec["responses"])
            == len(_UNIVERSAL_RESPONSES)
        )
        # Universal count is at least 8
        assert len(_UNIVERSAL_RESPONSES) >= 8

    def test_niche_stacks_on_universal(self):
        spec = generate_support_responses(
            store_name="Acme", niche="beauty",
        )
        assert (
            len(spec["responses"])
            == len(_UNIVERSAL_RESPONSES)
            + len(_NICHE_RESPONSES["beauty"])
        )

    def test_every_response_has_full_shape(self):
        for niche in _NICHE_RESPONSES:
            spec = generate_support_responses(
                store_name="Acme", niche=niche,
            )
            for r in spec["responses"]:
                assert r["trigger"], niche
                assert r["subject"], niche
                assert r["body"], niche
                assert r["tone"], niche
                assert r["next_action"], niche

    def test_every_niche_resolves(self):
        for niche in (
            "beauty", "fashion", "tech", "home", "food",
            "pets", "fitness", "jewelry", "outdoor",
            "baby", "general", "ufo_parts",
        ):
            spec = generate_support_responses(
                store_name="Acme", niche=niche,
            )
            assert spec["responses"]


class TestNicheSpecific:

    def test_jewelry_has_resize(self):
        spec = generate_support_responses(
            store_name="Acme", niche="jewelry",
        )
        triggers = {r["trigger"] for r in spec["responses"]}
        assert any(
            "Resize" in t for t in triggers
        )

    def test_food_has_allergen(self):
        spec = generate_support_responses(
            store_name="Acme", niche="food",
        )
        triggers = {r["trigger"] for r in spec["responses"]}
        assert any(
            "Allergen" in t for t in triggers
        )

    def test_beauty_has_sensitive_skin(self):
        spec = generate_support_responses(
            store_name="Acme", niche="beauty",
        )
        triggers = {r["trigger"] for r in spec["responses"]}
        assert any(
            "Sensitive" in t or "sensitive" in t.lower()
            for t in triggers
        )

    def test_baby_has_size_swap(self):
        spec = generate_support_responses(
            store_name="Acme", niche="baby",
        )
        triggers = {r["trigger"] for r in spec["responses"]}
        assert any(
            "swap" in t.lower() or "grew out" in t.lower()
            for t in triggers
        )

    def test_unknown_niche_falls_back(self):
        spec = generate_support_responses(
            store_name="Acme", niche="ufo_parts",
        )
        # general has 0 niche-specific
        assert (
            len(spec["responses"])
            == len(_UNIVERSAL_RESPONSES)
        )


class TestLiquidPlaceholders:

    def test_first_name_placeholder_present(self):
        spec = generate_support_responses(
            store_name="Acme",
        )
        # Most response bodies start with "Hi {{first_name}}"
        for r in spec["responses"]:
            # Not every response has first_name, but most do.
            # Find at least one universal that does.
            pass
        # At least 5 of the universal responses use first_name
        with_fn = sum(
            1 for r in spec["responses"]
            if "{{first_name}}" in r["body"]
        )
        assert with_fn >= 5

    def test_order_number_placeholder_when_relevant(self):
        spec = generate_support_responses(
            store_name="Acme",
        )
        # At least the order-tracking + damage responses
        # reference order.number
        order_refs = sum(
            1 for r in spec["responses"]
            if "{{order.number}}" in r["body"]
            or "{{order.number}}" in r["subject"]
        )
        assert order_refs >= 3

    def test_store_name_placeholder(self):
        spec = generate_support_responses(
            store_name="Acme",
        )
        signoff_refs = sum(
            1 for r in spec["responses"]
            if "{{store.name}}" in r["body"]
        )
        # Most responses end with "{{store.name}} team"
        assert signoff_refs >= 5


# ── Renderer ──────────────────────────────────────────────────


class TestRenderer:

    def test_empty_spec(self):
        assert render_responses_html({}) == ""
        assert render_responses_html(None) == ""  # type: ignore[arg-type]

    def test_produces_sections_per_response(self):
        spec = generate_support_responses(
            store_name="Acme Beauty", niche="beauty",
        )
        html_out = render_responses_html(spec)
        assert "Acme Beauty" in html_out
        # One section per response (count h2 tags --
        # response triggers)
        expected_count = len(spec["responses"])
        h2_count = html_out.count("<h2>")
        assert h2_count == expected_count

    def test_escapes_user_content(self):
        spec = {
            "store_name": "<script>x</script>",
            "niche": "beauty",
            "responses": [
                {
                    "trigger": "<b>t</b>",
                    "subject": "x & y",
                    "body": "<i>body</i>",
                    "tone": "x",
                    "next_action": "y",
                },
            ],
        }
        html_out = render_responses_html(spec)
        assert "<script>x</script>" not in html_out
        assert "<b>t</b>" not in html_out
        assert "&lt;" in html_out


# ── Applier ──────────────────────────────────────────────────


class TestApplierEmpty:

    def test_no_spec(self):
        out = apply_support_responses({})
        assert out["applied"] is False
        assert out["error"] == "no_responses_spec"

    def test_non_dict(self):
        out = apply_support_responses(None)  # type: ignore[arg-type]
        assert out["applied"] is False

    def test_spec_without_responses(self):
        out = apply_support_responses(
            {"store_name": "Acme"},
        )
        assert out["applied"] is False


class TestApplierSuccess:

    def test_pushes_via_create_page(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_support_responses(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.support_response_templates."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.support_response_templates."
            "record_writeback",
        ) as record_mock:
            out = apply_support_responses(spec)
        assert out["applied"] is True
        assert out["handle"] == "customer-support-responses"
        params = router.execute.call_args.args[1]
        assert params["title"] == (
            "Customer Support Responses"
        )
        assert params["handle"] == (
            "customer-support-responses"
        )
        kwargs = record_mock.call_args.kwargs
        assert kwargs["success"] is True
        assert kwargs["metrics"]["niche"] == "beauty"
        assert (
            kwargs["metrics"]["response_count"]
            == len(spec["responses"])
        )


class TestApplierFailureModes:

    def test_router_unavailable(self):
        spec = generate_support_responses(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.support_response_templates."
            "_get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.support_response_templates."
            "record_writeback",
        ) as record_mock:
            out = apply_support_responses(spec)
        assert out["applied"] is False
        assert out["error"] == "router_unavailable"
        assert (
            record_mock.call_args.kwargs["success"]
            is False
        )

    def test_adapter_rejection(self):
        router = MagicMock()
        router.execute.return_value = _fail("handle taken")
        spec = generate_support_responses(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.support_response_templates."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.support_response_templates."
            "record_writeback",
        ):
            out = apply_support_responses(spec)
        assert out["applied"] is False
        assert "handle taken" in out["error"]

    def test_adapter_raise(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        spec = generate_support_responses(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.support_response_templates."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.support_response_templates."
            "record_writeback",
        ):
            out = apply_support_responses(spec)
        assert out["applied"] is False
        assert "network" in out["error"]


class TestStoreIdPropagation:

    def test_store_id_recorded(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_support_responses(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.support_response_templates."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.support_response_templates."
            "record_writeback",
        ) as record_mock:
            apply_support_responses(
                spec, store_id="store-a",
            )
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
