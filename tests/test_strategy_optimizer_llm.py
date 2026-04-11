"""Tests for the LLM-backed StrategyOptimizer.refine_with_llm."""
import os
import tempfile

import pytest


# ── Helpers ──────────────────────────────────────────────────


class _FakeStructured:
    def __init__(self, ok=True, data=None, error=""):
        self.ok = ok
        self.data = data or {}
        self.error = error
        self.raw_text = ""


class _FakeLLM:
    def __init__(self, *, available=True, structured_data=None,
                 raise_on_call=False):
        self._available = available
        self._structured = structured_data
        self._raise = raise_on_call
        self.calls = []

    def is_available(self):
        return self._available

    def ask_structured(self, role="", prompt="", system_prompt="",
                       schema_hint="", **kw):
        self.calls.append({"role": role, "prompt": prompt})
        if self._raise:
            raise RuntimeError("LLM down")
        if self._structured is None:
            return _FakeStructured(ok=False, error="no data")
        return _FakeStructured(ok=True, data=self._structured)


@pytest.fixture(autouse=True)
def isolated_strategy_path(monkeypatch, tmp_path):
    """Point _STRATEGY_PATH at a temp file so tests don't share state."""
    from core.intelligence import strategy_optimizer as so
    monkeypatch.setattr(so, "_STRATEGY_PATH", str(tmp_path / "strategy.json"))


def _so(llm=None):
    from core.intelligence.strategy_optimizer import StrategyOptimizer
    return StrategyOptimizer(llm=llm)


_PERF = {
    "revenue_trend": "declining",
    "margin": 0.42,
    "ad_spend_pct": 0.18,
}


# ── Heuristic always runs ────────────────────────────────────


class TestHeuristicAlwaysRuns:
    def test_no_llm_returns_heuristic_only(self):
        so = _so()
        result = so.refine_with_llm("maximize_profit", performance_data=_PERF)
        assert result["source"] == "heuristic_only"
        assert result["heuristic"] is not None
        assert result["llm"] is None

    def test_unavailable_llm_returns_heuristic_only(self):
        so = _so(_FakeLLM(available=False))
        result = so.refine_with_llm("maximize_profit", performance_data=_PERF)
        assert result["source"] == "heuristic_only"

    def test_llm_exception_returns_heuristic_with_error(self):
        so = _so(_FakeLLM(raise_on_call=True))
        result = so.refine_with_llm("maximize_profit", performance_data=_PERF)
        assert result["heuristic"] is not None
        assert "error" in result["llm"]


# ── LLM happy path ───────────────────────────────────────────


class TestLLMHappyPath:
    def test_full_refinement(self):
        llm = _FakeLLM(structured_data={
            "recommended_goal": "grow_customers",
            "weight_changes": {
                "customer_acquisition": 0.15,
                "ad_spend_efficiency": 0.10,
                "profit_margin": -0.05,
            },
            "rationale": "Revenue declining and margin still healthy — "
                         "tighten ad spend rather than panic-switch goals.",
            "confidence": 0.78,
            "risks": [
                "switching focus may slow short-term profit",
                "need to monitor LTV closely",
            ],
        })
        so = _so(llm)
        result = so.refine_with_llm("maximize_profit", performance_data=_PERF)
        assert result["source"] == "llm"
        rec = result["llm"]
        assert rec["recommended_goal"] == "grow_customers"
        assert rec["weight_changes"]["customer_acquisition"] == 0.15
        assert rec["confidence"] == 0.78
        assert len(rec["risks"]) == 2
        assert "ad spend" in rec["rationale"].lower()
        # Heuristic still preserved
        assert result["heuristic"] is not None
        assert len(llm.calls) == 1

    def test_prompt_includes_context(self):
        llm = _FakeLLM(structured_data={
            "recommended_goal": "maximize_profit",
            "weight_changes": {},
            "rationale": "endorsed",
            "confidence": 0.6,
            "risks": [],
        })
        so = _so(llm)
        so.refine_with_llm("maximize_profit", performance_data=_PERF)
        prompt = llm.calls[0]["prompt"]
        assert "maximize_profit" in prompt
        assert "declining" in prompt or "revenue_trend" in prompt

    def test_weight_changes_capped_at_8(self):
        llm = _FakeLLM(structured_data={
            "recommended_goal": "maximize_profit",
            "weight_changes": {f"factor_{i}": 0.05 for i in range(20)},
            "rationale": "many tweaks",
            "confidence": 0.5,
            "risks": [],
        })
        so = _so(llm)
        result = so.refine_with_llm("maximize_profit")
        assert len(result["llm"]["weight_changes"]) == 8

    def test_risks_capped_at_5(self):
        llm = _FakeLLM(structured_data={
            "recommended_goal": "maximize_profit",
            "weight_changes": {},
            "rationale": "x",
            "confidence": 0.5,
            "risks": [f"risk{i}" for i in range(20)],
        })
        so = _so(llm)
        result = so.refine_with_llm("maximize_profit")
        assert len(result["llm"]["risks"]) == 5


