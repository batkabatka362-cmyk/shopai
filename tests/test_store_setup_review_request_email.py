"""Tests for ``engines.store_setup.review_request_email``.

Generator produces niche-aware post-purchase review request
email templates (vanilla + with_incentive variants). Applier
persists as Shopify page (``review-request-email``) via
``SHOPIFY_CREATE_PAGE``. Records via Pattern Z.

Coverage:
  1. Generator: empty store_name -> empty dict.
  2. Generator: both variants always present.
  3. Generator: every variant has subject + preheader +
     body_text + body_html + trigger.
  4. Generator: incentive variant carries incentive_code +
     incentive_pct when supplied.
  5. Generator: incentive variant without code/pct still
     ships with generic reward language.
  6. Generator: niche-specific subjects + body lines.
  7. Generator: trigger day count parameterised.
  8. Generator: Liquid placeholders preserved.
  9. Generator: incentive subject template substitutes pct.
 10. Renderer: empty / non-dict.
 11. Renderer: produces both sections.
 12. Renderer: HTML-escapes content.
 13. Applier: empty / no templates short-circuit.
 14. Applier: success + Pattern Z metrics.
 15. Applier: router_unavailable / rejection / raise.
 16. store_id propagation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.review_request_email import (
    _NICHE_BODY_LINES,
    _NICHE_SUBJECTS,
    apply_review_emails,
    generate_review_request_emails,
    render_review_emails_html,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_review_request_emails(
            store_name="",
        ) == {}
        assert generate_review_request_emails(
            store_name="   ",
        ) == {}
        assert generate_review_request_emails(
            store_name=None,
        ) == {}


class TestGeneratorShape:

    def test_both_variants_present(self):
        spec = generate_review_request_emails(
            store_name="Acme", niche="beauty",
        )
        assert "vanilla" in spec["templates"]
        assert "with_incentive" in spec["templates"]

    def test_every_variant_has_full_shape(self):
        spec = generate_review_request_emails(
            store_name="Acme",
        )
        for key in ("vanilla", "with_incentive"):
            tmpl = spec["templates"][key]
            assert tmpl["subject"], key
            assert tmpl["preheader"], key
            assert tmpl["body_text"], key
            assert tmpl["body_html"], key
            assert tmpl["trigger"], key

    def test_liquid_placeholders_preserved(self):
        spec = generate_review_request_emails(
            store_name="Acme",
        )
        for key in ("vanilla", "with_incentive"):
            tmpl = spec["templates"][key]
            assert "{{first_name}}" in tmpl["body_text"]
            assert "{{first_name}}" in tmpl["body_html"]
            assert (
                "{{order.line_item.product.url}}"
                in tmpl["body_text"]
            )

    def test_store_name_in_body(self):
        spec = generate_review_request_emails(
            store_name="Acme Beauty",
        )
        for key in ("vanilla", "with_incentive"):
            tmpl = spec["templates"][key]
            assert "Acme Beauty" in tmpl["body_text"]


class TestNicheTone:

    def test_every_niche_resolves(self):
        for niche in (
            "beauty", "fashion", "tech", "home", "food",
            "pets", "fitness", "jewelry", "outdoor",
            "baby", "general", "ufo_parts",
        ):
            spec = generate_review_request_emails(
                store_name="Acme", niche=niche,
            )
            assert spec["templates"]["vanilla"]["body_text"]

    def test_niche_specific_subject_per_niche(self):
        """Subject lines differ per niche."""
        beauty = generate_review_request_emails(
            store_name="Acme", niche="beauty",
        )
        fashion = generate_review_request_emails(
            store_name="Acme", niche="fashion",
        )
        food = generate_review_request_emails(
            store_name="Acme", niche="food",
        )
        # Each niche has its own subject -- not the
        # general default.
        general_subject = _NICHE_SUBJECTS["general"][0]
        assert (
            beauty["templates"]["vanilla"]["subject"]
            != general_subject
        )
        assert (
            fashion["templates"]["vanilla"]["subject"]
            != general_subject
        )
        # Specific category cues in body
        assert (
            "fit"
            in fashion["templates"]["vanilla"][
                "body_text"
            ].lower()
        )
        assert (
            "tast"
            in food["templates"]["vanilla"][
                "body_text"
            ].lower()
        )

    def test_unknown_niche_falls_back_to_general(self):
        spec = generate_review_request_emails(
            store_name="Acme", niche="ufo_parts",
        )
        general_subject = _NICHE_SUBJECTS["general"][0]
        assert (
            spec["templates"]["vanilla"]["subject"]
            == general_subject
        )

    def test_niche_body_lines_distinct(self):
        """Every shipped niche carries its own body line."""
        seen: set[str] = set()
        for niche in _NICHE_BODY_LINES:
            if niche == "general":
                continue
            body = _NICHE_BODY_LINES[niche]
            assert body not in seen, niche
            seen.add(body)


class TestIncentiveIntegration:

    def test_incentive_with_code_pct(self):
        spec = generate_review_request_emails(
            store_name="Acme",
            niche="beauty",
            incentive_code="THANKS15",
            incentive_pct=15,
        )
        inc = spec["templates"]["with_incentive"]
        assert "THANKS15" in inc["body_text"]
        assert "15%" in inc["body_text"]
        assert "15%" in inc["preheader"]
        # Subject substitutes pct in the "10% off" template
        assert "15%" in inc["subject"]
        # Spec fields carry the values for downstream
        # consumers
        assert inc["incentive_code"] == "THANKS15"
        assert inc["incentive_pct"] == 15

    def test_incentive_without_code_falls_back(self):
        """No code -> generic reward language, no broken
        placeholder."""
        spec = generate_review_request_emails(
            store_name="Acme", niche="beauty",
        )
        inc = spec["templates"]["with_incentive"]
        # No code referenced in body
        assert "THANKS" not in inc["body_text"]
        # Generic reward language present
        assert "thank-you" in inc["body_text"].lower()
        # Spec fields are None when not supplied
        assert inc["incentive_code"] is None
        assert inc["incentive_pct"] is None

    def test_code_uppercased(self):
        spec = generate_review_request_emails(
            store_name="Acme",
            incentive_code="thanks15",
            incentive_pct=15,
        )
        inc = spec["templates"]["with_incentive"]
        assert "THANKS15" in inc["body_text"]
        assert inc["incentive_code"] == "THANKS15"

    def test_zero_pct_ignored(self):
        """Zero pct = no real incentive; falls back to
        generic reward language."""
        spec = generate_review_request_emails(
            store_name="Acme",
            incentive_code="THANKS0",
            incentive_pct=0,
        )
        inc = spec["templates"]["with_incentive"]
        assert "0%" not in inc["body_text"]
        assert inc["incentive_pct"] is None


class TestTriggerDays:

    def test_default_triggers(self):
        spec = generate_review_request_emails(
            store_name="Acme",
        )
        assert (
            "7 days"
            in spec["templates"]["vanilla"]["trigger"]
        )
        assert (
            "14 days"
            in spec["templates"]["with_incentive"]["trigger"]
        )

    def test_override_trigger_days(self):
        spec = generate_review_request_emails(
            store_name="Acme",
            days_after_delivery_vanilla=10,
            days_after_delivery_incentive=30,
        )
        assert (
            "10 days"
            in spec["templates"]["vanilla"]["trigger"]
        )
        assert (
            "30 days"
            in spec["templates"]["with_incentive"]["trigger"]
        )


# ── Renderer ──────────────────────────────────────────────────


class TestRenderer:

    def test_empty_spec(self):
        assert render_review_emails_html({}) == ""
        assert render_review_emails_html(None) == ""  # type: ignore[arg-type]
        assert (
            render_review_emails_html({
                "store_name": "Acme",
            }) == ""
        )

    def test_renders_both_sections(self):
        spec = generate_review_request_emails(
            store_name="Acme Beauty", niche="beauty",
        )
        html_out = render_review_emails_html(spec)
        assert "Acme Beauty" in html_out
        assert "Vanilla" in html_out
        assert "With Incentive" in html_out
        # Trigger line surfaced
        assert "7 days" in html_out
        assert "14 days" in html_out

    def test_escapes_user_content(self):
        spec = {
            "store_name": "<script>x</script>",
            "niche": "beauty",
            "templates": {
                "vanilla": {
                    "subject": "<b>S</b>",
                    "preheader": "x & y",
                    "body_text": "",
                    "body_html": "",
                    "trigger": "7 days",
                },
            },
        }
        html_out = render_review_emails_html(spec)
        assert "<script>x</script>" not in html_out
        assert "<b>S</b>" not in html_out
        assert "&lt;" in html_out


# ── Applier ──────────────────────────────────────────────────


class TestApplierEmpty:

    def test_no_spec(self):
        out = apply_review_emails({})
        assert out["applied"] is False
        assert out["error"] == "no_review_email_spec"

    def test_non_dict(self):
        out = apply_review_emails(None)  # type: ignore[arg-type]
        assert out["applied"] is False

    def test_spec_without_templates(self):
        out = apply_review_emails({"store_name": "Acme"})
        assert out["applied"] is False


class TestApplierSuccess:

    def test_pushes_via_create_page(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_review_request_emails(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.review_request_email."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.review_request_email."
            "record_writeback",
        ) as record_mock:
            out = apply_review_emails(spec)
        assert out["applied"] is True
        assert out["handle"] == "review-request-email"
        params = router.execute.call_args.args[1]
        assert params["title"] == "Review Request Email"
        assert params["handle"] == "review-request-email"
        kwargs = record_mock.call_args.kwargs
        assert kwargs["success"] is True
        assert kwargs["metrics"]["template_count"] == 2
        assert kwargs["metrics"]["niche"] == "beauty"


class TestApplierFailureModes:

    def test_router_unavailable(self):
        spec = generate_review_request_emails(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.review_request_email."
            "_get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.review_request_email."
            "record_writeback",
        ) as record_mock:
            out = apply_review_emails(spec)
        assert out["applied"] is False
        assert out["error"] == "router_unavailable"
        assert (
            record_mock.call_args.kwargs["success"]
            is False
        )

    def test_adapter_rejection(self):
        router = MagicMock()
        router.execute.return_value = _fail("handle taken")
        spec = generate_review_request_emails(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.review_request_email."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.review_request_email."
            "record_writeback",
        ):
            out = apply_review_emails(spec)
        assert out["applied"] is False
        assert "handle taken" in out["error"]

    def test_adapter_raise(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        spec = generate_review_request_emails(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.review_request_email."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.review_request_email."
            "record_writeback",
        ):
            out = apply_review_emails(spec)
        assert out["applied"] is False
        assert "network" in out["error"]


class TestStoreIdPropagation:

    def test_store_id_recorded(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_review_request_emails(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.review_request_email."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.review_request_email."
            "record_writeback",
        ) as record_mock:
            apply_review_emails(spec, store_id="store-a")
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
