"""Tests for the LLM-backed MarketingTactics.synthesize_strategy_with_llm."""
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


def _mt(llm=None):
    from core.intelligence.marketing_tactics import MarketingTactics
    return MarketingTactics(llm=llm)


_CAMPAIGNS = [
    {
        "name": "Spring Sale", "id": "c1",
        "creative_id": "c1_v1",
        "days_running": 25, "ctr_trend": -0.4,
        "interests": ["fashion", "spring"],
        "age_range": (25, 45),
    },
    {
        "name": "Brand Aware", "id": "c2",
        "creative_id": "c2_v1",
        "days_running": 5, "ctr_trend": 0.1,
        "interests": ["fashion", "lifestyle"],
        "age_range": (22, 42),
    },
]

_PRODUCTS = [
    {
        "name": "Wool Sweater", "price": 89,
        "review_count": 12, "rating": 4.6,
        "review_text_count": 5, "review_photo_count": 0,
    },
]

_CUSTOMERS = [
    {"id": 1, "lifetime_value": 250, "orders_count": 4},
    {"id": 2, "lifetime_value": 80, "orders_count": 1},
]


# ── Heuristic always runs ────────────────────────────────────


class TestHeuristicAlwaysRuns:
    def test_no_llm_returns_heuristic_only(self):
        mt = _mt()
        result = mt.synthesize_strategy_with_llm(
            campaigns=_CAMPAIGNS, products=_PRODUCTS,
        )
        assert result["source"] == "heuristic_only"
        assert result["heuristic"] is not None
        # Should contain at least some of the expected sections
        assert any(k in result["heuristic"] for k in (
            "creative_fatigue", "social_proof_audit",
            "audience_overlap", "influencer_strategy",
        ))
        assert result["llm"] is None

    def test_unavailable_llm_returns_heuristic_only(self):
        mt = _mt(_FakeLLM(available=False))
        result = mt.synthesize_strategy_with_llm(campaigns=_CAMPAIGNS)
        assert result["source"] == "heuristic_only"

    def test_llm_exception_returns_heuristic_with_error(self):
        mt = _mt(_FakeLLM(raise_on_call=True))
        result = mt.synthesize_strategy_with_llm(campaigns=_CAMPAIGNS)
        assert result["heuristic"] is not None
        assert "error" in result["llm"]


# ── Empty input shortcut ─────────────────────────────────────


class TestEmptyInput:
    def test_no_inputs_skips_llm(self):
        mt = _mt(_FakeLLM(structured_data={
            "priorities": ["x"],
            "top_action": "x",
            "expected_lift_pct": 5,
            "confidence": 0.8,
            "reasoning": "x",
        }))
        result = mt.synthesize_strategy_with_llm()
        # Heuristic returns empty dict → shortcut path skips LLM
        assert result["source"] == "heuristic_only"


# ── LLM happy path ───────────────────────────────────────────


