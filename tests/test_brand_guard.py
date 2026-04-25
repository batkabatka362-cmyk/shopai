"""BrandGuard regression — deterministic brand-rule checks."""
from __future__ import annotations

import json

import pytest

from core.brand import BrandCheck, BrandGuard, BrandRules


# ── Constructor + metafield parsing ────────────────────────


class TestFromMetafields:
    def test_empty_list_neutral_defaults(self):
        g = BrandGuard.from_metafields([])
        # Caller can still run a check — no rules = no errors.
        check = g.check_content("Hello world", surface="ad_copy")
        assert check.passed

    def test_none_safe(self):
        g = BrandGuard.from_metafields(None)
        check = g.check_content("Hello", surface="ad_copy")
        assert check.passed

    def test_parses_brand_metafield(self):
        mf = {
            "namespace": "shopai",
            "key": "brand",
            "value": json.dumps({
                "voice": "calm_cozy",
                "tagline": "Calm & cozy living",
                "forbidden_words": ["competitor", "crap"],
                "required_words": ["cozy", "wellness"],
            }),
        }
        g = BrandGuard.from_metafields([mf])
        rules = g._rules
        assert rules.voice == "calm_cozy"
        assert rules.tagline == "Calm & cozy living"
        assert "competitor" in rules.forbidden_words
        assert "wellness" in rules.required_words

    def test_ignores_other_namespaces(self):
        mf = {
            "namespace": "other_app",
            "key": "brand",
            "value": json.dumps({"voice": "bold"}),
        }
        g = BrandGuard.from_metafields([mf])
        # Nothing was picked up — voice stays default.
        assert g._rules.voice == "neutral"

    def test_comma_string_forbidden_words(self):
        mf = {
            "namespace": "shopai",
            "key": "brand",
            "value": json.dumps({
                "voice": "bold",
                "forbidden_words": "cheap, scam, ripoff",
            }),
        }
        g = BrandGuard.from_metafields([mf])
        assert "cheap" in g._rules.forbidden_words
        assert "scam" in g._rules.forbidden_words
        assert "ripoff" in g._rules.forbidden_words

    def test_malformed_json_safe(self):
        mf = {
            "namespace": "shopai",
            "key": "brand",
            "value": "{not json",
        }
        g = BrandGuard.from_metafields([mf])
        # Didn't raise; defaults intact.
        assert g._rules.voice == "neutral"

    def test_surface_overrides_parsed(self):
        mf = {
            "namespace": "shopai",
            "key": "brand",
            "value": json.dumps({
                "voice": "bold",
                "surface_overrides": {
                    "ad_copy": {"max_chars": 150},
                },
            }),
        }
        g = BrandGuard.from_metafields([mf])
        assert (
            g._rules.surface_overrides["ad_copy"]["max_chars"]
            == 150
        )


# ── Surface rule enforcement ───────────────────────────────


class TestSurfaceRules:
    def test_unknown_surface_raises(self):
        g = BrandGuard(BrandRules())
        with pytest.raises(ValueError):
            g.check_content("x", surface="unknown")

    def test_ad_copy_max_chars(self):
        g = BrandGuard(BrandRules())
        long_ = "a" * 301
        check = g.check_content(long_, surface="ad_copy")
        assert not check.passed
        codes = [i.code for i in check.errors]
        assert "max_chars" in codes

    def test_ad_copy_at_cap_passes(self):
        g = BrandGuard(BrandRules())
        check = g.check_content("a" * 300, surface="ad_copy")
        assert check.passed

    def test_email_subject_no_exclamations(self):
        g = BrandGuard(BrandRules())
        check = g.check_content(
            "Big news!", surface="email_subject",
        )
        assert not check.passed
        assert any(
            i.code == "max_exclamations"
            for i in check.errors
        )

    def test_ad_copy_allows_two_exclamations(self):
        g = BrandGuard(BrandRules())
        check = g.check_content(
            "cozy!!", surface="ad_copy",
        )
        assert check.passed

    def test_ad_copy_three_exclamations_fails(self):
        g = BrandGuard(BrandRules())
        check = g.check_content(
            "cozy!!!", surface="ad_copy",
        )
        assert not check.passed

    def test_product_desc_min_chars(self):
        g = BrandGuard(BrandRules())
        check = g.check_content(
            "too short", surface="product_desc",
        )
        assert not check.passed
        assert any(i.code == "min_chars" for i in check.errors)

    def test_allcaps_detected_in_ad_copy(self):
        g = BrandGuard(BrandRules())
        check = g.check_content(
            "ORDER your cozy lamp today", surface="ad_copy",
        )
        assert not check.passed
        assert any(
            i.code == "allcaps_word" for i in check.errors
        )

    def test_three_letter_caps_allowed(self):
        """ALL-CAPS check requires 4+ chars — NASA OK, FREE
        (4 chars) not OK, OK (2 chars) fine."""
        g = BrandGuard(BrandRules())
        check = g.check_content(
            "Made in USA for you",
            surface="ad_copy",
        )
        # "USA" is 3 chars — doesn't trigger.
        assert check.passed

    def test_per_surface_override_shortens_ad_copy(self):
        rules = BrandRules(
            surface_overrides={"ad_copy": {"max_chars": 50}},
        )
        g = BrandGuard(rules)
        check = g.check_content("a" * 60, surface="ad_copy")
        assert not check.passed
        assert any(i.code == "max_chars" for i in check.errors)


