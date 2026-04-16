"""Tests for the ad_creative_generator engine.

The engine consumes a scored winner (output of
:mod:`engines.winning_products`) plus commerce product data
and emits a deterministic creative pack spec — video plan,
voiceover plan, five copy variants, thumbnail plan, cost
rollup, and a ready / pending_approval / blocked verdict.

Coverage:

  * Envelope shape + input validation
  * Upstream failure propagation
  * Copy-on-entry safety (no input mutation)
  * Strategy auto-selection (stock / ai / slideshow)
  * Explicit strategy override + block conditions
    (slideshow needing >=2 images, ai needing budget,
     total cost exceeding budget)
  * Five copy-variant templates with slot substitution
  * Platform/angle CTA matrix
  * Voiceover cost math (chars × $0.00017)
  * Thumbnail dimensions per placement
  * Readiness tri-state
"""
from __future__ import annotations

import copy as _copy

from engines.ad_creative_generator import (
    ENGINE_NAME,
    AdCreativeGeneratorEngine,
    run,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _winner(**overrides):
    base = {
        "product_key": "sku-42",
        "score": 82,
        "verdict": "strong_buy",
        "days_running": 95,
        "hero_ad": {
            "headline": "Silent Posture Corrector",
            "copy": "Relieve back pain in minutes.",
        },
        "factors": {"engagement_velocity": {"value": 1200}},
    }
    for k, v in overrides.items():
        base[k] = v
    return base


def _product(**overrides):
    base = {
        "title": "Silent Posture Corrector Pro",
        "description": "Hidden under-shirt device. Gently trains your spine.",
        "price": 39.99,
        "images": [
            "https://cdn.x/a.jpg",
            "https://cdn.x/b.jpg",
            "https://cdn.x/c.jpg",
        ],
        "tags": ["posture", "back pain"],
        "benefit": "upright posture all day",
        "problem": "slouching at your desk",
        "audience": "remote workers",
        "time_to_value": "15 minutes a day",
        "review_quote": "\"Finally standing straight again.\"",
    }
    for k, v in overrides.items():
        base[k] = v
    return base


def _call(**kwargs):
    payload = {"winner": _winner(), "product": _product()}
    payload.update(kwargs)
    return run(payload)


# ---------------------------------------------------------------------------
# Envelope & entry point
# ---------------------------------------------------------------------------


class TestEntryPoint:
    def test_engine_name_exported(self):
        assert ENGINE_NAME == "ad_creative_generator"

    def test_class_wrapper_delegates(self):
        out = AdCreativeGeneratorEngine().run({
            "winner": _winner(), "product": _product(),
        })
        assert out["status"] == "success"
        assert out["meta"]["engine"] == "ad_creative_generator"

    def test_envelope_fields(self):
        out = _call()
        assert out["status"] == "success"
        assert "creative_pack" in out["data"]
        assert "timestamp" in out["meta"]
        assert "elapsed_seconds" in out["meta"]
        assert out["error"] is None

    def test_creative_pack_shape(self):
        pack = _call()["data"]["creative_pack"]
        for key in (
            "video_plan", "voiceover_plan", "copy_variants",
            "thumbnail_plan", "total_est_cost_usd", "budget_usd",
            "readiness", "blocks", "target",
        ):
            assert key in pack, f"missing {key}"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_missing_winner_errors(self):
        out = run({"product": _product()})
        assert out["status"] == "error"
        assert "winner" in out["error"]

    def test_empty_winner_errors(self):
        out = run({"winner": {}, "product": _product()})
        assert out["status"] == "error"

    def test_non_dict_winner_errors(self):
        out = run({"winner": "nope", "product": _product()})
        assert out["status"] == "error"

    def test_non_dict_product_errors(self):
        out = run({"winner": _winner(), "product": "bogus"})
        assert out["status"] == "error"
        assert "product" in out["error"]

    def test_missing_product_becomes_empty_dict(self):
        out = run({"winner": _winner()})
        assert out["status"] == "success"

    def test_none_input_errors(self):
        out = run(None)
        assert out["status"] == "error"


class TestUpstreamFailure:
    def test_upstream_fail_is_propagated(self):
        out = run({"status": "fail", "error": "network down"})
        assert out["status"] == "error"
        assert out["error"] == "network down"

    def test_upstream_fail_without_error_msg(self):
        out = run({"status": "fail"})
        assert out["status"] == "error"
        assert "Upstream" in out["error"]


# ---------------------------------------------------------------------------
# Copy-on-entry
# ---------------------------------------------------------------------------


class TestCopyOnEntry:
    def test_engine_does_not_mutate_input(self):
        payload = {
            "winner": _winner(),
            "product": _product(),
            "copy_angles": ["benefit_driven"],
        }
        snapshot = _copy.deepcopy(payload)
        run(payload)
        assert payload == snapshot


# ---------------------------------------------------------------------------
# Target plumbing
# ---------------------------------------------------------------------------


class TestTarget:
    def test_defaults_meta_reels_9_16_en(self):
        pack = _call()["data"]["creative_pack"]
        t = pack["target"]
        assert t["platform"] == "meta"
        assert t["placement"] == "reels"
        assert t["aspect_ratio"] == "9:16"
        assert t["language"] == "en"
        assert t["duration_seconds"] == 15

    def test_override_duration_clamped_low(self):
        pack = _call(target={"duration_seconds": 3})["data"]["creative_pack"]
        # Below minimum — snaps back to default, not floor, by design.
        assert pack["target"]["duration_seconds"] == 15

    def test_override_duration_clamped_high(self):
        pack = _call(target={"duration_seconds": 600})["data"]["creative_pack"]
        assert pack["target"]["duration_seconds"] == 30

    def test_override_platform_tiktok(self):
        pack = _call(target={"platform": "TikTok"})["data"]["creative_pack"]
        assert pack["target"]["platform"] == "tiktok"


# ---------------------------------------------------------------------------
# Strategy auto-selection
# ---------------------------------------------------------------------------


class TestStrategyAuto:
    def test_strong_buy_high_price_picks_ai(self):
        pack = _call()["data"]["creative_pack"]
        assert pack["video_plan"]["kind"] == "ai"
        assert pack["video_plan"]["ai_prompt"]
        assert pack["video_plan"]["est_cost_usd"] == 0.09

    def test_low_price_picks_stock(self):
        p = _product(price=12.0)
        out = run({"winner": _winner(), "product": p})
        plan = out["data"]["creative_pack"]["video_plan"]
        assert plan["kind"] == "stock"
        assert plan["est_cost_usd"] == 0.0
        assert plan["stock_queries"]

    def test_mid_price_non_strong_buy_picks_stock(self):
        w = _winner(verdict="watch")
        p = _product(price=25.0)
        out = run({"winner": w, "product": p})
        plan = out["data"]["creative_pack"]["video_plan"]
        assert plan["kind"] == "stock"

    def test_strong_buy_but_low_price_picks_stock(self):
        # price<20 rule wins over strong_buy.
        p = _product(price=15.0)
        out = run({"winner": _winner(), "product": p})
        plan = out["data"]["creative_pack"]["video_plan"]
        assert plan["kind"] == "stock"


class TestStrategyExplicit:
    def test_explicit_stock(self):
        pack = _call(strategy="stock")["data"]["creative_pack"]
        assert pack["video_plan"]["kind"] == "stock"

    def test_explicit_ai(self):
        pack = _call(strategy="ai")["data"]["creative_pack"]
        assert pack["video_plan"]["kind"] == "ai"

    def test_explicit_slideshow_with_enough_images(self):
        pack = _call(strategy="slideshow")["data"]["creative_pack"]
        assert pack["video_plan"]["kind"] == "slideshow"
        assert len(pack["video_plan"]["slideshow_images"]) == 3

    def test_slideshow_caps_at_six_images(self):
        p = _product(images=[f"u{i}" for i in range(10)])
        out = run({
            "winner": _winner(), "product": p, "strategy": "slideshow",
        })
        assert len(out["data"]["creative_pack"]["video_plan"]["slideshow_images"]) == 6

    def test_unknown_strategy_falls_back_to_auto(self):
        pack = _call(strategy="holographic")["data"]["creative_pack"]
        # unknown → auto → strong_buy+high price → ai
        assert pack["video_plan"]["kind"] == "ai"


# ---------------------------------------------------------------------------
# Block conditions
# ---------------------------------------------------------------------------


class TestBlocks:
    def test_slideshow_needs_two_images(self):
        p = _product(images=["only-one"])
        out = run({
            "winner": _winner(), "product": p, "strategy": "slideshow",
        })
        pack = out["data"]["creative_pack"]
        assert pack["readiness"] == "blocked"
        assert any("slideshow" in b for b in pack["blocks"])

    def test_ai_budget_too_small_blocks(self):
        out = run({
            "winner": _winner(),
            "product": _product(),
            "strategy": "ai",
            "budget_usd": 0.05,
        })
        pack = out["data"]["creative_pack"]
        assert pack["readiness"] == "blocked"
        assert any("ai video" in b for b in pack["blocks"])

    def test_voiceover_cost_can_exceed_budget(self):
        # Tiny budget — voiceover alone on 5 angles blows past $0.05.
        out = run({
            "winner": _winner(),
            "product": _product(),
            "strategy": "stock",
            "budget_usd": 0.05,
        })
        pack = out["data"]["creative_pack"]
        assert pack["readiness"] == "blocked"
        assert any("budget" in b for b in pack["blocks"])

    def test_stock_with_ample_budget_is_not_blocked(self):
        out = run({
            "winner": _winner(),
            "product": _product(),
            "strategy": "stock",
            "budget_usd": 1.0,
        })
        pack = out["data"]["creative_pack"]
        assert pack["blocks"] == []


# ---------------------------------------------------------------------------
# Readiness tri-state
# ---------------------------------------------------------------------------


class TestReadiness:
    def test_default_pending_approval(self):
        pack = _call()["data"]["creative_pack"]
        assert pack["readiness"] == "pending_approval"

    def test_auto_approve_is_ready(self):
        pack = _call(auto_approve=True)["data"]["creative_pack"]
        assert pack["readiness"] == "ready"

    def test_blocks_override_auto_approve(self):
        out = run({
            "winner": _winner(),
            "product": _product(images=["only-one"]),
            "strategy": "slideshow",
            "auto_approve": True,
        })
        assert out["data"]["creative_pack"]["readiness"] == "blocked"


# ---------------------------------------------------------------------------
# Copy variants
# ---------------------------------------------------------------------------


class TestCopyVariants:
    def test_default_emits_five_angles(self):
        pack = _call()["data"]["creative_pack"]
        angles = [v["angle"] for v in pack["copy_variants"]]
        assert angles == [
            "problem_agitation", "benefit_driven", "social_proof",
            "curiosity_hook", "urgency_scarcity",
        ]

    def test_custom_angle_subset(self):
        pack = _call(copy_angles=["benefit_driven", "urgency_scarcity"])
        pack = pack["data"]["creative_pack"]
        angles = [v["angle"] for v in pack["copy_variants"]]
        assert angles == ["benefit_driven", "urgency_scarcity"]

    def test_unknown_angles_ignored_then_defaulted(self):
        pack = _call(copy_angles=["bogus_angle"])["data"]["creative_pack"]
        angles = [v["angle"] for v in pack["copy_variants"]]
        # all-unknown falls back to full set
        assert len(angles) == 5

    def test_non_list_angles_defaults(self):
        pack = _call(copy_angles="benefit_driven")["data"]["creative_pack"]
        assert len(pack["copy_variants"]) == 5

    def test_every_variant_has_required_fields(self):
        pack = _call()["data"]["creative_pack"]
        for v in pack["copy_variants"]:
            for key in (
                "angle", "headline", "body", "hook", "cta",
                "hook_seconds", "hashtags", "brand_voice",
            ):
                assert key in v, f"{v['angle']} missing {key}"
            assert v["hook_seconds"] == 3
            assert isinstance(v["hashtags"], list)
            assert v["hashtags"][0].startswith("#")

    def test_problem_agitation_references_problem_slot(self):
        pack = _call()["data"]["creative_pack"]
        variant = next(
            v for v in pack["copy_variants"] if v["angle"] == "problem_agitation"
        )
        assert "slouching at your desk" in variant["headline"]
        assert "slouching at your desk" in variant["body"]

    def test_benefit_driven_references_benefit_slot(self):
        pack = _call()["data"]["creative_pack"]
        variant = next(
            v for v in pack["copy_variants"] if v["angle"] == "benefit_driven"
        )
        assert "upright posture" in variant["headline"]
        assert "upright posture" in variant["body"]

    def test_social_proof_references_count_and_review(self):
        pack = _call()["data"]["creative_pack"]
        variant = next(
            v for v in pack["copy_variants"] if v["angle"] == "social_proof"
        )
        # velocity 1200 × 30 = 36000 → display "36,000"
        assert "36,000" in variant["headline"]
        assert "standing straight" in variant["body"]

    def test_urgency_scarcity_references_price(self):
        pack = _call()["data"]["creative_pack"]
        variant = next(
            v for v in pack["copy_variants"] if v["angle"] == "urgency_scarcity"
        )
        assert "$39.99" in variant["body"]

    def test_brand_voice_propagates(self):
        pack = _call(brand_voice="playful")["data"]["creative_pack"]
        for v in pack["copy_variants"]:
            assert v["brand_voice"] == "playful"


class TestSlotFallbacks:
    def test_missing_benefit_falls_back_to_description(self):
        p = _product()
        p.pop("benefit")
        out = run({"winner": _winner(), "product": p})
        benefit_variant = next(
            v for v in out["data"]["creative_pack"]["copy_variants"]
            if v["angle"] == "benefit_driven"
        )
        # first phrase of description leaks through
        assert "Hidden under-shirt device" in benefit_variant["body"]

    def test_missing_problem_derives_from_title(self):
        p = _product()
        p.pop("problem")
        out = run({"winner": _winner(), "product": p})
        problem_variant = next(
            v for v in out["data"]["creative_pack"]["copy_variants"]
            if v["angle"] == "problem_agitation"
        )
        # synthesised from short title
        assert "old-school" in problem_variant["body"].lower()

    def test_missing_velocity_uses_default_social_count(self):
        w = _winner(factors={})
        out = run({"winner": w, "product": _product()})
        sp = next(
            v for v in out["data"]["creative_pack"]["copy_variants"]
            if v["angle"] == "social_proof"
        )
        assert "500" in sp["headline"]

    def test_zero_price_uses_phrase(self):
        p = _product(price=0)
        out = run({"winner": _winner(), "product": p})
        urg = next(
            v for v in out["data"]["creative_pack"]["copy_variants"]
            if v["angle"] == "urgency_scarcity"
        )
        assert "a great price" in urg["body"]


# ---------------------------------------------------------------------------
# CTA matrix
# ---------------------------------------------------------------------------


class TestCTAMatrix:
    def test_meta_urgency_is_shop_now(self):
        pack = _call(target={"platform": "meta"})["data"]["creative_pack"]
        urg = next(
            v for v in pack["copy_variants"] if v["angle"] == "urgency_scarcity"
        )
        assert urg["cta"] == "SHOP_NOW"

    def test_meta_problem_is_learn_more(self):
        pack = _call(target={"platform": "meta"})["data"]["creative_pack"]
        pr = next(
            v for v in pack["copy_variants"] if v["angle"] == "problem_agitation"
        )
        assert pr["cta"] == "LEARN_MORE"

    def test_tiktok_curiosity_is_watch_more(self):
        pack = _call(target={"platform": "tiktok"})["data"]["creative_pack"]
        cur = next(
            v for v in pack["copy_variants"] if v["angle"] == "curiosity_hook"
        )
        assert cur["cta"] == "Watch More"

    def test_tiktok_benefit_is_shop_now(self):
        pack = _call(target={"platform": "tiktok"})["data"]["creative_pack"]
        be = next(
            v for v in pack["copy_variants"] if v["angle"] == "benefit_driven"
        )
        assert be["cta"] == "Shop Now"

    def test_unknown_platform_meta_default(self):
        pack = _call(target={"platform": "snapchat"})["data"]["creative_pack"]
        # Unknown platform: matrix misses → fallback SHOP_NOW for non-meta
        ct = [v["cta"] for v in pack["copy_variants"]]
        assert all(c == "Shop Now" for c in ct)


# ---------------------------------------------------------------------------
# Voiceover plan
# ---------------------------------------------------------------------------


class TestVoiceoverPlan:
    def test_one_script_per_variant(self):
        pack = _call()["data"]["creative_pack"]
        vo = pack["voiceover_plan"]
        assert set(vo["scripts"].keys()) == {v["angle"] for v in pack["copy_variants"]}

    def test_cost_is_chars_times_rate(self):
        pack = _call()["data"]["creative_pack"]
        vo = pack["voiceover_plan"]
        expected = round(vo["char_total"] * 0.00017, 4)
        assert vo["est_cost_usd"] == expected
        assert vo["tts_rate_per_char"] == 0.00017

    def test_char_total_matches_script_lengths(self):
        pack = _call()["data"]["creative_pack"]
        vo = pack["voiceover_plan"]
        total = sum(len(s) for s in vo["scripts"].values())
        assert vo["char_total"] == total

    def test_voice_style_by_brand_voice(self):
        assert _call(brand_voice="casual")["data"]["creative_pack"][
            "voiceover_plan"]["voice_style"] == "casual_female"
        assert _call(brand_voice="authoritative")["data"]["creative_pack"][
            "voiceover_plan"]["voice_style"] == "authoritative_male"
        assert _call(brand_voice="playful")["data"]["creative_pack"][
            "voiceover_plan"]["voice_style"] == "playful_female"
        assert _call(brand_voice="luxury")["data"]["creative_pack"][
            "voiceover_plan"]["voice_style"] == "calm_male"
        assert _call(brand_voice="weirdcore")["data"]["creative_pack"][
            "voiceover_plan"]["voice_style"] == "casual_female"

    def test_script_includes_hook_body_and_cta_line(self):
        pack = _call()["data"]["creative_pack"]
        vo = pack["voiceover_plan"]
        script = vo["scripts"]["benefit_driven"]
        # benefit hook text
        assert "This changes everything" in script
        # body
        assert "Silent Posture Corrector Pro gives you" in script
        # SHOP_NOW → "Tap the link..."
        assert "Tap the link to grab yours." in script

    def test_learn_more_cta_line(self):
        pack = _call()["data"]["creative_pack"]
        vo = pack["voiceover_plan"]
        # problem_agitation on Meta → LEARN_MORE
        script = vo["scripts"]["problem_agitation"]
        assert "Tap to see the full story." in script

    def test_language_propagates(self):
        pack = _call(target={"language": "mn"})["data"]["creative_pack"]
        assert pack["voiceover_plan"]["language"] == "mn"


# ---------------------------------------------------------------------------
# Thumbnail plan
# ---------------------------------------------------------------------------


class TestThumbnailPlan:
    def test_reels_vertical_dimensions(self):
        pack = _call(target={"placement": "reels"})["data"]["creative_pack"]
        assert pack["thumbnail_plan"]["dimensions"] == [1080, 1920]

    def test_tiktok_vertical_dimensions(self):
        pack = _call(target={"placement": "tiktok"})["data"]["creative_pack"]
        assert pack["thumbnail_plan"]["dimensions"] == [1080, 1920]

    def test_story_vertical_dimensions(self):
        pack = _call(target={"placement": "story"})["data"]["creative_pack"]
        assert pack["thumbnail_plan"]["dimensions"] == [1080, 1920]

    def test_feed_square_dimensions(self):
        pack = _call(target={"placement": "feed"})["data"]["creative_pack"]
        assert pack["thumbnail_plan"]["dimensions"] == [1080, 1080]

    def test_unknown_placement_landscape_default(self):
        pack = _call(target={"placement": "youtube"})["data"]["creative_pack"]
        assert pack["thumbnail_plan"]["dimensions"] == [1200, 628]

    def test_overlay_from_hero_headline(self):
        pack = _call()["data"]["creative_pack"]
        assert pack["thumbnail_plan"]["text_overlay"].isupper()
        assert "SILENT" in pack["thumbnail_plan"]["text_overlay"]

    def test_source_image_picked_from_product(self):
        pack = _call()["data"]["creative_pack"]
        assert pack["thumbnail_plan"]["source_image"] == "https://cdn.x/a.jpg"

    def test_source_image_from_dict_entry(self):
        p = _product(images=[{"url": "https://cdn.x/dict-form.jpg"}])
        pack = run({"winner": _winner(), "product": p})["data"]["creative_pack"]
        assert pack["thumbnail_plan"]["source_image"] == (
            "https://cdn.x/dict-form.jpg"
        )

    def test_no_images_empty_source(self):
        p = _product(images=[])
        pack = run({
            "winner": _winner(), "product": p, "strategy": "stock",
        })["data"]["creative_pack"]
        assert pack["thumbnail_plan"]["source_image"] == ""


# ---------------------------------------------------------------------------
# Video plan details (stock / ai)
# ---------------------------------------------------------------------------


class TestStockPlan:
    def test_stock_queries_deduped_and_trimmed(self):
        # Title, headline, tags all convey "posture" — dedupe keeps 1-3.
        pack = _call(strategy="stock")["data"]["creative_pack"]
        q = pack["video_plan"]["stock_queries"]
        assert 1 <= len(q) <= 3
        assert all(isinstance(s, str) and s for s in q)

    def test_stock_fallback_when_no_text(self):
        p = {"price": 10.0}  # no title, no tags
        out = run({"winner": {"product_key": "k"}, "product": p})
        q = out["data"]["creative_pack"]["video_plan"]["stock_queries"]
        assert q  # at least one fallback query


class TestAIPlan:
    def test_ai_prompt_includes_title_and_aspect(self):
        pack = _call()["data"]["creative_pack"]
        prompt = pack["video_plan"]["ai_prompt"]
        assert "Silent Posture Corrector Pro" in prompt
        assert "9:16" in prompt

    def test_ai_prompt_includes_mood_from_hero_copy(self):
        pack = _call()["data"]["creative_pack"]
        prompt = pack["video_plan"]["ai_prompt"]
        assert "Relieve back pain in minutes" in prompt


# ---------------------------------------------------------------------------
# Cost rollup
# ---------------------------------------------------------------------------


class TestCostRollup:
    def test_total_is_video_plus_voiceover(self):
        pack = _call()["data"]["creative_pack"]
        expected = round(
            pack["video_plan"]["est_cost_usd"]
            + pack["voiceover_plan"]["est_cost_usd"],
            4,
        )
        assert pack["total_est_cost_usd"] == expected

    def test_budget_echoed(self):
        pack = _call(budget_usd=1.5)["data"]["creative_pack"]
        assert pack["budget_usd"] == 1.5

    def test_negative_budget_clamped_to_default(self):
        pack = _call(budget_usd=-1)["data"]["creative_pack"]
        assert pack["budget_usd"] == 0.5


# ---------------------------------------------------------------------------
# Top-level pass-through data
# ---------------------------------------------------------------------------


class TestDataPassthrough:
    def test_product_key_echoed(self):
        out = _call()
        assert out["data"]["product_key"] == "sku-42"

    def test_verdict_echoed(self):
        out = _call()
        assert out["data"]["winner_verdict"] == "strong_buy"

    def test_score_echoed(self):
        out = _call()
        assert out["data"]["winner_score"] == 82
