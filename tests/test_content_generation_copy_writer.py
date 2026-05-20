"""Tests for ``engines.content_generation.copy_writer``.

Two paths are exercised:

  * LLM path -- mock the router's ``execute(Capability.CHAT_COMPLETE,
    ...)`` to return a known JSON response; verify the parser
    produces the canonical draft dict.
  * Template fallback -- with no LLM mock, the writer returns the
    deterministic template-built draft (because the Pattern J
    guard short-circuits the live LLM call under pytest).

Coverage:
  1. Pattern J guard: live LLM never called under pytest.
  2. LLM happy path returns JSON -> parsed draft.
  3. LLM returns markdown-fenced JSON -> regex falls back, parsed.
  4. LLM returns garbage -> caller falls back to template path.
  5. LLM router returns ok=False -> falls back to template path.
  6. LLM raises -> falls back to template path.
  7. Bullets/alt_headlines validation: missing/empty values OK.
  8. Headline + body are mandatory; without them the LLM result is
     discarded and the template runs.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from engines.content_generation.copy_writer import write_copy


_BRIEF = {
    "content_type": "product_description",
    "usps": ["FDA approved", "Lifetime warranty"],
    "target_audience": "skincare enthusiasts aged 30-55",
    "desired_outcome": "drive first purchase",
}
_TONE = {"primary_tone": "professional", "emotional_appeal": "trust"}
_KEYWORDS = {
    "primary_keywords": ["LED facial device"],
    "secondary_keywords": ["anti-aging", "skin firming"],
}
_PRODUCT = {
    "title": "YouthBoost LED Facial Lifter",
    "features": ["6 LED wavelengths", "Wireless charging", "Aluminum body"],
    "price": 199.0,
    "category": "Skincare",
}
_BRAND = {"name": "Glow Labs"}


def _ok(data):
    return SimpleNamespace(ok=True, data=data, error=None)


def _fail(error="x"):
    return SimpleNamespace(ok=False, data=None, error=error)


class TestPatternJGuard:

    def test_pytest_env_blocks_live_llm(self, monkeypatch):
        """Under pytest, the LLM path short-circuits without
        even importing the router -- so falls back to template."""
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "active")
        # No router mock -- if the LLM path tried to call it we'd
        # crash. Template fallback must run cleanly.
        result = write_copy(_BRIEF, _TONE, _KEYWORDS, _PRODUCT, _BRAND)
        assert result["status"] == "success"
        # Template fallback's model_note signature
        assert "template fallback" in result["draft"]["model_note"]


class TestLLMHappyPath:

    def _run_with_llm(self, llm_text, max_tokens_seen=None):
        seen_params = {}

        def _exec(cap, params):
            seen_params.update(params)
            return _ok({"text": llm_text, "model": "claude-haiku-4-5"})

        router = SimpleNamespace(execute=_exec)
        with patch.dict("os.environ", {}, clear=False), \
             patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch("core.adapters.get_router", return_value=router):
            # NB: PYTEST_CURRENT_TEST cleared above so the guard
            # doesn't short-circuit; the patched router still
            # intercepts the call so no live HTTP fires.
            result = write_copy(_BRIEF, _TONE, _KEYWORDS, _PRODUCT, _BRAND)
        return result, seen_params

    def test_strict_json_response(self):
        llm = json.dumps({
            "headline": "Glow at Any Age",
            "alt_headlines": ["The Lifter That Works", "Skin Reset"],
            "body": "Treat your skin to lifelike radiance...",
            "bullets": ["6 wavelengths", "Wireless", "Pro grade"],
            "cta": "Reveal Your Glow",
        })
        result, params = self._run_with_llm(llm)
        assert result["status"] == "success"
        d = result["draft"]
        assert d["headline"] == "Glow at Any Age"
        assert d["body"].startswith("Treat your skin")
        assert d["bullets"] == ["6 wavelengths", "Wireless", "Pro grade"]
        assert d["cta"] == "Reveal Your Glow"
        assert "Skin Reset" in d["alt_headlines"]
        assert d["model_note"].startswith("llm:")
        # Prompt includes product context
        assert "YouthBoost" in params.get("prompt", "")
        assert params.get("max_tokens") == 800  # product_description budget

    def test_markdown_fenced_json_still_parses(self):
        llm = (
            "Here you go:\n```json\n"
            + json.dumps({
                "headline": "H",
                "body": "B paragraph",
                "bullets": ["a", "b"],
                "cta": "Buy",
                "alt_headlines": [],
            })
            + "\n```"
        )
        result, _ = self._run_with_llm(llm)
        assert result["draft"]["headline"] == "H"
        assert result["draft"]["body"] == "B paragraph"

    def test_missing_cta_uses_template_cta(self):
        llm = json.dumps({
            "headline": "H", "body": "B",
            "bullets": ["x"], "alt_headlines": [],
            # no cta
        })
        result, _ = self._run_with_llm(llm)
        # Should fall back to canned product_description CTA
        assert result["draft"]["cta"] == "Shop Now"


class TestLLMFallbackPaths:

    def test_garbage_response_falls_back_to_template(self):
        """LLM returns prose with no JSON anywhere -> template
        path runs, draft is deterministic."""
        router = SimpleNamespace(
            execute=lambda c, p: _ok({"text": "I am not JSON.", "model": "x"}),
        )
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch("core.adapters.get_router", return_value=router):
            result = write_copy(_BRIEF, _TONE, _KEYWORDS, _PRODUCT, _BRAND)
        assert result["status"] == "success"
        assert "template fallback" in result["draft"]["model_note"]
        # Template path uses YouthBoost in the headline
        assert "YouthBoost" in result["draft"]["headline"]

    def test_router_not_ok_falls_back(self):
        router = SimpleNamespace(execute=lambda c, p: _fail("upstream timeout"))
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch("core.adapters.get_router", return_value=router):
            result = write_copy(_BRIEF, _TONE, _KEYWORDS, _PRODUCT, _BRAND)
        assert result["status"] == "success"
        assert "template fallback" in result["draft"]["model_note"]

    def test_router_raises_falls_back(self):
        def _raises(c, p):
            raise RuntimeError("boom")

        router = SimpleNamespace(execute=_raises)
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch("core.adapters.get_router", return_value=router):
            result = write_copy(_BRIEF, _TONE, _KEYWORDS, _PRODUCT, _BRAND)
        assert result["status"] == "success"
        assert "template fallback" in result["draft"]["model_note"]

    def test_missing_headline_or_body_falls_back(self):
        # LLM returns valid JSON shape but headline empty -> reject
        llm = json.dumps({
            "headline": "",
            "body": "B",
            "bullets": ["x"],
            "alt_headlines": [],
            "cta": "Go",
        })
        router = SimpleNamespace(
            execute=lambda c, p: _ok({"text": llm, "model": "x"}),
        )
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch("core.adapters.get_router", return_value=router):
            result = write_copy(_BRIEF, _TONE, _KEYWORDS, _PRODUCT, _BRAND)
        assert "template fallback" in result["draft"]["model_note"]


class TestContentTypeBudgets:

    def test_blog_uses_larger_token_budget(self):
        seen = {}

        def _exec(c, p):
            seen.update(p)
            return _ok({
                "text": json.dumps({
                    "headline": "H",
                    "body": "B body",
                    "bullets": [],
                    "alt_headlines": [],
                    "cta": "X",
                }),
                "model": "x",
            })

        router = SimpleNamespace(execute=_exec)
        brief = dict(_BRIEF)
        brief["content_type"] = "blog"
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch("core.adapters.get_router", return_value=router):
            write_copy(brief, _TONE, _KEYWORDS, _PRODUCT, _BRAND)
        # Blog gets a 2000-token budget vs 800 for product_description.
        assert seen["max_tokens"] == 2000
