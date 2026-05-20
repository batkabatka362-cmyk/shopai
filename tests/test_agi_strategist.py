"""Tests for ``engines.agi_strategist``.

The AGI Strategist takes a high-level merchant goal and
decomposes it into substrategies + recommended engines.
Tested paths:

  * LLM path (mocked router) -- structured JSON in, validated
    plan out. Substrategies that reference invented engine
    names are dropped silently. If NO valid substrategies
    remain, the whole LLM result is rejected and the template
    fallback runs.
  * Template path -- deterministic keyword classifier
    (revenue / retention / traffic / conversion / aov) maps to
    a canned substrategy set.
  * Pattern Q envelope -- the ``AGIStrategistEngine.run()``
    method returns ``{status, data, meta, error}``.
  * Pattern J guard -- LLM never called under pytest unless
    the router is explicitly patched.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from engines.agi_strategist import AGIStrategistEngine, decompose_goal


def _ok(data):
    return SimpleNamespace(ok=True, data=data, error=None)


def _fail(error="x"):
    return SimpleNamespace(ok=False, data=None, error=error)


# ---------------------------------------------------------------------------
# Pattern J guard / template fallback
# ---------------------------------------------------------------------------


class TestPatternJGuard:

    def test_pytest_env_blocks_live_llm(self, monkeypatch):
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "active")
        result = decompose_goal(goal="Increase revenue 10%")
        assert result["status"] == "success"
        plan = result["data"]
        assert "template fallback" in plan["model_note"]
        assert plan["substrategies"]
        # Confidence is the template-default 0.55
        assert plan["confidence"] == 0.55


# ---------------------------------------------------------------------------
# Template fallback keyword classification
# ---------------------------------------------------------------------------


class TestTemplateFallbackBuckets:

    def test_revenue_keyword(self, monkeypatch):
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "active")
        result = decompose_goal(goal="Increase revenue this quarter")
        labels = [s["label"] for s in result["data"]["substrategies"]]
        # Revenue bucket has the 3-substrategy set: traffic + conversion + aov
        assert any("traffic" in l.lower() for l in labels)
        assert any("conversion" in l.lower() for l in labels)
        assert any("aov" in l.lower() or "average" in l.lower() for l in labels)

    def test_retention_keyword(self, monkeypatch):
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "active")
        result = decompose_goal(goal="Reduce churn next quarter")
        labels = [s["label"] for s in result["data"]["substrategies"]]
        assert any("at-risk" in l.lower() or "churn" in l.lower() for l in labels)
        assert any("loyal" in l.lower() or "loyalty" in l.lower() for l in labels)

    def test_traffic_keyword(self, monkeypatch):
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "active")
        result = decompose_goal(goal="Drive more visitors to the storefront")
        labels = [s["label"] for s in result["data"]["substrategies"]]
        # Traffic bucket -> capture-organic + re-engage-warm
        assert any("organic" in l.lower() for l in labels)
        assert any(
            "re-engage" in l.lower() or "warm" in l.lower() for l in labels
        )

    def test_conversion_keyword(self, monkeypatch):
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "active")
        result = decompose_goal(goal="Boost CVR on product pages")
        labels = [s["label"] for s in result["data"]["substrategies"]]
        assert any(
            "landing" in l.lower() or "product" in l.lower() for l in labels
        )

    def test_aov_keyword(self, monkeypatch):
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "active")
        result = decompose_goal(goal="Lift average order value with bundles")
        labels = [s["label"] for s in result["data"]["substrategies"]]
        assert any("bundle" in l.lower() for l in labels)

    def test_unknown_goal_defaults_to_revenue(self, monkeypatch):
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "active")
        result = decompose_goal(goal="Make the store more delightful")
        # No keyword fires -> defaults to revenue bucket
        labels = [s["label"] for s in result["data"]["substrategies"]]
        assert any("traffic" in l.lower() for l in labels)
        assert "(no LLM" in result["data"]["model_note"]

    def test_empty_goal_returns_error(self):
        result = decompose_goal(goal="")
        assert result["status"] == "error"
        assert result["error"] == "empty_goal"

    def test_whitespace_goal_returns_error(self):
        result = decompose_goal(goal="   ")
        assert result["status"] == "error"
        assert result["error"] == "empty_goal"


# ---------------------------------------------------------------------------
# LLM path (mocked router)
# ---------------------------------------------------------------------------


def _run_with_llm(llm_text, goal="Increase revenue 10% this quarter"):
    seen = {}

    def _exec(cap, params):
        seen.update(params)
        return _ok({"text": llm_text, "model": "claude-haiku-4-5"})

    router = SimpleNamespace(execute=_exec)
    with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
         patch("core.adapters.get_router", return_value=router):
        result = decompose_goal(goal=goal)
    return result, seen


class TestLLMHappyPath:

    def test_strict_json_response(self):
        llm = json.dumps({
            "substrategies": [
                {
                    "label": "Drive paid traffic",
                    "description": (
                        "Run Meta + Google ads with branded "
                        "creative + retargeting."
                    ),
                    "target_metric": "traffic",
                    "expected_lift_pct": 8.0,
                    "priority": 1,
                    "recommended_engines": [
                        "content_generation", "email_marketing",
                    ],
                },
                {
                    "label": "Lift conversion via better PDP copy",
                    "description": "LLM-generated product copy + bundles",
                    "target_metric": "conversion",
                    "expected_lift_pct": 6.0,
                    "priority": 2,
                    "recommended_engines": [
                        "content_generation", "bundle",
                    ],
                },
            ],
            "confidence": 0.75,
        })
        result, params = _run_with_llm(llm)
        assert result["status"] == "success"
        plan = result["data"]
        assert plan["model_note"].startswith("llm:")
        assert plan["confidence"] == 0.75
        assert len(plan["substrategies"]) == 2
        first = plan["substrategies"][0]
        assert first["label"] == "Drive paid traffic"
        assert first["target_metric"] == "traffic"
        assert first["priority"] == 1
        # Prompt contains goal + engine catalogue
        assert "Increase revenue 10%" in params["prompt"]
        assert "engine catalogue" in params["system"].lower() or "catalogue" in params["system"].lower()

    def test_invented_engine_substrategy_dropped(self):
        """LLM hallucinates 'magic_growth_engine' which isn't
        in our catalogue. That substrategy is dropped; a valid
        sibling is retained."""
        llm = json.dumps({
            "substrategies": [
                {
                    "label": "Mythical play",
                    "description": "Use a non-existent engine",
                    "target_metric": "revenue",
                    "expected_lift_pct": 50,
                    "priority": 1,
                    "recommended_engines": ["magic_growth_engine"],
                },
                {
                    "label": "Real play",
                    "description": "Bundle for AOV",
                    "target_metric": "aov",
                    "expected_lift_pct": 5,
                    "priority": 2,
                    "recommended_engines": ["bundle"],
                },
            ],
            "confidence": 0.8,
        })
        result, _ = _run_with_llm(llm)
        labels = [s["label"] for s in result["data"]["substrategies"]]
        assert "Mythical play" not in labels
        assert "Real play" in labels

    def test_invalid_target_metric_substrategy_dropped(self):
        """Substrategy with an unrecognised metric is dropped."""
        llm = json.dumps({
            "substrategies": [
                {
                    "label": "Bad metric",
                    "description": "y",
                    "target_metric": "vibes",  # not in valid set
                    "expected_lift_pct": 1,
                    "priority": 1,
                    "recommended_engines": ["bundle"],
                },
                {
                    "label": "Good metric",
                    "description": "x",
                    "target_metric": "aov",
                    "expected_lift_pct": 1,
                    "priority": 1,
                    "recommended_engines": ["bundle"],
                },
            ],
            "confidence": 0.5,
        })
        result, _ = _run_with_llm(llm)
        labels = [s["label"] for s in result["data"]["substrategies"]]
        assert "Bad metric" not in labels
        assert "Good metric" in labels

    def test_priority_clamped(self):
        """Priority must be 1-5; out-of-range values clamp."""
        llm = json.dumps({
            "substrategies": [
                {
                    "label": "P0 attempt",
                    "description": "x",
                    "target_metric": "aov",
                    "expected_lift_pct": 1,
                    "priority": 99,
                    "recommended_engines": ["bundle"],
                },
            ],
            "confidence": 0.5,
        })
        result, _ = _run_with_llm(llm)
        assert result["data"]["substrategies"][0]["priority"] == 5

    def test_lift_pct_clamped(self):
        """Expected lift % can't exceed 100."""
        llm = json.dumps({
            "substrategies": [
                {
                    "label": "Wildly optimistic",
                    "description": "x",
                    "target_metric": "revenue",
                    "expected_lift_pct": 1000,  # clamped to 100
                    "priority": 1,
                    "recommended_engines": ["bundle"],
                },
            ],
            "confidence": 0.5,
        })
        result, _ = _run_with_llm(llm)
        assert result["data"]["substrategies"][0]["expected_lift_pct"] == 100.0


