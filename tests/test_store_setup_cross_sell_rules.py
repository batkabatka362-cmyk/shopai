"""Tests for ``engines.store_setup.cross_sell_rules``.

Niche-aware cross-sell + upsell rule templates. Each rule
is a ``{trigger, suggestion, location, rationale}`` triplet
ready for paste into Loox / Stamped / Recommendz OR a
future ``cross_sell`` engine.

Coverage:
  1. Generator: empty store_name -> empty dict.
  2. Generator: at least 1 rule per niche.
  3. Generator: each rule has name + trigger +
     suggestion + location + rationale.
  4. Generator: trigger.context is a known location enum.
  5. Generator: suggestion.strategy is a known enum.
  6. Generator: every niche resolves.
  7. Generator: unknown niche -> general.
  8. Generator: deep-copy semantics.
  9. Generator: tag filter conditions use the
     `family:value` convention.
 10. Renderer: empty / non-dict.
 11. Renderer: one section per rule with JSON trigger +
     suggestion.
 12. Renderer: HTML-escapes content.
 13. Applier: empty short-circuit.
 14. Applier: success + Pattern Z metrics.
 15. Applier: router_unavailable / rejection / raise.
 16. store_id propagation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.cross_sell_rules import (
    _LOCATIONS,
    _NICHE_RULES,
    _STRATEGIES,
    apply_rules,
    generate_cross_sell_rules,
    render_rules_html,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_cross_sell_rules(
            store_name="",
        ) == {}
        assert generate_cross_sell_rules(
            store_name="   ",
        ) == {}
        assert generate_cross_sell_rules(
            store_name=None,
        ) == {}


class TestGeneratorShape:

    def test_at_least_one_rule_per_niche(self):
        for niche in _NICHE_RULES:
            spec = generate_cross_sell_rules(
                store_name="Acme", niche=niche,
            )
            assert len(spec["rules"]) >= 1, niche

    def test_every_rule_has_full_shape(self):
        for niche in _NICHE_RULES:
            spec = generate_cross_sell_rules(
                store_name="Acme", niche=niche,
            )
            for rule in spec["rules"]:
                assert rule["name"], niche
                assert "trigger" in rule, niche
                assert "suggestion" in rule, niche
                assert rule["location"], niche
                assert rule["rationale"], niche

    def test_every_niche_resolves(self):
        for niche in (
            "beauty", "fashion", "tech", "home", "food",
            "pets", "fitness", "jewelry", "outdoor",
            "baby", "general", "ufo_parts",
        ):
            spec = generate_cross_sell_rules(
                store_name="Acme", niche=niche,
            )
            assert spec["rules"]

    def test_unknown_niche_falls_back(self):
        spec = generate_cross_sell_rules(
            store_name="Acme", niche="ufo_parts",
        )
        general_count = len(_NICHE_RULES["general"])
        assert len(spec["rules"]) == general_count


class TestEnumValidation:

    def test_locations_are_known(self):
        for niche in _NICHE_RULES:
            spec = generate_cross_sell_rules(
                store_name="Acme", niche=niche,
            )
            for rule in spec["rules"]:
                assert rule["location"] in _LOCATIONS, (
                    niche, rule["location"],
                )

    def test_strategies_are_known(self):
        for niche in _NICHE_RULES:
            spec = generate_cross_sell_rules(
                store_name="Acme", niche=niche,
            )
            for rule in spec["rules"]:
                strategy = rule["suggestion"].get(
                    "strategy",
                )
                assert strategy in _STRATEGIES, (
                    niche, rule["name"], strategy,
                )

    def test_trigger_contexts_are_known(self):
        """Trigger.context values are operator-facing
        labels (PDP, Cart drawer, etc.) -- verify they
        match the location-style strings."""
        valid_contexts = {
            "PDP", "Cart drawer", "Cart page",
            "Post-purchase", "Email follow-up",
            "Collection page",
        }
        for niche in _NICHE_RULES:
            spec = generate_cross_sell_rules(
                store_name="Acme", niche=niche,
            )
            for rule in spec["rules"]:
                ctx = rule["trigger"].get("context")
                assert ctx in valid_contexts, (
                    niche, rule["name"], ctx,
                )


class TestTagConventionConsistency:
    """Tag filters in triggers + suggestions follow the
    `family:value` Shopify-native convention from
    `tag_library`."""

    def test_tag_filters_use_family_value(self):
        for niche in _NICHE_RULES:
            spec = generate_cross_sell_rules(
                store_name="Acme", niche=niche,
            )
            for rule in spec["rules"]:
                for which in ("trigger", "suggestion"):
                    f = rule[which].get("filter") or {}
                    tag = f.get("tag")
                    if not tag:
                        continue
                    # Either bare ("sale") or family:value
                    if ":" in tag:
                        family, _, value = (
                            tag.partition(":")
                        )
                        assert family, (niche, tag)
                        assert value, (niche, tag)


class TestDeepCopySemantics:

    def test_caller_mutation_doesnt_poison(self):
        spec = generate_cross_sell_rules(
            store_name="Acme", niche="beauty",
        )
        # Mutate the trigger of the first rule
        spec["rules"][0]["trigger"]["context"] = (
            "TAMPERED"
        )
        # Re-fetch; should NOT see the mutation
        spec2 = generate_cross_sell_rules(
            store_name="Acme", niche="beauty",
        )
        assert (
            spec2["rules"][0]["trigger"]["context"]
            != "TAMPERED"
        )


# ── Renderer ──────────────────────────────────────────────────


class TestRenderer:

    def test_empty_spec(self):
        assert render_rules_html({}) == ""
        assert render_rules_html(None) == ""  # type: ignore[arg-type]
        assert (
            render_rules_html({"store_name": "Acme"}) == ""
        )

    def test_one_section_per_rule(self):
        spec = generate_cross_sell_rules(
            store_name="Acme Beauty", niche="beauty",
        )
        html_out = render_rules_html(spec)
        assert "Acme Beauty" in html_out
        # Count h3 Trigger/Suggestion headings -- exact
        # count, less ambiguous than nested class names.
        assert (
            html_out.count("<h3>Trigger</h3>")
            == len(spec["rules"])
        )
        assert (
            html_out.count("<h3>Suggestion</h3>")
            == len(spec["rules"])
        )

    def test_escapes_user_content(self):
        spec = {
            "store_name": "<script>x</script>",
            "niche": "beauty",
            "rules": [
                {
                    "name": "<b>r</b>",
                    "trigger": {"context": "PDP"},
                    "suggestion": {
                        "strategy": "tag_match",
                    },
                    "location": "PDP related-products",
                    "rationale": "x & y",
                },
            ],
        }
        html_out = render_rules_html(spec)
        assert "<script>x</script>" not in html_out
        assert "<b>r</b>" not in html_out
        assert "&lt;" in html_out


# ── Applier ──────────────────────────────────────────────────


class TestApplierEmpty:

    def test_no_spec(self):
        out = apply_rules({})
        assert out["applied"] is False
        assert out["error"] == "no_rules_spec"

    def test_non_dict(self):
        out = apply_rules(None)  # type: ignore[arg-type]
        assert out["applied"] is False

    def test_spec_without_rules(self):
        out = apply_rules({"store_name": "Acme"})
        assert out["applied"] is False


class TestApplierSuccess:

    def test_pushes_via_create_page(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_cross_sell_rules(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.cross_sell_rules."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.cross_sell_rules."
            "record_writeback",
        ) as record_mock:
            out = apply_rules(spec)
        assert out["applied"] is True
        assert out["handle"] == "cross-sell-rules"
        params = router.execute.call_args.args[1]
        assert (
            params["title"]
            == "Cross-Sell Recommendation Rules"
        )
        assert params["handle"] == "cross-sell-rules"
        kwargs = record_mock.call_args.kwargs
        assert kwargs["success"] is True
        assert kwargs["metrics"]["rule_count"] == 3
        assert kwargs["metrics"]["niche"] == "beauty"


class TestApplierFailureModes:

    def test_router_unavailable(self):
        spec = generate_cross_sell_rules(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.cross_sell_rules."
            "_get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.cross_sell_rules."
            "record_writeback",
        ) as record_mock:
            out = apply_rules(spec)
        assert out["applied"] is False
        assert out["error"] == "router_unavailable"
        assert (
            record_mock.call_args.kwargs["success"]
            is False
        )

    def test_adapter_rejection(self):
        router = MagicMock()
        router.execute.return_value = _fail("handle taken")
        spec = generate_cross_sell_rules(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.cross_sell_rules."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.cross_sell_rules."
            "record_writeback",
        ):
            out = apply_rules(spec)
        assert out["applied"] is False
        assert "handle taken" in out["error"]

    def test_adapter_raise(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        spec = generate_cross_sell_rules(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.cross_sell_rules."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.cross_sell_rules."
            "record_writeback",
        ):
            out = apply_rules(spec)
        assert out["applied"] is False
        assert "network" in out["error"]


class TestStoreIdPropagation:

    def test_store_id_recorded(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_cross_sell_rules(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.cross_sell_rules."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.cross_sell_rules."
            "record_writeback",
        ) as record_mock:
            apply_rules(spec, store_id="store-a")
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