# ── Defensive: bad LLM responses ─────────────────────────────


class TestLLMDefensive:
    def test_unparseable_returns_error(self):
        so = _so(_FakeLLM(structured_data=None))
        result = so.refine_with_llm("maximize_profit")
        assert result["source"] == "heuristic_only"
        assert "error" in result["llm"]

    def test_clamps_confidence_and_weights(self):
        llm = _FakeLLM(structured_data={
            "recommended_goal": "maximize_profit",
            "weight_changes": {
                "huge": 5.0,    # > 1.0 → clamped
                "tiny": -3.0,   # < -1.0 → clamped
                "ok": 0.2,
            },
            "rationale": "x",
            "confidence": 1.5,  # > 1.0 → clamped
            "risks": [],
        })
        so = _so(llm)
        result = so.refine_with_llm("maximize_profit")
        rec = result["llm"]
        assert rec["confidence"] == 1.0
        assert rec["weight_changes"]["huge"] == 1.0
        assert rec["weight_changes"]["tiny"] == -1.0
        assert rec["weight_changes"]["ok"] == 0.2

    def test_non_numeric_weight_filtered(self):
        llm = _FakeLLM(structured_data={
            "recommended_goal": "maximize_profit",
            "weight_changes": {"good": 0.1, "bad": "huge"},
            "rationale": "x",
            "confidence": 0.5,
            "risks": [],
        })
        so = _so(llm)
        result = so.refine_with_llm("maximize_profit")
        assert "good" in result["llm"]["weight_changes"]
        assert "bad" not in result["llm"]["weight_changes"]

    def test_weight_changes_not_a_dict(self):
        llm = _FakeLLM(structured_data={
            "recommended_goal": "maximize_profit",
            "weight_changes": "should be a dict",
            "rationale": "x",
            "confidence": 0.5,
            "risks": [],
        })
        so = _so(llm)
        result = so.refine_with_llm("maximize_profit")
        assert result["llm"]["weight_changes"] == {}

    def test_non_numeric_confidence_normalization_error(self):
        llm = _FakeLLM(structured_data={
            "recommended_goal": "maximize_profit",
            "weight_changes": {},
            "rationale": "x",
            "confidence": "high",  # bad
            "risks": [],
        })
        so = _so(llm)
        result = so.refine_with_llm("maximize_profit")
        assert "error" in result["llm"]

    def test_missing_recommended_goal_falls_back_to_current(self):
        llm = _FakeLLM(structured_data={
            "weight_changes": {},
            "rationale": "x",
            "confidence": 0.5,
            "risks": [],
        })
        so = _so(llm)
        result = so.refine_with_llm("maximize_profit")
        assert result["llm"]["recommended_goal"] == "maximize_profit"


# ── Prompt registered ────────────────────────────────────────


class TestPromptRegistered:
    def test_strategy_refine_prompt_exists(self):
        from core.system.prompt_library import get_prompt
        p = get_prompt("strategy.refine")
        assert p is not None
        assert p.role == "reasoner"
        assert "current_goal" in p.placeholders
        assert "heuristic_summary" in p.placeholders
