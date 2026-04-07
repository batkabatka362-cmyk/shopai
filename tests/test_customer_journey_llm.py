"""Tests for the LLM-backed CustomerJourney.personalize_with_llm."""
import time

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


def _cj(llm=None):
    from core.intelligence.customer_journey import CustomerJourney
    return CustomerJourney(llm=llm)


def _customer(cid, *, ltv=200.0, orders=3, days_since_last=30):
    return {
        "id": cid,
        "lifetime_value": ltv,
        "orders_count": orders,
        "last_order_at": time.time() - days_since_last * 86400,
    }


_CUSTOMERS = [
    _customer(1, ltv=400, orders=8, days_since_last=15),    # loyal
    _customer(2, ltv=80, orders=1, days_since_last=200),    # at-risk
    _customer(3, ltv=180, orders=2, days_since_last=45),    # active
    _customer(4, ltv=0, orders=0, days_since_last=999),     # prospect
]


# ── Heuristic always runs ────────────────────────────────────


class TestHeuristicAlwaysRuns:
    def test_no_llm_returns_heuristic_only(self):
        cj = _cj()
        result = cj.personalize_with_llm(_CUSTOMERS)
        assert result["source"] == "heuristic_only"
        assert result["heuristic"] is not None
        assert "lifecycle_segments" in result["heuristic"]
        assert result["llm"] is None

    def test_unavailable_llm_returns_heuristic_only(self):
        cj = _cj(_FakeLLM(available=False))
        result = cj.personalize_with_llm(_CUSTOMERS)
        assert result["source"] == "heuristic_only"

    def test_llm_exception_returns_heuristic_with_error(self):
        cj = _cj(_FakeLLM(raise_on_call=True))
        result = cj.personalize_with_llm(_CUSTOMERS)
        assert result["heuristic"] is not None
        assert "error" in result["llm"]


# ── Empty input shortcut ─────────────────────────────────────


class TestEmptyInput:
    def test_no_customers_skips_llm(self):
        llm = _FakeLLM(structured_data={
            "segments": [],
            "top_segment": "x",
            "expected_uplift_pct": 5,
            "confidence": 0.5,
            "reasoning": "x",
        })
        cj = _cj(llm)
        result = cj.personalize_with_llm([])
        # No customers → shortcut, LLM not called
        assert result["source"] == "heuristic_only"
        assert llm.calls == []


# ── LLM happy path ───────────────────────────────────────────


class TestLLMHappyPath:
    def test_full_plan(self):
        llm = _FakeLLM(structured_data={
            "segments": [
                {
                    "name": "At-risk loyal",
                    "size_estimate": "~25%",
                    "tactic": "Win-back email with 15% loyalty discount",
                    "channel": "email",
                    "expected_response_pct": 12.5,
                },
                {
                    "name": "First-time buyers",
                    "size_estimate": "~30%",
                    "tactic": "Post-purchase nurture sequence",
                    "channel": "email",
                    "expected_response_pct": 8.0,
                },
            ],
            "top_segment": "At-risk loyal",
            "expected_uplift_pct": 14.5,
            "confidence": 0.72,
            "reasoning": "At-risk loyal customers respond best to "
                         "personalized win-back offers because they "
                         "already trust the brand.",
        })
        cj = _cj(llm)
        result = cj.personalize_with_llm(_CUSTOMERS)
        assert result["source"] == "llm"
        rec = result["llm"]
        assert len(rec["segments"]) == 2
        assert rec["segments"][0]["name"] == "At-risk loyal"
        assert rec["segments"][0]["expected_response_pct"] == 12.5
        assert rec["top_segment"] == "At-risk loyal"
        assert rec["expected_uplift_pct"] == 14.5
        assert rec["confidence"] == 0.72
        assert "win-back" in rec["reasoning"].lower() or "loyal" in rec["reasoning"].lower()
        # Heuristic still preserved
        assert result["heuristic"]
        # LLM was called
        assert len(llm.calls) == 1

    def test_prompt_includes_input_counts_and_summary(self):
        llm = _FakeLLM(structured_data={
            "segments": [],
            "top_segment": "x",
            "expected_uplift_pct": 0,
            "confidence": 0.5,
            "reasoning": "x",
        })
        cj = _cj(llm)
        cj.personalize_with_llm(_CUSTOMERS, orders=[{"id": 1}, {"id": 2}])
        prompt = llm.calls[0]["prompt"]
        assert "Customers: 4" in prompt
        assert "orders: 2" in prompt

    def test_segments_capped_at_6(self):
        llm = _FakeLLM(structured_data={
            "segments": [
                {"name": f"seg{i}", "size_estimate": "?",
                 "tactic": "x", "channel": "email",
                 "expected_response_pct": 1.0}
                for i in range(20)
            ],
            "top_segment": "seg0",
            "expected_uplift_pct": 5,
            "confidence": 0.5,
            "reasoning": "x",
        })
        cj = _cj(llm)
        result = cj.personalize_with_llm(_CUSTOMERS)
        assert len(result["llm"]["segments"]) == 6


