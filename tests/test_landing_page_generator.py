"""Tests for ``engines.landing_page.page_generator``.

Two paths are exercised:

  * LLM path -- mock the router's ``execute(Capability.CHAT_COMPLETE,
    ...)`` to return a known JSON response; verify the parser
    produces the canonical page dict.
  * Template fallback -- with no LLM mock, the writer returns the
    deterministic template-built page (because the Pattern J
    guard short-circuits the live LLM call under pytest).

Coverage:
  1. Pattern J guard: live LLM never called under pytest.
  2. LLM happy path -> parsed page.
  3. LLM markdown-fenced JSON -> regex falls back, parsed.
  4. LLM returns garbage -> falls back to template path.
  5. LLM router returns ok=False -> falls back.
  6. LLM raises -> falls back.
  7. Empty benefits list -> falls back to template (load-bearing).
  8. Missing CTA -> falls back to template.
  9. Mobile channel sets layout=single_column on both paths.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from engines.landing_page.page_generator import generate_page


_PRODUCT = {
    "title": "YouthBoost LED Facial Lifter",
    "description": "Pro-grade LED therapy. Reduces wrinkles in 4 weeks.",
    "price": 199.0,
    "features": ["6 LED wavelengths", "Wireless charging", "Aluminum body"],
    "category": "Skincare",
}
_CAMPAIGN = {"goal": "conversion", "channel": "web"}
_AUDIENCE = "skincare enthusiasts aged 30-55"
_VOICE = "professional"


def _ok(data):
    return SimpleNamespace(ok=True, data=data, error=None)


def _fail(error="x"):
    return SimpleNamespace(ok=False, data=None, error=error)


class TestPatternJGuard:

    def test_pytest_env_blocks_live_llm(self, monkeypatch):
        """Under pytest, the LLM path short-circuits without
        even importing the router -- falls back to template."""
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "active")
        # No router mock -- template fallback must run cleanly.
        result = generate_page(_PRODUCT, _CAMPAIGN, _AUDIENCE, _VOICE)
        assert result["status"] == "success"
        page = result["page"]
        # Template path uses YouthBoost in the headline
        assert "YouthBoost" in page["headline"]
        # Template path always populates benefits + cta
        assert page["benefits"]
        assert page["cta"]


class TestLLMHappyPath:

    def _run(self, llm_text, campaign=None):
        seen = {}

        def _exec(cap, params):
            seen.update(params)
            return _ok({"text": llm_text, "model": "claude-haiku-4-5"})

        router = SimpleNamespace(execute=_exec)
        camp = campaign or _CAMPAIGN
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch("core.adapters.get_router", return_value=router):
            result = generate_page(_PRODUCT, camp, _AUDIENCE, _VOICE)
        return result, seen

    def test_strict_json_response(self):
        llm = json.dumps({
            "headline": "Reverse 4 Weeks of Skin Aging",
            "subheadline": "Pro-grade LED, salon results at home.",
            "hero_section": "Step into the dermatology booth experts trust.",
            "benefits": [
                "Visibly firmer in 14 days",
                "FDA-cleared LEDs",
                "1-touch, no learning curve",
            ],
            "cta": "Claim Your Lifter",
            "social_proof": "Trusted by 12,000 estheticians worldwide.",
        })
        result, params = self._run(llm)
        assert result["status"] == "success"
        p = result["page"]
        assert p["headline"] == "Reverse 4 Weeks of Skin Aging"
        assert p["cta"] == "Claim Your Lifter"
        assert len(p["benefits"]) == 3
        assert "Trusted by 12,000" in p["social_proof"]
        # Standard layout for web channel
        assert p["layout"] == "standard"
        # Prompt includes product context
        assert "YouthBoost" in params["prompt"]
        assert params["max_tokens"] == 1200

    def test_markdown_fenced_json_still_parses(self):
        llm = (
            "Sure, here you go:\n```json\n"
            + json.dumps({
                "headline": "H",
                "subheadline": "S",
                "hero_section": "Hero",
                "benefits": ["b1", "b2"],
                "cta": "Go",
                "social_proof": "Proof",
            })
            + "\n```"
        )
        result, _ = self._run(llm)
        assert result["page"]["headline"] == "H"
        assert result["page"]["benefits"] == ["b1", "b2"]

    def test_mobile_channel_sets_single_column_layout(self):
        llm = json.dumps({
            "headline": "H",
            "subheadline": "S",
            "hero_section": "Hero",
            "benefits": ["b1"],
            "cta": "Go",
            "social_proof": "P",
        })
        result, _ = self._run(llm, campaign={"goal": "conversion", "channel": "mobile"})
        assert result["page"]["layout"] == "single_column"


class TestLLMFallbackPaths:

    def _run_with_router(self, router):
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch("core.adapters.get_router", return_value=router):
            return generate_page(_PRODUCT, _CAMPAIGN, _AUDIENCE, _VOICE)

    def test_garbage_response_falls_back_to_template(self):
        router = SimpleNamespace(
            execute=lambda c, p: _ok({"text": "I am not JSON.", "model": "x"}),
        )
        result = self._run_with_router(router)
        assert result["status"] == "success"
        assert "YouthBoost" in result["page"]["headline"]  # template hallmark

    def test_router_not_ok_falls_back(self):
        router = SimpleNamespace(execute=lambda c, p: _fail("upstream timeout"))
        result = self._run_with_router(router)
        assert result["status"] == "success"
        assert "YouthBoost" in result["page"]["headline"]

    def test_router_raises_falls_back(self):
        def _raises(c, p):
            raise RuntimeError("boom")
        router = SimpleNamespace(execute=_raises)
        result = self._run_with_router(router)
        assert result["status"] == "success"
        assert "YouthBoost" in result["page"]["headline"]

    def test_missing_cta_falls_back(self):
        llm = json.dumps({
            "headline": "H",
            "subheadline": "S",
            "hero_section": "Hero",
            "benefits": ["b1"],
            # no cta
            "social_proof": "P",
        })
        router = SimpleNamespace(execute=lambda c, p: _ok({"text": llm, "model": "x"}))
        result = self._run_with_router(router)
        # Template path uses YouthBoost
        assert "YouthBoost" in result["page"]["headline"]

    def test_empty_benefits_falls_back(self):
        """Benefits is load-bearing for a landing page -- an
        LLM that returns no benefits is treated as failure."""
        llm = json.dumps({
            "headline": "H",
            "subheadline": "S",
            "hero_section": "Hero",
            "benefits": [],  # empty
            "cta": "Go",
            "social_proof": "P",
        })
        router = SimpleNamespace(execute=lambda c, p: _ok({"text": llm, "model": "x"}))
        result = self._run_with_router(router)
        assert "YouthBoost" in result["page"]["headline"]
