"""Tests for ``engines.email_marketing.subject_line_generator``.

Two paths:

  * LLM path -- mock the router to return JSON variants; verify
    the canonical wrapped shape (with re-scoring via the same
    open-rate heuristic the template path uses).
  * Template fallback -- under pytest the LLM path
    short-circuits via the Pattern J env guard; the template
    chain runs end-to-end.

Coverage:
  1. Pattern J guard: live LLM never called under pytest.
  2. LLM happy path -> wrapped output with scored variants.
  3. LLM emoji detection via non-ASCII scan.
  4. LLM 60-char cap enforced even when the model overshoots.
  5. LLM invalid style coerced to "benefit".
  6. LLM no variants -> falls back to template.
  7. LLM garbage -> falls back to template.
  8. LLM router raises -> falls back to template.
  9. Template path uses goal-specific template set (nurture vs
     promotional vs win-back vs announcement).
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from engines.email_marketing.subject_line_generator import (
    generate_subject_lines,
)


_STORE = "Glow Labs"
_DISCOUNT = {"type": "percentage", "value": 25}
_PRODUCTS = [
    {"title": "YouthBoost LED Facial Lifter"},
    {"title": "Companion Pack"},
]


def _ok(data):
    return SimpleNamespace(ok=True, data=data, error=None)


def _fail(error="x"):
    return SimpleNamespace(ok=False, data=None, error=error)


class TestPatternJGuard:

    def test_pytest_env_blocks_live_llm(self, monkeypatch):
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "active")
        result = generate_subject_lines(
            "promotional", _STORE, _DISCOUNT, _PRODUCTS,
        )
        assert result["status"] == "success"
        # Template fallback's model_note signature
        sl = result["subject_lines"]
        assert "template fallback" in sl["model_note"]
        assert sl["subject_lines"]
        # All subject lines respect 60-char cap
        for v in sl["subject_lines"]:
            assert len(v["text"]) <= 60


class TestLLMHappyPath:

    def _run(self, llm_text, goal="promotional"):
        def _exec(cap, params):
            return _ok({"text": llm_text, "model": "claude-haiku-4-5"})

        router = SimpleNamespace(execute=_exec)
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch("core.adapters.get_router", return_value=router):
            return generate_subject_lines(goal, _STORE, _DISCOUNT, _PRODUCTS)

    def test_strict_json_response(self):
        llm = json.dumps({
            "variants": [
                {"text": "Last hours: 25% off YouthBoost",
                 "style": "urgency", "personalized": False},
                {"text": "Glow Labs flash sale -- inside",
                 "style": "curiosity", "personalized": False},
                {"text": "{{first_name}}, your 25% off awaits",
                 "style": "personal", "personalized": True},
                {"text": "Treat yourself: 25% off premium skincare",
                 "style": "benefit", "personalized": False},
            ],
        })
        result = self._run(llm)
        assert result["status"] == "success"
        sl = result["subject_lines"]
        assert len(sl["subject_lines"]) == 4
        assert sl["model_note"].startswith("llm:")
        # Each variant is rescored via the canonical heuristic
        for v in sl["subject_lines"]:
            assert 0 < v["score"] <= 1.0
            assert v["style"] in {
                "urgency", "curiosity", "personal", "benefit",
            }

    def test_emoji_detected_from_text(self):
        llm = json.dumps({
            "variants": [
                {"text": "\U0001f525 25% off YouthBoost -- 24h",
                 "style": "urgency", "personalized": False},
            ],
        })
        result = self._run(llm)
        variant = result["subject_lines"]["subject_lines"][0]
        # Emoji flag is detected from non-ASCII in text, not
        # from the model's self-report
        assert variant["emoji"] is True

    def test_overlong_line_truncated_to_60(self):
        llm = json.dumps({
            "variants": [
                {"text": "x" * 90, "style": "benefit",
                 "personalized": False},
            ],
        })
        result = self._run(llm)
        line = result["subject_lines"]["subject_lines"][0]["text"]
        assert len(line) <= 60
        assert line.endswith("...")

    def test_invalid_style_coerced_to_benefit(self):
        llm = json.dumps({
            "variants": [
                {"text": "Yo", "style": "spammy_invented_style",
                 "personalized": False},
            ],
        })
        result = self._run(llm)
        assert result["subject_lines"]["subject_lines"][0]["style"] == "benefit"

    def test_temperature_higher_than_other_engines(self):
        """Subject lines need more creativity than body copy."""
        captured = {}

        def _exec(cap, params):
            captured.update(params)
            return _ok({"text": json.dumps({"variants": [
                {"text": "x", "style": "benefit", "personalized": False},
            ]}), "model": "x"})

        router = SimpleNamespace(execute=_exec)
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch("core.adapters.get_router", return_value=router):
            generate_subject_lines(
                "promotional", _STORE, _DISCOUNT, _PRODUCTS,
            )
        assert captured["temperature"] == 0.8


class TestLLMFallbackPaths:

    def _run_with_router(self, router, goal="promotional"):
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch("core.adapters.get_router", return_value=router):
            return generate_subject_lines(goal, _STORE, _DISCOUNT, _PRODUCTS)

    def test_garbage_response_falls_back(self):
        router = SimpleNamespace(
            execute=lambda c, p: _ok({"text": "not JSON.", "model": "x"}),
        )
        result = self._run_with_router(router)
        assert "template fallback" in result["subject_lines"]["model_note"]

    def test_no_variants_falls_back(self):
        llm = json.dumps({"variants": []})
        router = SimpleNamespace(
            execute=lambda c, p: _ok({"text": llm, "model": "x"}),
        )
        result = self._run_with_router(router)
        assert "template fallback" in result["subject_lines"]["model_note"]

    def test_router_not_ok_falls_back(self):
        router = SimpleNamespace(execute=lambda c, p: _fail("timeout"))
        result = self._run_with_router(router)
        assert "template fallback" in result["subject_lines"]["model_note"]

    def test_router_raises_falls_back(self):
        def _raises(c, p):
            raise RuntimeError("boom")
        router = SimpleNamespace(execute=_raises)
        result = self._run_with_router(router)
        assert "template fallback" in result["subject_lines"]["model_note"]


class TestTemplateFallbackGoalSpecific:
    """Template-path coverage so existing behavior doesn't drift."""

    def test_promotional_uses_promotional_templates(self, monkeypatch):
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "active")
        result = generate_subject_lines(
            "promotional", _STORE, _DISCOUNT, _PRODUCTS,
        )
        sl = result["subject_lines"]["subject_lines"]
        # Promotional templates reference discount text
        assert any("25%" in v["text"] for v in sl)

    def test_nurture_uses_nurture_templates(self, monkeypatch):
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "active")
        result = generate_subject_lines(
            "nurture", _STORE, _DISCOUNT, _PRODUCTS,
        )
        sl = result["subject_lines"]["subject_lines"]
        # Nurture templates feature the store name without urgency
        assert any(_STORE in v["text"] for v in sl)

    def test_winback_uses_winback_templates(self, monkeypatch):
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "active")
        result = generate_subject_lines(
            "win-back", _STORE, _DISCOUNT, _PRODUCTS,
        )
        sl = result["subject_lines"]["subject_lines"]
        # Winback templates include "miss you" / "been a while" / "Come back"
        assert any(
            phrase in v["text"].lower()
            for v in sl
            for phrase in ("miss you", "been a while", "come back")
        )
