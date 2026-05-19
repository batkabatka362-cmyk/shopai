"""Tests for ``engines.store_setup.shipping_zones``.

Generator produces niche-aware shipping zone + rate spec;
applier persists as a Shopify page.

Coverage:
  1. Generator: empty store_name -> empty dict.
  2. Generator: 2 zones (domestic + international) per
     niche.
  3. Generator: each zone has zone_name, countries,
     rates, free_shipping_threshold_usd.
  4. Generator: each rate has name + weight_max_g +
     price_usd + delivery_days.
  5. Generator: niche-specific tuning:
     - food has refrigerated + frozen rate options
     - jewelry has insured + signature rates
     - home has white-glove rate
     - tech has insurance note
  6. Generator: free_shipping_threshold matches AOV
     expectations.
  7. Generator: international threshold = 2x domestic.
  8. Generator: every niche resolves.
  9. Generator: operator_notes carries niche-specific
     advice (cold_chain for food, white_glove for home,
     etc.).
 10. Renderer: empty -> empty.
 11. Renderer: produces zone sections + rate tables +
     operator notes.
 12. Renderer: HTML-escapes content.
 13. Applier: empty short-circuit.
 14. Applier: success + Pattern Z.
 15. Applier: router_unavailable / rejection / raise.
 16. store_id propagation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.shipping_zones import (
    _NICHE_RATES,
    apply_shipping_zones,
    generate_shipping_zone_recommendations,
    render_shipping_html,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_shipping_zone_recommendations(
            store_name="",
        ) == {}
        assert generate_shipping_zone_recommendations(
            store_name="   ",
        ) == {}
        assert generate_shipping_zone_recommendations(
            store_name=None,
        ) == {}


class TestGeneratorShape:

    def test_two_zones_per_niche(self):
        for niche in _NICHE_RATES:
            spec = generate_shipping_zone_recommendations(
                store_name="Acme", niche=niche,
            )
            assert len(spec["zones"]) == 2, niche
            assert (
                spec["zones"][0]["zone_name"]
                == "Domestic (US)"
            )
            assert (
                spec["zones"][1]["zone_name"]
                == "International"
            )

    def test_each_zone_has_full_shape(self):
        for niche in _NICHE_RATES:
            spec = generate_shipping_zone_recommendations(
                store_name="Acme", niche=niche,
            )
            for zone in spec["zones"]:
                assert zone["zone_name"], niche
                assert zone["countries"], niche
                assert isinstance(zone["rates"], list)
                assert len(zone["rates"]) >= 1, (
                    niche, zone["zone_name"],
                )
                assert (
                    zone["free_shipping_threshold_usd"]
                    >= 0
                )

    def test_each_rate_has_full_shape(self):
        for niche in _NICHE_RATES:
            spec = generate_shipping_zone_recommendations(
                store_name="Acme", niche=niche,
            )
            for zone in spec["zones"]:
                for r in zone["rates"]:
                    assert r["name"], niche
                    assert r["weight_max_g"] > 0
                    assert r["price_usd"] > 0
                    assert r["delivery_days"]

    def test_every_niche_resolves(self):
        for niche in (
            "beauty", "fashion", "tech", "home", "food",
            "pets", "fitness", "jewelry", "outdoor",
            "baby", "general", "ufo_parts",
        ):
            spec = generate_shipping_zone_recommendations(
                store_name="Acme", niche=niche,
            )
            assert spec["zones"]


class TestNicheSpecific:

    def test_food_has_refrigerated_rate(self):
        spec = generate_shipping_zone_recommendations(
            store_name="Acme", niche="food",
        )
        domestic_rates = spec["zones"][0]["rates"]
        names = {r["name"] for r in domestic_rates}
        assert any(
            "refrigerated" in n.lower() for n in names
        )
        assert any(
            "frozen" in n.lower() for n in names
        )

    def test_jewelry_has_insured_signature(self):
        spec = generate_shipping_zone_recommendations(
            store_name="Acme", niche="jewelry",
        )
        domestic_rates = spec["zones"][0]["rates"]
        for r in domestic_rates:
            assert "insured" in r["name"].lower()
            assert "signature" in r["name"].lower()

    def test_home_has_white_glove(self):
        spec = generate_shipping_zone_recommendations(
            store_name="Acme", niche="home",
        )
        names = {
            r["name"]
            for r in spec["zones"][0]["rates"]
        }
        assert any(
            "white-glove" in n.lower() for n in names
        )

    def test_food_has_cold_chain_note(self):
        spec = generate_shipping_zone_recommendations(
            store_name="Acme", niche="food",
        )
        notes = spec["operator_notes"]
        assert "cold_chain" in notes
        assert "temperature-controlled" in notes[
            "cold_chain"
        ].lower()

    def test_jewelry_has_insurance_required(self):
        spec = generate_shipping_zone_recommendations(
            store_name="Acme", niche="jewelry",
        )
        notes = spec["operator_notes"]
        assert "insurance" in notes
        assert "REQUIRED" in notes["insurance"]


class TestThresholds:

    def test_international_2x_domestic(self):
        for niche in _NICHE_RATES:
            spec = generate_shipping_zone_recommendations(
                store_name="Acme", niche=niche,
            )
            dom = spec["zones"][0][
                "free_shipping_threshold_usd"
            ]
            intl = spec["zones"][1][
                "free_shipping_threshold_usd"
            ]
            assert intl == dom * 2, niche

    def test_food_lower_threshold(self):
        """Food has lower AOV; threshold lower than home."""
        food = generate_shipping_zone_recommendations(
            store_name="Acme", niche="food",
        )
        home = generate_shipping_zone_recommendations(
            store_name="Acme", niche="home",
        )
        assert (
            food["zones"][0]["free_shipping_threshold_usd"]
            < home["zones"][0]["free_shipping_threshold_usd"]
        )

    def test_jewelry_high_threshold(self):
        spec = generate_shipping_zone_recommendations(
            store_name="Acme", niche="jewelry",
        )
        # Jewelry has high AOV; threshold $100+
        assert (
            spec["zones"][0]["free_shipping_threshold_usd"]
            >= 100
        )


# ── Renderer ──────────────────────────────────────────────────


class TestRenderer:

    def test_empty_spec(self):
        assert render_shipping_html({}) == ""
        assert render_shipping_html(None) == ""  # type: ignore[arg-type]

    def test_produces_zone_sections(self):
        spec = generate_shipping_zone_recommendations(
            store_name="Acme Beauty", niche="beauty",
        )
        html_out = render_shipping_html(spec)
        assert "Acme Beauty" in html_out
        assert "Domestic" in html_out
        assert "International" in html_out
        # Rate table per zone
        assert html_out.count("<table") == 2
        # Operator notes section
        assert "Operator Notes" in html_out

    def test_escapes_user_content(self):
        spec = {
            "store_name": "<script>x</script>",
            "niche": "beauty",
            "zones": [
                {
                    "zone_name": "<b>Z</b>",
                    "countries": ["<b>US</b>"],
                    "rates": [
                        {
                            "name": "<i>R</i>",
                            "weight_max_g": 100,
                            "price_usd": 5.0,
                            "delivery_days": "<em>1</em>",
                        },
                    ],
                    "free_shipping_threshold_usd": 50,
                },
            ],
            "operator_notes": {},
        }
        html_out = render_shipping_html(spec)
        assert "<script>x</script>" not in html_out
        assert "<b>Z</b>" not in html_out
        assert "&lt;" in html_out


# ── Applier ──────────────────────────────────────────────────


class TestApplierEmpty:

    def test_no_spec(self):
        out = apply_shipping_zones({})
        assert out["applied"] is False
        assert out["error"] == "no_shipping_spec"

    def test_non_dict(self):
        out = apply_shipping_zones(None)  # type: ignore[arg-type]
        assert out["applied"] is False

    def test_spec_without_zones(self):
        out = apply_shipping_zones({"store_name": "Acme"})
        assert out["applied"] is False


class TestApplierSuccess:

    def test_pushes_via_create_page(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_shipping_zone_recommendations(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.shipping_zones."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.shipping_zones."
            "record_writeback",
        ) as record_mock:
            out = apply_shipping_zones(spec)
        assert out["applied"] is True
        assert out["handle"] == "shipping-zones"
        params = router.execute.call_args.args[1]
        assert params["title"] == "Shipping Zones & Rates"
        assert params["handle"] == "shipping-zones"
        kwargs = record_mock.call_args.kwargs
        assert kwargs["success"] is True
        assert kwargs["metrics"]["zone_count"] == 2
        assert kwargs["metrics"]["niche"] == "beauty"


class TestApplierFailureModes:

    def test_router_unavailable(self):
        spec = generate_shipping_zone_recommendations(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.shipping_zones."
            "_get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.shipping_zones."
            "record_writeback",
        ) as record_mock:
            out = apply_shipping_zones(spec)
        assert out["applied"] is False
        assert out["error"] == "router_unavailable"
        assert (
            record_mock.call_args.kwargs["success"]
            is False
        )

    def test_adapter_rejection(self):
        router = MagicMock()
        router.execute.return_value = _fail("handle taken")
        spec = generate_shipping_zone_recommendations(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.shipping_zones."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.shipping_zones."
            "record_writeback",
        ):
            out = apply_shipping_zones(spec)
        assert out["applied"] is False
        assert "handle taken" in out["error"]

    def test_adapter_raise(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        spec = generate_shipping_zone_recommendations(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.shipping_zones."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.shipping_zones."
            "record_writeback",
        ):
            out = apply_shipping_zones(spec)
        assert out["applied"] is False
        assert "network" in out["error"]


class TestStoreIdPropagation:

    def test_store_id_recorded(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_shipping_zone_recommendations(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.shipping_zones."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.shipping_zones."
            "record_writeback",
        ) as record_mock:
            apply_shipping_zones(spec, store_id="store-a")
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
