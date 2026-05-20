"""Tests for ``engines.store_setup.announcement_bar``.

Generator produces niche-aware banner options; applier
persists them as a Shopify page (handle
``announcement-bar``) via ``SHOPIFY_CREATE_PAGE``. Records
via Pattern Z.

Coverage:
  1. Generator: empty store_name -> empty dict.
  2. Generator: 2+ bars per niche; full shape per bar.
  3. Generator: every shipped niche resolves.
  4. Generator: unknown niche falls back to general.
  5. Generator: messages under 60 chars (mobile-safe).
  6. Generator: tone field is one of the known categories.
  7. Generator: cta_url is a relative path (/...).
  8. Renderer: empty / non-dict.
  9. Renderer: produces one section per bar with operator
     metadata.
 10. Renderer: HTML-escapes user content.
 11. Applier: empty short-circuit.
 12. Applier: success + Pattern Z metrics.
 13. Applier: router_unavailable / rejection / raise.
 14. store_id propagation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.announcement_bar import (
    _NICHE_BARS,
    apply_bars,
    generate_announcement_bars,
    render_bars_html,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_announcement_bars(
            store_name="",
        ) == {}
        assert generate_announcement_bars(
            store_name="   ",
        ) == {}
        assert generate_announcement_bars(
            store_name=None,
        ) == {}


class TestGeneratorShape:

    def test_bars_per_niche(self):
        for niche in _NICHE_BARS:
            spec = generate_announcement_bars(
                store_name="Acme", niche=niche,
            )
            assert len(spec["bars"]) >= 2, niche

    def test_full_shape_per_bar(self):
        for niche in _NICHE_BARS:
            spec = generate_announcement_bars(
                store_name="Acme", niche=niche,
            )
            for bar in spec["bars"]:
                assert bar["message"], niche
                assert bar["cta_label"], niche
                assert bar["cta_url"], niche
                assert bar["tone"], niche
                assert bar["when_to_use"], niche

    def test_every_niche_resolves(self):
        for niche in (
            "beauty", "fashion", "tech", "home", "food",
            "pets", "fitness", "jewelry", "outdoor",
            "baby", "general", "ufo_parts",
        ):
            spec = generate_announcement_bars(
                store_name="Acme", niche=niche,
            )
            assert spec["bars"]

    def test_unknown_niche_falls_back_to_general(self):
        spec = generate_announcement_bars(
            store_name="Acme", niche="ufo_parts",
        )
        # general has 2 bars
        assert (
            len(spec["bars"]) == len(_NICHE_BARS["general"])
        )


class TestContentQuality:

    def test_messages_mobile_safe(self):
        """Mobile-truncation threshold is ~60 chars; every
        bar message should fit."""
        for niche in _NICHE_BARS:
            spec = generate_announcement_bars(
                store_name="Acme", niche=niche,
            )
            for bar in spec["bars"]:
                assert len(bar["message"]) <= 60, (
                    niche, bar["message"],
                )

    def test_tones_are_known_categories(self):
        """Each bar's tone should be one of the known
        operator-facing categories."""
        valid = {
            "shipping_threshold", "brand_claim",
            "first_order_promo", "new_collection",
            "subscription_promo", "feature_highlight",
        }
        for niche in _NICHE_BARS:
            spec = generate_announcement_bars(
                store_name="Acme", niche=niche,
            )
            for bar in spec["bars"]:
                assert bar["tone"] in valid, (
                    niche, bar["tone"],
                )

    def test_cta_url_is_relative_path(self):
        """All CTAs should be /collections/... or /pages/...
        so they work across domains."""
        for niche in _NICHE_BARS:
            spec = generate_announcement_bars(
                store_name="Acme", niche=niche,
            )
            for bar in spec["bars"]:
                assert bar["cta_url"].startswith("/"), (
                    niche, bar["cta_url"],
                )


# ── Renderer ──────────────────────────────────────────────────


class TestRenderer:

    def test_empty_spec(self):
        assert render_bars_html({}) == ""
        assert render_bars_html(None) == ""  # type: ignore[arg-type]
        assert render_bars_html({"store_name": "Acme"}) == ""

    def test_one_section_per_bar(self):
        spec = generate_announcement_bars(
            store_name="Acme", niche="beauty",
        )
        html_out = render_bars_html(spec)
        # Three beauty bars -> three sections
        assert (
            html_out.count("announcement-option") == (
                len(spec["bars"]) * 2  # class on h2 + p
            )
        ) or (
            html_out.count("<section class=\"announcement-option\">")
            == len(spec["bars"])
        )
        # Each "When to use" rendered
        for bar in spec["bars"]:
            assert "When to use" in html_out

    def test_escapes_user_content(self):
        spec = {
            "store_name": "<script>x</script>",
            "niche": "beauty",
            "bars": [
                {
                    "message": "<b>m</b>",
                    "cta_label": "<a>",
                    "cta_url": "/x",
                    "tone": "shipping_threshold",
                    "when_to_use": "x & y",
                },
            ],
        }
        html_out = render_bars_html(spec)
        assert "<script>x</script>" not in html_out
        assert "<b>m</b>" not in html_out
        assert "&lt;" in html_out


# ── Applier ──────────────────────────────────────────────────


class TestApplierEmpty:

    def test_no_spec(self):
        out = apply_bars({})
        assert out["applied"] is False
        assert out["error"] == "no_bars_spec"

    def test_non_dict(self):
        out = apply_bars(None)  # type: ignore[arg-type]
        assert out["applied"] is False

    def test_spec_without_bars(self):
        out = apply_bars({"store_name": "Acme"})
        assert out["applied"] is False


class TestApplierSuccess:

    def test_pushes_via_create_page(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_announcement_bars(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.announcement_bar."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.announcement_bar."
            "record_writeback",
        ) as record_mock:
            out = apply_bars(spec)
        assert out["applied"] is True
        assert out["handle"] == "announcement-bar"
        params = router.execute.call_args.args[1]
        assert params["title"] == "Announcement Bar"
        assert params["handle"] == "announcement-bar"
        # Pattern Z carries bar count
        kwargs = record_mock.call_args.kwargs
        assert kwargs["success"] is True
        assert kwargs["metrics"]["bar_count"] == 3
        assert kwargs["metrics"]["niche"] == "beauty"


class TestApplierFailureModes:

    def test_router_unavailable(self):
        spec = generate_announcement_bars(store_name="Acme")
        with patch(
            "engines.store_setup.announcement_bar."
            "_get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.announcement_bar."
            "record_writeback",
        ) as record_mock:
            out = apply_bars(spec)
        assert out["applied"] is False
        assert out["error"] == "router_unavailable"
        assert (
            record_mock.call_args.kwargs["success"] is False
        )

    def test_adapter_rejection(self):
        router = MagicMock()
        router.execute.return_value = _fail("handle taken")
        spec = generate_announcement_bars(store_name="Acme")
        with patch(
            "engines.store_setup.announcement_bar."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.announcement_bar."
            "record_writeback",
        ):
            out = apply_bars(spec)
        assert out["applied"] is False
        assert "handle taken" in out["error"]

    def test_adapter_raise(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        spec = generate_announcement_bars(store_name="Acme")
        with patch(
            "engines.store_setup.announcement_bar."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.announcement_bar."
            "record_writeback",
        ):
            out = apply_bars(spec)
        assert out["applied"] is False
        assert "network" in out["error"]


class TestStoreIdPropagation:

    def test_store_id_recorded(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_announcement_bars(store_name="Acme")
        with patch(
            "engines.store_setup.announcement_bar."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.announcement_bar."
            "record_writeback",
        ) as record_mock:
            apply_bars(spec, store_id="store-a")
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