class TestLLMFallbackPaths:

    def test_garbage_falls_back_to_template(self):
        result, _ = _run_with_llm("not JSON at all")
        assert "template fallback" in result["data"]["model_note"]

    def test_no_valid_substrategies_falls_back(self):
        """All substrategies invalid -> total fallback."""
        llm = json.dumps({
            "substrategies": [
                {"label": "x", "description": "y",
                 "target_metric": "vibes",  # bad metric
                 "recommended_engines": ["bundle"]},
            ],
            "confidence": 0.5,
        })
        result, _ = _run_with_llm(llm)
        assert "template fallback" in result["data"]["model_note"]

    def test_router_not_ok_falls_back(self):
        router = SimpleNamespace(execute=lambda c, p: _fail("timeout"))
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch("core.adapters.get_router", return_value=router):
            result = decompose_goal(goal="Increase revenue")
        assert "template fallback" in result["data"]["model_note"]

    def test_router_raises_falls_back(self):
        def _raises(c, p):
            raise RuntimeError("boom")
        router = SimpleNamespace(execute=_raises)
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch("core.adapters.get_router", return_value=router):
            result = decompose_goal(goal="Increase revenue")
        assert "template fallback" in result["data"]["model_note"]


# ---------------------------------------------------------------------------
# Pattern Q envelope -- AGIStrategistEngine.run()
# ---------------------------------------------------------------------------