# ── Defensive: bad LLM responses ─────────────────────────────


class TestLLMDefensive:
    def test_unparseable_returns_error(self):
        cj = _cj(_FakeLLM(structured_data=None))
        result = cj.personalize_with_llm(_CUSTOMERS)
        assert result["source"] == "heuristic_only"
        assert "error" in result["llm"]

    def test_clamps_confidence(self):
        llm = _FakeLLM(structured_data={
            "segments": [],
            "top_segment": "x",
            "expected_uplift_pct": 5,
            "confidence": 1.7,  # > 1
            "reasoning": "x",
        })
        cj = _cj(llm)
        result = cj.personalize_with_llm(_CUSTOMERS)
        assert result["llm"]["confidence"] == 1.0

    def test_segments_not_a_list_defaults_empty(self):
        llm = _FakeLLM(structured_data={
            "segments": "should be a list",
            "top_segment": "x",
            "expected_uplift_pct": 5,
            "confidence": 0.5,
            "reasoning": "x",
        })
        cj = _cj(llm)
        result = cj.personalize_with_llm(_CUSTOMERS)
        assert result["llm"]["segments"] == []

    def test_invalid_segment_shapes_filtered(self):
        llm = _FakeLLM(structured_data={
            "segments": [
                {"name": "ok", "size_estimate": "20%", "tactic": "x",
                 "channel": "email", "expected_response_pct": 5},
                "not a dict",  # filtered
                {"name": "also ok", "size_estimate": "30%", "tactic": "y",
                 "channel": "sms", "expected_response_pct": 7},
            ],
            "top_segment": "ok",
            "expected_uplift_pct": 6,
            "confidence": 0.6,
            "reasoning": "x",
        })
        cj = _cj(llm)
        result = cj.personalize_with_llm(_CUSTOMERS)
        # 2 valid, 1 filtered
        assert len(result["llm"]["segments"]) == 2

    def test_non_numeric_uplift_is_normalization_error(self):
        llm = _FakeLLM(structured_data={
            "segments": [],
            "top_segment": "x",
            "expected_uplift_pct": "high",  # bad
            "confidence": 0.5,
            "reasoning": "x",
        })
        cj = _cj(llm)
        result = cj.personalize_with_llm(_CUSTOMERS)
        assert "error" in result["llm"]
        assert "normalization" in result["llm"]["error"]


# ── Prompt registered ────────────────────────────────────────


class TestPromptRegistered:
    def test_personalization_prompt_exists(self):
        from core.system.prompt_library import get_prompt
        p = get_prompt("customer.personalization_plan")
        assert p is not None
        assert p.role == "reasoner"
        assert "customer_count" in p.placeholders
        assert "heuristic_summary" in p.placeholders
