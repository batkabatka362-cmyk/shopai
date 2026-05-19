"""Tests for ``engines.store_setup.theme_palette``.

Generator produces a structured palette spec per niche;
applier persists it as a Shopify page (handle ``theme-palette``)
via the existing ``SHOPIFY_CREATE_PAGE`` adapter and records
via Pattern Z.

Coverage:
  1. Generator: every niche has all 6 semantic tokens.
  2. Generator: unknown niche falls back to general.
  3. Generator: contrast ratios are calculated + clamp to
     WCAG ranges.
  4. Generator: every shipped niche is WCAG AA-compliant.
  5. WCAG helpers: hex parse + luminance + contrast math.
  6. Renderer: empty spec -> empty string.
  7. Renderer: produces swatches + JSON spec for round-trip.
  8. Renderer: HTML-escapes content.
  9. Applier: empty -> short-circuit.
 10. Applier: success + Pattern Z recording.
 11. Applier: router_unavailable.
 12. Applier: adapter raise + rejection.
 13. store_id propagation.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.theme_palette import (
    _NICHE_PALETTES,
    _contrast,
    _hex_to_rgb,
    _relative_luminance,
    apply_palette,
    generate_palette,
    render_palette_html,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorTokens:

    def test_every_niche_has_six_semantic_slots(self):
        required = {
            "primary", "secondary", "accent",
            "background", "surface", "text",
        }
        for niche in _NICHE_PALETTES:
            spec = generate_palette(niche=niche)
            assert set(spec["tokens"].keys()) == required, (
                niche
            )

    def test_unknown_niche_falls_back_to_general(self):
        spec = generate_palette(niche="ufo_parts")
        assert spec["niche"] == "ufo_parts"
        # tokens match general's
        assert (
            spec["tokens"]
            == _NICHE_PALETTES["general"]
        )

    def test_empty_niche_falls_back(self):
        spec = generate_palette(niche="")
        assert (
            spec["tokens"] == _NICHE_PALETTES["general"]
        )
        spec = generate_palette(niche=None)  # type: ignore[arg-type]
        assert (
            spec["tokens"] == _NICHE_PALETTES["general"]
        )

    def test_all_token_values_are_hex(self):
        for niche in _NICHE_PALETTES:
            spec = generate_palette(niche=niche)
            for name, value in spec["tokens"].items():
                assert value.startswith("#"), (niche, name)
                assert len(value) == 7, (niche, name)


class TestGeneratorContrast:

    def test_contrast_dict_present(self):
        spec = generate_palette(niche="beauty")
        assert set(spec["contrast"].keys()) == {
            "primary_on_background",
            "text_on_background",
            "primary_on_surface",
            "text_on_surface",
        }

    def test_every_shipped_niche_passes_wcag_aa(self):
        """Every default palette must clear AA (4.5:1) at
        minimum -- accessibility is non-negotiable for a
        product that's claiming 'autonomous merchant'.
        """
        for niche in _NICHE_PALETTES:
            spec = generate_palette(niche=niche)
            assert spec["wcag_compliant_aa"] is True, (
                niche, spec["contrast"]
            )

    def test_high_contrast_palettes_clear_aaa(self):
        # Fashion uses black-on-white, definitely AAA.
        spec = generate_palette(niche="fashion")
        assert spec["wcag_compliant_aaa"] is True

    def test_contrast_values_in_range(self):
        spec = generate_palette(niche="beauty")
        for value in spec["contrast"].values():
            # WCAG ratios live in [1.0, 21.0]
            assert 1.0 <= value <= 21.0


# ── WCAG primitives ──────────────────────────────────────────


class TestHexToRGB:

    def test_basic_hex(self):
        assert _hex_to_rgb("#FFFFFF") == (255, 255, 255)
        assert _hex_to_rgb("#000000") == (0, 0, 0)
        assert _hex_to_rgb("FF8800") == (255, 136, 0)

    def test_invalid_returns_black(self):
        assert _hex_to_rgb("") == (0, 0, 0)
        assert _hex_to_rgb("not-hex") == (0, 0, 0)
        assert _hex_to_rgb("#FFF") == (0, 0, 0)  # short form
        assert _hex_to_rgb("#GGGGGG") == (0, 0, 0)
        assert _hex_to_rgb(None) == (0, 0, 0)  # type: ignore[arg-type]


class TestContrast:

    def test_black_on_white_is_21(self):
        ratio = _contrast("#000000", "#FFFFFF")
        # Known WCAG value: 21:1 (with 0.05 offset rounding
        # noise the formula yields exactly 21.0)
        assert ratio == 21.0

    def test_same_color_is_1(self):
        assert _contrast("#888888", "#888888") == 1.0
        assert _contrast("#FF0000", "#FF0000") == 1.0

    def test_order_independent(self):
        a = _contrast("#000000", "#FFFFFF")
        b = _contrast("#FFFFFF", "#000000")
        assert a == b

    def test_known_failure_case(self):
        """Pale grey on white: below AA -- this is the
        contrast level the audit must refuse."""
        ratio = _contrast("#CCCCCC", "#FFFFFF")
        assert ratio < 4.5  # below AA


class TestLuminance:

    def test_white_max(self):
        # White luminance == 1.0
        assert _relative_luminance((255, 255, 255)) == 1.0

    def test_black_zero(self):
        assert _relative_luminance((0, 0, 0)) == 0.0


# ── Renderer ──────────────────────────────────────────────────


class TestRenderer:

    def test_empty_spec(self):
        assert render_palette_html({}) == ""
        assert render_palette_html(None) == ""  # type: ignore[arg-type]
        assert render_palette_html({"niche": "x"}) == ""

    def test_renders_swatches(self):
        spec = generate_palette(niche="beauty")
        html_out = render_palette_html(spec)
        assert "<section class=\"palette\">" in html_out
        # Each token -> a swatch
        for name in spec["tokens"]:
            assert f"{name}:" in html_out

    def test_renders_compliance_line(self):
        spec = generate_palette(niche="fashion")
        html_out = render_palette_html(spec)
        # Fashion clears AAA
        assert "AAA-compliant" in html_out

    def test_json_round_trip(self):
        """The <pre> JSON block must be the spec itself so a
        future theme-settings-write adapter can re-parse
        deterministically."""
        spec = generate_palette(niche="beauty")
        html_out = render_palette_html(spec)
        # Find the JSON block + ensure parseable
        start = html_out.find("<pre")
        end = html_out.find("</pre>", start)
        assert start > 0 and end > start
        # Extract JSON content (decode HTML entities back)
        content = html_out[
            html_out.find(">", start) + 1:end
        ]
        # Roundtripping through html.escape -> json.loads
        # requires unescaping &quot; etc.
        import html as _html
        parsed = json.loads(_html.unescape(content))
        assert parsed["tokens"] == spec["tokens"]
        assert parsed["niche"] == spec["niche"]

    def test_escapes_user_content(self):
        spec = {
            "niche": "<script>alert(1)</script>",
            "tokens": {"primary": "#000"},
            "contrast": {},
            "wcag_compliant_aa": False,
            "wcag_compliant_aaa": False,
        }
        html_out = render_palette_html(spec)
        assert "<script>" not in html_out
        assert "&lt;script&gt;" in html_out


# ── Applier ──────────────────────────────────────────────────


class TestApplierEmpty:

    def test_empty_spec(self):
        out = apply_palette({})
        assert out["applied"] is False
        assert out["error"] == "no_palette_spec"

    def test_non_dict(self):
        out = apply_palette(None)  # type: ignore[arg-type]
        assert out["applied"] is False

    def test_spec_without_tokens(self):
        out = apply_palette({"niche": "beauty"})
        assert out["applied"] is False


class TestApplierSuccess:

    def test_pushes_via_create_page(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_palette(niche="beauty")
        with patch(
            "engines.store_setup.theme_palette._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.theme_palette."
            "record_writeback",
        ) as record_mock:
            out = apply_palette(spec)
        assert out["applied"] is True
        assert out["handle"] == "theme-palette"
        params = router.execute.call_args.args[1]
        assert params["title"] == "Theme Palette"
        assert params["handle"] == "theme-palette"
        assert "palette" in params["body_html"]
        assert params["published"] is True
        record_mock.assert_called_once()
        assert (
            record_mock.call_args.kwargs["success"] is True
        )


class TestApplierFailureModes:

    def test_router_unavailable_records_failure(self):
        spec = generate_palette(niche="tech")
        with patch(
            "engines.store_setup.theme_palette._get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.theme_palette."
            "record_writeback",
        ) as record_mock:
            out = apply_palette(spec)
        assert out["applied"] is False
        assert out["error"] == "router_unavailable"
        record_mock.assert_called_once()
        assert (
            record_mock.call_args.kwargs["success"] is False
        )

    def test_adapter_rejection(self):
        router = MagicMock()
        router.execute.return_value = _fail("handle taken")
        spec = generate_palette(niche="tech")
        with patch(
            "engines.store_setup.theme_palette._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.theme_palette."
            "record_writeback",
        ):
            out = apply_palette(spec)
        assert out["applied"] is False
        assert "handle taken" in out["error"]

    def test_adapter_raise(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        spec = generate_palette(niche="tech")
        with patch(
            "engines.store_setup.theme_palette._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.theme_palette."
            "record_writeback",
        ):
            out = apply_palette(spec)
        assert out["applied"] is False
        assert "network" in out["error"]


class TestStoreIdPropagation:

    def test_store_id_recorded(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_palette(niche="beauty")
        with patch(
            "engines.store_setup.theme_palette._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.theme_palette."
            "record_writeback",
        ) as record_mock:
            apply_palette(spec, store_id="store-a")
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