class TestLLMHappyPath:
    def test_full_synthesis(self):
        llm = _FakeLLM(structured_data={
            "priorities": [
                "Refresh Spring Sale creative — fatigue at 25 days",
                "Add review photos to Wool Sweater",
                "Exclude lookalikes between c1 and c2 audiences",
            ],
            "top_action": "Pause Spring Sale and ship a new variant",
            "expected_lift_pct": 18.5,
            "confidence": 0.78,
            "reasoning": "Both c1's CTR is dropping AND audience overlap "
                         "with c2 is high, so the cheap fix is one creative "
                         "swap that fixes both.",
        })
        mt = _mt(llm)
        result = mt.synthesize_strategy_with_llm(
            campaigns=_CAMPAIGNS, products=_PRODUCTS, customers=_CUSTOMERS,
        )
        assert result["source"] == "llm"
        rec = result["llm"]
        assert len(rec["priorities"]) == 3
        assert "Spring Sale" in rec["top_action"]
        assert rec["expected_lift_pct"] == 18.5
        assert rec["confidence"] == 0.78
        assert "creative" in rec["reasoning"].lower()
        # Heuristic still preserved
        assert result["heuristic"]
        # LLM was called
        assert len(llm.calls) == 1

    def test_prompt_includes_input_counts(self):
        llm = _FakeLLM(structured_data={
            "priorities": [], "top_action": "", "expected_lift_pct": 0,
            "confidence": 0.5, "reasoning": "",
        })
        mt = _mt(llm)
        mt.synthesize_strategy_with_llm(
            campaigns=_CAMPAIGNS, products=_PRODUCTS, customers=_CUSTOMERS,
        )
        prompt = llm.calls[0]["prompt"]
        # Counts surfaced into the prompt
        assert "2 campaigns" in prompt
        assert "1 products" in prompt
        assert "2 customers" in prompt
        # Heuristic JSON snippet appears
        assert "creative_fatigue" in prompt or "social_proof" in prompt

    def test_priorities_capped_at_8(self):
        llm = _FakeLLM(structured_data={
            "priorities": [f"p{i}" for i in range(20)],
            "top_action": "x",
            "expected_lift_pct": 5,
            "confidence": 0.5,
            "reasoning": "x",
        })
        mt = _mt(llm)
        result = mt.synthesize_strategy_with_llm(campaigns=_CAMPAIGNS)
        assert len(result["llm"]["priorities"]) == 8


# ── Defensive: bad LLM responses ─────────────────────────────


class TestLLMDefensive:
    def test_unparseable_returns_error(self):
        mt = _mt(_FakeLLM(structured_data=None))
        result = mt.synthesize_strategy_with_llm(campaigns=_CAMPAIGNS)
        assert result["source"] == "heuristic_only"
        assert "error" in result["llm"]

    def test_clamps_confidence(self):
        llm = _FakeLLM(structured_data={
            "priorities": [], "top_action": "x",
            "expected_lift_pct": 5,
            "confidence": 2.0,  # > 1.0
            "reasoning": "x",
        })
        mt = _mt(llm)
        result = mt.synthesize_strategy_with_llm(campaigns=_CAMPAIGNS)
        assert result["llm"]["confidence"] == 1.0

    def test_non_numeric_lift_is_error(self):
        llm = _FakeLLM(structured_data={
            "priorities": [], "top_action": "x",
            "expected_lift_pct": "very high",  # bad
            "confidence": 0.5,
            "reasoning": "x",
        })
        mt = _mt(llm)
        result = mt.synthesize_strategy_with_llm(campaigns=_CAMPAIGNS)
        assert "error" in result["llm"]
        assert "normalization" in result["llm"]["error"]

    def test_missing_priorities_default_empty(self):
        llm = _FakeLLM(structured_data={
            "top_action": "do the thing",
            "expected_lift_pct": 10,
            "confidence": 0.6,
            "reasoning": "x",
        })
        mt = _mt(llm)
        result = mt.synthesize_strategy_with_llm(campaigns=_CAMPAIGNS)
        assert result["llm"]["priorities"] == []
        assert result["llm"]["top_action"] == "do the thing"

    def test_priorities_not_list_defaults_empty(self):
        llm = _FakeLLM(structured_data={
            "priorities": "should be a list",  # wrong type
            "top_action": "x",
            "expected_lift_pct": 5,
            "confidence": 0.5,
            "reasoning": "x",
        })
        mt = _mt(llm)
        result = mt.synthesize_strategy_with_llm(campaigns=_CAMPAIGNS)
        assert result["llm"]["priorities"] == []


# ── Prompt registered ────────────────────────────────────────


class TestPromptRegistered:
    def test_marketing_strategy_prompt_exists(self):
        from core.system.prompt_library import get_prompt
        p = get_prompt("marketing.synthesize_strategy")
        assert p is not None
        assert p.role == "reasoner"
        assert "campaign_count" in p.placeholders
        assert "heuristic_summary" in p.placeholders
