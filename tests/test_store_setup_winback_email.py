"""Tests for ``engines.store_setup.winback_email``.

3-step lapsed-customer reactivation sequence. Pairs with
the ``Lapsed (180d)`` segment from ``customer_segments``.

Coverage:
  1. Generator: empty store_name -> empty dict.
  2. Generator: all 3 variants present (soft, incentive,
     last_chance).
  3. Generator: every variant has subject + preheader +
     bodies + trigger.
  4. Generator: incentive variant carries incentive_code +
     incentive_pct when supplied.
  5. Generator: no-code fallback (incentive + last_chance
     ship with generic reward language).
  6. Generator: niche-specific subjects + openings.
  7. Generator: trigger days configurable per step.
  8. Generator: Liquid placeholders preserved.
  9. Generator: subject pct substitution works for common
     default percentages.
 10. Renderer: empty / non-dict.
 11. Renderer: 3 sections + trigger lines surface.
 12. Renderer: HTML-escapes content.
 13. Applier: empty / no templates short-circuit.
 14. Applier: success + Pattern Z metrics.
 15. Applier: router_unavailable / rejection / raise.
 16. store_id propagation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.winback_email import (
    _NICHE_OPENINGS,
    _NICHE_SUBJECTS,
    _subject_with_pct,
    apply_winback,
    generate_winback_sequence,
    render_winback_html,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_winback_sequence(
            store_name="",
        ) == {}
        assert generate_winback_sequence(
            store_name="   ",
        ) == {}
        assert generate_winback_sequence(
            store_name=None,
        ) == {}


class TestGeneratorShape:

    def test_three_variants_present(self):
        spec = generate_winback_sequence(
            store_name="Acme", niche="beauty",
        )
        for key in ("soft", "incentive", "last_chance"):
            assert key in spec["templates"], key

    def test_every_variant_has_full_shape(self):
        spec = generate_winback_sequence(
            store_name="Acme",
        )
        for key in ("soft", "incentive", "last_chance"):
            tmpl = spec["templates"][key]
            assert tmpl["subject"], key
            assert tmpl["preheader"], key
            assert tmpl["body_text"], key
            assert tmpl["body_html"], key
            assert tmpl["trigger"], key

    def test_liquid_placeholders_preserved(self):
        spec = generate_winback_sequence(
            store_name="Acme",
        )
        for key in ("soft", "incentive", "last_chance"):
            tmpl = spec["templates"][key]
            assert "{{first_name}}" in tmpl["body_text"]
            assert "{{first_name}}" in tmpl["body_html"]
            assert "{{shop.url}}" in tmpl["body_html"]


class TestNicheTone:

    def test_every_niche_resolves(self):
        for niche in (
            "beauty", "fashion", "tech", "home", "food",
            "pets", "fitness", "jewelry", "outdoor",
            "baby", "general", "ufo_parts",
        ):
            spec = generate_winback_sequence(
                store_name="Acme", niche=niche,
            )
            assert spec["templates"]["soft"]["body_text"]

    def test_distinct_subjects_per_niche(self):
        """At least most niches have category-specific
        soft subjects -- not all are the universal "we
        miss you" general default."""
        general_soft = _NICHE_SUBJECTS["general"][0]
        distinct = 0
        for niche in _NICHE_SUBJECTS:
            if niche == "general":
                continue
            if (
                _NICHE_SUBJECTS[niche][0] != general_soft
            ):
                distinct += 1
        # 10 specific niches; at least half should have
        # their own subject (the others share the
        # universal "we miss you" template by design).
        assert distinct >= 5, distinct

    def test_distinct_openings_per_niche(self):
        """Niche-specific openings shouldn't all duplicate
        the general fallback."""
        seen = set()
        for niche, opening in _NICHE_OPENINGS.items():
            if niche == "general":
                continue
            assert opening not in seen, niche
            seen.add(opening)

    def test_unknown_niche_falls_back(self):
        spec = generate_winback_sequence(
            store_name="Acme", niche="ufo_parts",
        )
        general_soft = _NICHE_SUBJECTS["general"][0]
        assert (
            spec["templates"]["soft"]["subject"]
            == general_soft
        )

    def test_niche_specific_body_cues(self):
        """Each niche surfaces a category-relevant phrase
        in the soft email."""
        cases = {
            "fashion": ("wardrobe", "season"),
            "fitness": ("training",),
            "pets": ("pet",),
            "baby": ("little one", "grown"),
            "outdoor": ("trail", "trip"),
        }
        for niche, snippets in cases.items():
            spec = generate_winback_sequence(
                store_name="Acme", niche=niche,
            )
            body = (
                spec["templates"]["soft"]["body_text"]
                .lower()
            )
            for snippet in snippets:
                if snippet.lower() in body:
                    break
            else:
                raise AssertionError(
                    f"niche={niche}: none of {snippets} in "
                    f"body: {body[:200]}",
                )


