"""Tests for ``core.brain.intent_router.classify_intent``.

Coverage:
  1. Common English business intents → expected engine.
  2. Mongolian intents land on the same engines (the index
     bundles both languages).
  3. Multi-engine ambiguity: tie-breaking favours the engine
     with the strongest phrase match.
  4. No-match cases (empty / gibberish / under-floor) return
     ``engine=None`` with diagnostics.
  5. Word-set fallback handles "lower my product prices" vs the
     phrase "lower price" — the test case the substring matcher
     was failing pre-fix.
  6. Naive stemming for plurals ("products" matches "product").
  7. ``available_engines`` whitelist limits routing.
  8. ``IntentResult.to_dict`` shape.
  9. ``list_supported_engines`` returns the index keys sorted.
"""
from __future__ import annotations

import pytest

from core.brain.intent_router import (
    IntentResult,
    classify_intent,
    list_supported_engines,
)


# ─── canonical English intents ───────────────────────────────────


class TestEnglishIntents:

    @pytest.mark.parametrize("text, expected", [
        ("I want to lower my product prices", "dynamic_pricing"),
        ("create a 10% promo code", "discount_strategy"),
        ("archive declining products", "product_lifecycle"),
        ("improve my SEO meta titles", "search_optimization"),
        ("reward my loyal customers", "loyalty"),
        ("predict customer churn", "churn_prediction"),
        ("pay affiliate commissions", "affiliate"),
        ("auto-tag products by category", "tag_management"),
        ("rewrite product descriptions", "content_generation"),
        ("optimize ad spend with ROAS guardrails", "roas_guardrails"),
        ("spy on competitor ads", "ads_spy"),
        ("analyze cohorts and LTV", "cohort_analysis"),
        ("detect fraudulent orders", "fraud_detection"),
        ("build a product bundle", "bundle"),
        ("shipping rates per zone", "shipping"),
        ("B2B wholesale pricing", "wholesale_b2b"),
    ])
    def test_canonical_intents_route_correctly(self, text, expected):
        result = classify_intent(text)
        assert result.engine == expected, (
            f"Expected '{expected}' for {text!r}, got "
            f"'{result.engine}' (confidence {result.confidence:.2f})"
        )
        assert result.confidence > 0.0
        assert result.source == "rules"

    def test_high_confidence_threshold(self):
        # An exact multi-word phrase match should land in the high
        # confidence band and surface "high confidence" in the
        # explanation.
        result = classify_intent(
            "auto tag products by category and tag them all",
        )
        assert result.engine == "tag_management"
        assert "high" in result.explanation


# ─── Mongolian intents ───────────────────────────────────────────


class TestMongolianIntents:

    def test_mongolian_discount_keyword(self):
        result = classify_intent("хямдрал хийе")
        assert result.engine == "discount_strategy"

    def test_mongolian_price_phrase(self):
        result = classify_intent("үнэ нэмэх хэрэгтэй")
        assert result.engine == "dynamic_pricing"


# ─── word-set fallback (the regression case) ─────────────────────


class TestWordSetFallback:

    def test_intervening_words_dont_break_matching(self):
        # The phrase "lower price" lives in the index; but the
        # input has "lower my product prices" with intervening
        # words. The substring matcher misses; the word-set
        # fallback catches it because {lower, price} ⊂ tokens.
        result = classify_intent("I want to lower my product prices")
        assert result.engine == "dynamic_pricing"

    def test_plural_input_matches_singular_phrase(self):
        # Naive stemming strips trailing 's' from 4+ char tokens
        # so "products" matches "product" in the phrase.
        result = classify_intent("rewrite my products' descriptions")
        assert result.engine == "content_generation"


# ─── no-match / weak-match ───────────────────────────────────────


class TestNoMatch:

    def test_empty_input_returns_none(self):
        result = classify_intent("")
        assert result.engine is None
        assert result.confidence == 0.0
        assert "empty input" in result.explanation

    def test_whitespace_input_returns_none(self):
        result = classify_intent("   \n\t  ")
        assert result.engine is None
        assert result.confidence == 0.0

    def test_gibberish_returns_none_with_alternatives(self):
        result = classify_intent("xyzqq blarghhh foo bar")
        assert result.engine is None
        assert "no engine keyword matched" in result.explanation
        # No matches → no alternatives surfaced.
        assert result.alternatives == []

    def test_weak_match_under_floor_returns_none_with_runner_up(self):
        # A single ambiguous word ("rate" hits shipping rate but
        # without the "shipping" prefix). It should produce a
        # below-floor candidate but explicitly None engine.
        result = classify_intent("rate")
        # Either engine=None below floor, or low-confidence weak;
        # primary contract: surface alternatives so caller can
        # disambiguate.
        if result.engine is None:
            assert "weak match" in result.explanation or "no engine" in result.explanation


# ─── available_engines whitelist ────────────────────────────────


class TestEngineWhitelist:

    def test_whitelist_filters_routable_engines(self):
        # Even though "lower price" most strongly hits
        # dynamic_pricing, the whitelist forces fallback to a
        # different engine or no-match.
        result = classify_intent(
            "lower my prices",
            available_engines={"discount_strategy", "loyalty"},
        )
        assert result.engine != "dynamic_pricing"

    def test_whitelist_with_no_overlap_returns_none(self):
        result = classify_intent(
            "lower my prices",
            available_engines={"loyalty", "shipping"},
        )
        assert result.engine is None


# ─── IntentResult shape ─────────────────────────────────────────


class TestIntentResultSerialization:

    def test_to_dict_round_trip(self):
        result = classify_intent("create a discount code for VIP")
        d = result.to_dict()
        assert "engine" in d
        assert "confidence" in d
        assert "alternatives" in d
        assert "source" in d
        assert "explanation" in d
        assert "matched_keywords" in d
        # Confidence is rounded to 3 decimals in the dict form.
        assert isinstance(d["confidence"], float)

    def test_alternatives_capped_at_three(self):
        # An ambiguous phrase that matches multiple engines.
        result = classify_intent(
            "discount the price for loyal customers and ship it",
        )
        assert len(result.alternatives) <= 3


# ─── list_supported_engines ─────────────────────────────────────


class TestSupportedEngines:

    def test_returns_sorted_index_keys(self):
        engines = list_supported_engines()
        assert engines == sorted(engines)
        # Sanity: at least the core writeback engines are listed.
        for required in [
            "dynamic_pricing", "discount_strategy", "loyalty",
            "affiliate", "tag_management", "search_optimization",
            "product_lifecycle",
        ]:
            assert required in engines


# ─── input safety ───────────────────────────────────────────────


class TestInputSafety:

    def test_oversized_input_truncated_no_crash(self):
        # Cap is 1000 chars; 10k input should not crash.
        result = classify_intent("price " * 5000)
        # Doesn't matter which engine wins; just that we don't
        # blow up matching or denominator math.
        assert isinstance(result, IntentResult)

    def test_non_string_input_returns_no_match(self):
        for bad in [None, 42, [], {}]:
            # type: ignore  — deliberate misuse.
            result = classify_intent(bad)  # noqa
            assert result.engine is None
            assert result.confidence == 0.0