# ── Forbidden words ────────────────────────────────────────


class TestForbiddenWords:
    def test_forbidden_word_word_boundary(self):
        g = BrandGuard(BrandRules(
            forbidden_words=frozenset({"crap"}),
        ))
        check = g.check_content(
            "This lamp is crap", surface="product_desc",
        )
        assert not check.passed
        assert any(
            i.code == "forbidden_word" for i in check.errors
        )

    def test_forbidden_word_case_insensitive(self):
        g = BrandGuard(BrandRules(
            forbidden_words=frozenset({"competitor"}),
        ))
        check = g.check_content(
            "better than the COMPETITOR brand yy " * 3,
            surface="product_desc",
        )
        assert not check.passed
        assert any(
            i.code == "forbidden_word" for i in check.errors
        )

    def test_forbidden_substring_not_matched(self):
        """'scam' should not flag 'scampi'."""
        g = BrandGuard(BrandRules(
            forbidden_words=frozenset({"scam"}),
        ))
        check = g.check_content(
            "Love these shrimp scampi dishes foo bar yyyy xxxx",
            surface="product_desc",
        )
        assert check.passed


# ── Voice-mismatch ─────────────────────────────────────────


class TestVoiceMismatch:
    def test_hype_word_in_calm_voice_flagged(self):
        g = BrandGuard(BrandRules(voice="calm_cozy"))
        check = g.check_content(
            "You won't believe this CRAZY deal",
            surface="ad_copy",
        )
        assert not check.passed
        assert any(
            i.code == "voice_mismatch" for i in check.errors
        )

    def test_hype_word_in_bold_voice_allowed(self):
        g = BrandGuard(BrandRules(voice="bold_energetic"))
        check = g.check_content(
            "Insane mushroom lamp sale",
            surface="ad_copy",
        )
        assert check.passed

    def test_short_word_not_detected(self):
        """'rush' is a hype word — triggers only on word
        boundary."""
        g = BrandGuard(BrandRules(voice="calm_cozy"))
        check = g.check_content(
            "This rushes the glow to the room",
            surface="ad_copy",
        )
        # "rushes" is a different token from "rush".
        assert check.passed


# ── Tagline + required words (warnings) ────────────────────


class TestSoftRules:
    def test_missing_tagline_in_email_body_warns(self):
        g = BrandGuard(BrandRules(
            tagline="Calm & cozy living",
        ))
        body = (
            "Thanks for your purchase. Your order is on the "
            "way. Let us know if you have questions."
        )
        check = g.check_content(body, surface="email_body")
        # Still passes — warning-level.
        assert check.passed
        codes = [i.code for i in check.warnings]
        assert "missing_tagline" in codes

    def test_tagline_present_no_warning(self):
        g = BrandGuard(BrandRules(
            tagline="Calm & cozy living",
        ))
        body = (
            "Thanks for your purchase. Calm & cozy living — "
            "Deguar team."
        )
        check = g.check_content(body, surface="email_body")
        assert not check.warnings

    def test_tagline_not_checked_on_ad_copy(self):
        """require_tagline is email_body-only by default."""
        g = BrandGuard(BrandRules(
            tagline="Calm & cozy living",
        ))
        check = g.check_content(
            "cozy vibes", surface="ad_copy",
        )
        assert not any(
            i.code == "missing_tagline" for i in check.issues
        )

    def test_all_required_words_missing_warns(self):
        g = BrandGuard(BrandRules(
            required_words=frozenset({"cozy", "wellness"}),
        ))
        check = g.check_content(
            "Standard generic ad copy here.",
            surface="ad_copy",
        )
        assert check.passed  # warning only
        assert any(
            i.code == "missing_required_words"
            for i in check.warnings
        )

    def test_at_least_one_required_word_present(self):
        g = BrandGuard(BrandRules(
            required_words=frozenset({"cozy", "wellness"}),
        ))
        check = g.check_content(
            "Cozy lamp for your reading nook.",
            surface="ad_copy",
        )
        # At least one present → no warning.
        assert not any(
            i.code == "missing_required_words"
            for i in check.warnings
        )


# ── BrandCheck convenience ─────────────────────────────────


class TestBrandCheckShape:
    def test_errors_vs_warnings_split(self):
        g = BrandGuard(BrandRules(
            tagline="Calm & cozy living",
            forbidden_words=frozenset({"bad"}),
        ))
        # One error (forbidden word) + one warning (missing
        # tagline in email).
        check = g.check_content(
            "This content is bad for buyers",
            surface="email_body",
        )
        assert len(check.errors) == 1
        assert len(check.warnings) == 1
        assert not check.passed

    def test_text_length_populated(self):
        g = BrandGuard(BrandRules())
        check = g.check_content(
            "hello world", surface="ad_copy",
        )
        assert check.text_length == 11