class TestPatternQEnvelope:

    def test_run_with_valid_input(self):
        engine = AGIStrategistEngine()
        result = engine.run({"goal": "Increase revenue 10%"})
        # Canonical envelope keys
        assert set(result.keys()) >= {"status", "data", "meta", "error"}
        assert result["status"] in {"success", "error", "fail"}
        assert result["meta"]["engine"] == "agi_strategist"

    def test_run_with_missing_goal_returns_error(self):
        engine = AGIStrategistEngine()
        result = engine.run({})
        assert result["status"] == "error"
        assert result["error"] == "missing_or_empty_goal"
        assert result["meta"]["engine"] == "agi_strategist"

    def test_run_with_no_input_returns_error(self):
        engine = AGIStrategistEngine()
        result = engine.run(None)
        assert result["status"] == "error"
        assert result["error"] == "missing_or_empty_goal"

    def test_run_clamps_horizon_days(self):
        engine = AGIStrategistEngine()
        # Negative horizon clamped to 1
        result = engine.run({
            "goal": "Increase revenue", "horizon_days": -5,
        })
        assert result["data"]["horizon_days"] == 1
        # Excessively large horizon clamped to 2 years (730)
        result = engine.run({
            "goal": "Increase revenue", "horizon_days": 99999,
        })
        assert result["data"]["horizon_days"] == 730

    def test_run_with_bad_horizon_type_defaults(self):
        engine = AGIStrategistEngine()
        result = engine.run({
            "goal": "Increase revenue",
            "horizon_days": "not a number",
        })
        # Defaults to 90 (one quarter)
        assert result["data"]["horizon_days"] == 90

    def test_run_normalises_constraints(self):
        engine = AGIStrategistEngine()
        result = engine.run({
            "goal": "Increase revenue",
            # Mixed types + empty strings should be filtered
            "constraints": ["no ads below 2.5 ROAS", "", 42, None, " "],
        })
        # Engine doesn't echo constraints in output dict; just
        # verify no crash on the messy input.
        assert result["status"] == "success"