# ── Incentive integration ────────────────────────────────────


class TestIncentiveIntegration:

    def test_incentive_with_code_pct(self):
        spec = generate_winback_sequence(
            store_name="Acme",
            niche="beauty",
            incentive_code="COMEBACK20",
            incentive_pct=20,
        )
        inc = spec["templates"]["incentive"]
        assert "COMEBACK20" in inc["body_text"]
        assert "20%" in inc["body_text"]
        assert "20%" in inc["preheader"]
        # Beauty soft is "20% off your comeback"; subject
        # substitution should make it match the pct
        assert "20%" in inc["subject"]
        assert inc["incentive_code"] == "COMEBACK20"
        assert inc["incentive_pct"] == 20

    def test_incentive_without_code(self):
        spec = generate_winback_sequence(
            store_name="Acme", niche="beauty",
        )
        inc = spec["templates"]["incentive"]
        assert "COMEBACK" not in inc["body_text"]
        # Generic reward language
        assert "in your account" in inc["body_text"].lower()
        assert inc["incentive_code"] is None
        assert inc["incentive_pct"] is None

    def test_last_chance_with_code(self):
        spec = generate_winback_sequence(
            store_name="Acme",
            niche="fashion",
            last_chance_code="FINAL30",
            last_chance_pct=30,
        )
        lc = spec["templates"]["last_chance"]
        assert "FINAL30" in lc["body_text"]
        assert "30%" in lc["body_text"]
        # Fashion last_chance is "30% off, then we lose"
        # -- substitution should preserve the 30%
        assert "30%" in lc["subject"]
        assert lc["incentive_code"] == "FINAL30"

    def test_codes_uppercased(self):
        spec = generate_winback_sequence(
            store_name="Acme",
            incentive_code="comeback20",
            incentive_pct=20,
            last_chance_code="final30",
            last_chance_pct=30,
        )
        assert (
            spec["templates"]["incentive"][
                "incentive_code"
            ] == "COMEBACK20"
        )
        assert (
            spec["templates"]["last_chance"][
                "incentive_code"
            ] == "FINAL30"
        )

    def test_zero_pct_ignored(self):
        """Zero pct = no real incentive; falls back."""
        spec = generate_winback_sequence(
            store_name="Acme",
            incentive_code="COMEBACK0",
            incentive_pct=0,
        )
        inc = spec["templates"]["incentive"]
        assert "0%" not in inc["body_text"]
        assert inc["incentive_pct"] is None


# ── Trigger days ─────────────────────────────────────────────


class TestTriggerDays:

    def test_default_triggers(self):
        spec = generate_winback_sequence(
            store_name="Acme",
        )
        soft_trigger = (
            spec["templates"]["soft"]["trigger"]
        )
        inc_trigger = (
            spec["templates"]["incentive"]["trigger"]
        )
        lc_trigger = (
            spec["templates"]["last_chance"]["trigger"]
        )
        assert "0 days" in soft_trigger
        assert "30 days" in inc_trigger
        assert "60 days" in lc_trigger

    def test_custom_triggers(self):
        spec = generate_winback_sequence(
            store_name="Acme",
            days_after_lapse_soft=5,
            days_after_lapse_incentive=45,
            days_after_lapse_last_chance=90,
        )
        assert (
            "5 days"
            in spec["templates"]["soft"]["trigger"]
        )
        assert (
            "45 days"
            in spec["templates"]["incentive"]["trigger"]
        )
        assert (
            "90 days"
            in spec["templates"]["last_chance"]["trigger"]
        )


