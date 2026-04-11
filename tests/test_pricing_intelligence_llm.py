"""Tests for the LLM-backed PricingIntelligence.recommend_with_llm."""
import pytest


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


def _pi(llm=None):
    from core.intelligence.pricing_intelligence import PricingIntelligence
    return PricingIntelligence(llm=llm)


_PRODUCT = {
    "name": "Cozy Lamp",
    "price": 29.99,
    "cost": 12.50,
}


# ── Heuristic always runs ────────────────────────────────────


class TestHeuristicAlwaysRuns:
    def test_no_llm_returns_heuristic_only(self):
        pi = _pi()
        result = pi.recommend_with_llm(_PRODUCT, competitor_prices=[24.99, 32.50])
        assert result["source"] == "heuristic_only"
        assert result["heuristic"] is not None
        assert result["heuristic"]["competitor_count"] == 2
        assert result["llm"] is None

    def test_unavailable_llm_returns_heuristic_only(self):
        pi = _pi(_FakeLLM(available=False))
        result = pi.recommend_with_llm(_PRODUCT, competitor_prices=[24.99])
        assert result["source"] == "heuristic_only"

    def test_llm_exception_returns_heuristic_only_with_error(self):
        pi = _pi(_FakeLLM(raise_on_call=True))
        result = pi.recommend_with_llm(_PRODUCT, competitor_prices=[24.99])
        # Heuristic still runs
        assert result["heuristic"] is not None
        # LLM block carries the error
        assert result["llm"]["error"]


# ── LLM happy path ───────────────────────────────────────────


class TestLLMHappyPath:
    def test_full_recommendation(self):
        llm = _FakeLLM(structured_data={
            "action": "lower",
            "new_price": 27.99,
            "delta_pct": -6.7,
            "reasoning": "Slightly under competitor average to win share",
            "confidence": 0.75,
            "risks": ["margin compression", "brand perception"],
        })
        pi = _pi(llm)
        result = pi.recommend_with_llm(
            _PRODUCT, competitor_prices=[29.99, 28.50, 30.00],
        )
        assert result["source"] == "llm"
        rec = result["llm"]
        assert rec["action"] == "lower"
        assert rec["new_price"] == 27.99
        assert rec["delta_pct"] == -6.7
        assert rec["confidence"] == 0.75
        assert "margin compression" in rec["risks"]
        # Heuristic still present
        assert result["heuristic"]["competitor_avg"] > 0
        # LLM was called
        assert len(llm.calls) == 1

    def test_llm_prompt_includes_product_data(self):
        llm = _FakeLLM(structured_data={
            "action": "hold",
            "new_price": 29.99,
            "delta_pct": 0,
            "reasoning": "ok",
            "confidence": 0.6,
            "risks": [],
        })
        pi = _pi(llm)
        pi.recommend_with_llm(
            _PRODUCT,
            recent_sales=[{"id": 1}, {"id": 2}],
            competitor_prices=[28.0, 30.0],
        )
        prompt = llm.calls[0]["prompt"]
        assert "Cozy Lamp" in prompt
        assert "29.99" in prompt
        assert "12.5" in prompt or "12.50" in prompt
        assert "28.0" in prompt or "$28" in prompt


# ── Defensive: bad LLM responses ─────────────────────────────


class TestLLMDefensive:
    def test_unparseable_returns_error_block(self):
        llm = _FakeLLM(structured_data=None)  # ok=False
        pi = _pi(llm)
        result = pi.recommend_with_llm(_PRODUCT, competitor_prices=[20])
        assert result["source"] == "heuristic_only"
        assert "error" in result["llm"]

    def test_missing_fields_use_defaults(self):
        # LLM omits delta_pct and risks
        llm = _FakeLLM(structured_data={
            "action": "raise",
            "new_price": 32.50,
            "reasoning": "premium positioning",
            "confidence": 0.8,
        })
        pi = _pi(llm)
        result = pi.recommend_with_llm(_PRODUCT, competitor_prices=[28.0])
        rec = result["llm"]
        assert rec["action"] == "raise"
        assert rec["new_price"] == 32.50
        # Missing fields default to safe values
        assert rec["delta_pct"] == 0
        assert rec["risks"] == []

    def test_clamps_confidence_out_of_range(self):
        llm = _FakeLLM(structured_data={
            "action": "hold",
            "new_price": 29.99,
            "confidence": 2.5,  # > 1.0
        })
        pi = _pi(llm)
        result = pi.recommend_with_llm(_PRODUCT, competitor_prices=[28.0])
        assert result["llm"]["confidence"] == 1.0

    def test_non_numeric_new_price_is_normalization_failure(self):
        llm = _FakeLLM(structured_data={
            "action": "lower",
            "new_price": "twenty",  # bad
            "confidence": 0.7,
        })
        pi = _pi(llm)
        result = pi.recommend_with_llm(_PRODUCT, competitor_prices=[28.0])
        assert "error" in result["llm"]
        assert "normalization" in result["llm"]["error"]


# ── Empty / edge inputs ──────────────────────────────────────


class TestEdgeInputs:
    def test_no_competitors(self):
        pi = _pi()
        result = pi.recommend_with_llm(_PRODUCT)
        # Heuristic returns no_data
        assert result["heuristic"]["position"] == "no_data"
        assert result["source"] == "heuristic_only"

    def test_zero_cost_handled(self):
        pi = _pi()
        result = pi.recommend_with_llm({"name": "X", "price": 10, "cost": 0})
        assert result is not None
        assert result["heuristic"] is not None

    def test_zero_price_handled(self):
        pi = _pi()
        result = pi.recommend_with_llm({"name": "X", "price": 0, "cost": 5})
        # Heuristic still runs (returns no_data via competitor flow)
        assert result is not None

    def test_unknown_product_name(self):
        pi = _pi()
        result = pi.recommend_with_llm({"price": 10, "cost": 5})
        # Should not crash, heuristic uses "Unknown"
        assert result is not None
