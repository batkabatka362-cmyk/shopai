"""Tests for ``engines.store_setup.locale_markets``.

Niche-aware market + currency / locale recommender.
Output is drop-in for ``SHOPIFY_CREATE_MARKET``.

Coverage:
  1. Empty store_name -> empty dict.
  2. Primary market defaults to US/USD/en.
  3. Override primary_market.
  4. Per-niche additional markets present + shaped.
  5. Niche-specific tuning:
     - beauty has UK + EU + AU
     - food domestic-only (Canada at most)
     - jewelry has UAE
     - tech has compatibility notes in rationale
  6. Every niche resolves.
  7. Each additional market has all fields.
  8. Country codes are 2-letter ISO.
  9. Currency codes are 3-letter ISO.
 10. Handoff: produces per-market kwargs ready for
     SHOPIFY_CREATE_MARKET.
 11. Handoff: regions list shape matches adapter expectation.
 12. Handoff: excludes primary market.
 13. Renderer: empty / non-dict.
 14. Renderer: primary + additional sections.
 15. Applier: empty short-circuit.
 16. Applier: success + Pattern Z.
 17. Applier: failure modes.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.locale_markets import (
    _DEFAULT_PRIMARY,
    _NICHE_MARKETS,
    apply_market_recommendations,
    generate_market_recommendations,
    hand_off_to_market_adapter,
    render_markets_html,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_market_recommendations(
            store_name="",
        ) == {}
        assert generate_market_recommendations(
            store_name="   ",
        ) == {}
        assert generate_market_recommendations(
            store_name=None,
        ) == {}


class TestPrimaryMarket:

    def test_default_primary_us(self):
        spec = generate_market_recommendations(
            store_name="Acme",
        )
        primary = spec["primary_market"]
        assert primary["name"] == "United States"
        assert primary["country_codes"] == ["US"]
        assert primary["currency"] == "USD"

    def test_override_primary(self):
        custom = {
            "name": "United Kingdom",
            "handle": "uk",
            "country_codes": ["GB"],
            "currency": "GBP",
            "locale": "en",
        }
        spec = generate_market_recommendations(
            store_name="Acme",
            primary_market=custom,
        )
        assert spec["primary_market"] == custom


class TestAdditionalMarkets:

    def test_every_niche_has_additional_markets(self):
        for niche in _NICHE_MARKETS:
            if not _NICHE_MARKETS[niche]:
                continue  # general has 1 (Canada)
            spec = generate_market_recommendations(
                store_name="Acme", niche=niche,
            )
            assert spec["additional_markets"]

    def test_every_market_has_full_shape(self):
        for niche in _NICHE_MARKETS:
            spec = generate_market_recommendations(
                store_name="Acme", niche=niche,
            )
            for m in spec["additional_markets"]:
                assert m["name"], niche
                assert m["handle"], niche
                assert isinstance(
                    m["country_codes"], list,
                )
                assert m["country_codes"], niche
                assert m["currency"], niche
                assert m["locale"], niche
                assert m["rationale"], niche
                assert m["when_to_open"], niche

    def test_every_niche_resolves(self):
        for niche in (
            "beauty", "fashion", "tech", "home", "food",
            "pets", "fitness", "jewelry", "outdoor",
            "baby", "general", "ufo_parts",
        ):
            spec = generate_market_recommendations(
                store_name="Acme", niche=niche,
            )
            # Spec is always present, possibly with
            # empty additional_markets for niches
            # without recommendations
            assert "primary_market" in spec


class TestNicheTuning:

    def test_beauty_has_eu_uk_au(self):
        spec = generate_market_recommendations(
            store_name="Acme", niche="beauty",
        )
        names = {
            m["name"] for m in spec["additional_markets"]
        }
        assert "United Kingdom" in names
        assert any("European" in n for n in names)
        assert "Australia" in names

    def test_food_is_domestic_or_canada_only(self):
        """Food has perishability + customs concerns;
        export markets are minimal."""
        spec = generate_market_recommendations(
            store_name="Acme", niche="food",
        )
        # Food should have at most Canada in
        # additional markets
        names = {
            m["name"] for m in spec["additional_markets"]
        }
        assert "European Union" not in names
        assert "Australia" not in names
        # Canada is the only allowed expansion
        if names:
            assert names.issubset({"Canada"})

    def test_jewelry_has_uae(self):
        spec = generate_market_recommendations(
            store_name="Acme", niche="jewelry",
        )
        names = {
            m["name"] for m in spec["additional_markets"]
        }
        assert any("Arab Emirates" in n for n in names)

    def test_tech_mentions_compatibility(self):
        spec = generate_market_recommendations(
            store_name="Acme", niche="tech",
        )
        # At least one rationale flags voltage / plug
        # / CE compatibility
        rationales = [
            m["rationale"].lower()
            for m in spec["additional_markets"]
        ]
        compat_terms = [
            "voltage", "plug", "ce", "fcc", "rohs",
        ]
        assert any(
            any(t in r for t in compat_terms)
            for r in rationales
        )

    def test_baby_mentions_safety_regs(self):
        spec = generate_market_recommendations(
            store_name="Acme", niche="baby",
        )
        rationales = [
            m["rationale"]
            for m in spec["additional_markets"]
        ]
        # Look for safety / standards / regulatory
        # mentions
        safety_terms = [
            "CPSA", "UKCA", "CE", "safety", "ACCC",
        ]
        assert any(
            any(t in r for t in safety_terms)
            for r in rationales
        )


class TestISOFormatting:

    def test_country_codes_are_2_letter(self):
        for niche in _NICHE_MARKETS:
            spec = generate_market_recommendations(
                store_name="Acme", niche=niche,
            )
            for m in spec["additional_markets"]:
                for c in m["country_codes"]:
                    assert len(c) == 2, (niche, c)
                    assert c == c.upper(), (niche, c)
                    assert c.isalpha(), (niche, c)

    def test_currency_codes_are_3_letter(self):
        for niche in _NICHE_MARKETS:
            spec = generate_market_recommendations(
                store_name="Acme", niche=niche,
            )
            for m in spec["additional_markets"]:
                cur = m["currency"]
                assert len(cur) == 3, (niche, cur)
                assert cur == cur.upper(), (niche, cur)
                assert cur.isalpha(), (niche, cur)


# ── Handoff ──────────────────────────────────────────────────


class TestHandoff:

    def test_excludes_primary(self):
        spec = generate_market_recommendations(
            store_name="Acme", niche="beauty",
        )
        kwargs_list = hand_off_to_market_adapter(spec)
        # Should equal number of additional markets
        assert (
            len(kwargs_list)
            == len(spec["additional_markets"])
        )

    def test_per_market_shape(self):
        spec = generate_market_recommendations(
            store_name="Acme", niche="beauty",
        )
        kwargs_list = hand_off_to_market_adapter(spec)
        for k in kwargs_list:
            assert "name" in k
            assert "handle" in k
            assert k["status"] == "active"
            assert "regions" in k
            assert isinstance(k["regions"], list)

    def test_regions_shape(self):
        """Each region must be
        ``{"country_code": "XX"}`` to match the
        SHOPIFY_CREATE_MARKET friendly call shape."""
        spec = generate_market_recommendations(
            store_name="Acme", niche="beauty",
        )
        kwargs_list = hand_off_to_market_adapter(spec)
        for k in kwargs_list:
            for region in k["regions"]:
                assert "country_code" in region
                assert len(region["country_code"]) == 2

    def test_empty_template(self):
        assert hand_off_to_market_adapter({}) == []
        assert hand_off_to_market_adapter(None) == []  # type: ignore[arg-type]
        # Template without additional_markets
        assert hand_off_to_market_adapter(
            {"primary_market": _DEFAULT_PRIMARY},
        ) == []


# ── Renderer ──────────────────────────────────────────────────


class TestRenderer:

    def test_empty_spec(self):
        assert render_markets_html({}) == ""
        assert render_markets_html(None) == ""  # type: ignore[arg-type]

    def test_renders_primary_block(self):
        spec = generate_market_recommendations(
            store_name="Acme Beauty", niche="beauty",
        )
        html_out = render_markets_html(spec)
        assert "Acme Beauty" in html_out
        assert "Primary Market" in html_out
        assert "USD" in html_out
        assert "Additional Markets" in html_out

    def test_renders_additional_per_market(self):
        spec = generate_market_recommendations(
            store_name="Acme", niche="beauty",
        )
        html_out = render_markets_html(spec)
        expected_count = len(spec["additional_markets"])
        # Each additional has its own h3
        assert html_out.count("<h3>") == expected_count


# ── Applier ──────────────────────────────────────────────────


class TestApplierEmpty:

    def test_no_spec(self):
        out = apply_market_recommendations({})
        assert out["applied"] is False
        assert out["error"] == "no_market_spec"

    def test_non_dict(self):
        out = apply_market_recommendations(None)  # type: ignore[arg-type]
        assert out["applied"] is False


class TestApplierSuccess:

    def test_pushes_via_create_page(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_market_recommendations(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.locale_markets."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.locale_markets."
            "record_writeback",
        ) as record_mock:
            out = apply_market_recommendations(spec)
        assert out["applied"] is True
        assert out["handle"] == "market-recommendations"
        params = router.execute.call_args.args[1]
        assert params["title"] == (
            "Market & Currency Recommendations"
        )
        kwargs = record_mock.call_args.kwargs
        assert kwargs["success"] is True
        assert (
            kwargs["metrics"]["additional_count"]
            == len(spec["additional_markets"])
        )


class TestApplierFailureModes:

    def test_router_unavailable(self):
        spec = generate_market_recommendations(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.locale_markets."
            "_get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.locale_markets."
            "record_writeback",
        ):
            out = apply_market_recommendations(spec)
        assert out["applied"] is False
        assert out["error"] == "router_unavailable"

    def test_adapter_rejection(self):
        router = MagicMock()
        router.execute.return_value = _fail("handle taken")
        spec = generate_market_recommendations(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.locale_markets."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.locale_markets."
            "record_writeback",
        ):
            out = apply_market_recommendations(spec)
        assert out["applied"] is False
        assert "handle taken" in out["error"]


class TestStoreIdPropagation:

    def test_store_id_recorded(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_market_recommendations(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.locale_markets."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.locale_markets."
            "record_writeback",
        ) as record_mock:
            apply_market_recommendations(
                spec, store_id="store-a",
            )
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