# ── Subject pct substitution ─────────────────────────────────


class TestSubjectPctSubstitution:

    def test_replaces_common_defaults(self):
        for default in ("10% off", "15% off", "20% off",
                        "25% off", "30% off"):
            tmpl = f"Hey {{first}} -- {default} for you"
            out = _subject_with_pct(tmpl, 12)
            assert "12% off" in out
            assert default not in out

    def test_no_match_unchanged(self):
        tmpl = "Plain subject without percent"
        assert _subject_with_pct(tmpl, 20) == tmpl


# ── Renderer ──────────────────────────────────────────────────


class TestRenderer:

    def test_empty_spec(self):
        assert render_winback_html({}) == ""
        assert render_winback_html(None) == ""  # type: ignore[arg-type]
        assert (
            render_winback_html({
                "store_name": "Acme",
            }) == ""
        )

    def test_three_sections_render(self):
        spec = generate_winback_sequence(
            store_name="Acme", niche="beauty",
        )
        html_out = render_winback_html(spec)
        # All three labels surfaced
        assert "Soft" in html_out
        assert "Incentive" in html_out
        assert "Last Chance" in html_out
        # Trigger lines present
        assert "Lapsed" in html_out

    def test_escapes_user_content(self):
        spec = {
            "store_name": "<script>x</script>",
            "niche": "beauty",
            "templates": {
                "soft": {
                    "subject": "<b>S</b>",
                    "preheader": "x & y",
                    "body_text": "",
                    "body_html": "",
                    "trigger": "0 days",
                },
            },
        }
        html_out = render_winback_html(spec)
        assert "<script>x</script>" not in html_out
        assert "<b>S</b>" not in html_out
        assert "&lt;" in html_out


# ── Applier ──────────────────────────────────────────────────


class TestApplierEmpty:

    def test_no_spec(self):
        out = apply_winback({})
        assert out["applied"] is False
        assert out["error"] == "no_winback_spec"

    def test_non_dict(self):
        out = apply_winback(None)  # type: ignore[arg-type]
        assert out["applied"] is False

    def test_spec_without_templates(self):
        out = apply_winback({"store_name": "Acme"})
        assert out["applied"] is False


class TestApplierSuccess:

    def test_pushes_via_create_page(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_winback_sequence(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.winback_email."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.winback_email."
            "record_writeback",
        ) as record_mock:
            out = apply_winback(spec)
        assert out["applied"] is True
        assert out["handle"] == "winback-email"
        params = router.execute.call_args.args[1]
        assert params["title"] == "Win-Back Email Sequence"
        assert params["handle"] == "winback-email"
        kwargs = record_mock.call_args.kwargs
        assert kwargs["success"] is True
        assert kwargs["metrics"]["template_count"] == 3
        assert kwargs["metrics"]["niche"] == "beauty"


class TestApplierFailureModes:

    def test_router_unavailable(self):
        spec = generate_winback_sequence(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.winback_email."
            "_get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.winback_email."
            "record_writeback",
        ) as record_mock:
            out = apply_winback(spec)
        assert out["applied"] is False
        assert out["error"] == "router_unavailable"
        assert (
            record_mock.call_args.kwargs["success"]
            is False
        )

    def test_adapter_rejection(self):
        router = MagicMock()
        router.execute.return_value = _fail("handle taken")
        spec = generate_winback_sequence(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.winback_email."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.winback_email."
            "record_writeback",
        ):
            out = apply_winback(spec)
        assert out["applied"] is False
        assert "handle taken" in out["error"]

    def test_adapter_raise(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        spec = generate_winback_sequence(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.winback_email."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.winback_email."
            "record_writeback",
        ):
            out = apply_winback(spec)
        assert out["applied"] is False
        assert "network" in out["error"]


class TestStoreIdPropagation:

    def test_store_id_recorded(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_winback_sequence(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.winback_email."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.winback_email."
            "record_writeback",
        ) as record_mock:
            apply_winback(spec, store_id="store-a")
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
