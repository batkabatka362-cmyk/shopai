"""Tests for AIOrchestratorStrategy Phase 4 wiring (W963-66)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import patch

from engines._ai_strategies import AIOrchestratorStrategy


@dataclass
class _BaseDecision:
    store_id: str
    priority: str = "growing"
    cluster_focus: list = None
    rationale: str = "det"
    signals: dict = None

    def __post_init__(self):
        if self.cluster_focus is None:
            self.cluster_focus = ["x"]
        if self.signals is None:
            self.signals = {}


class _FakeLLM:
    def __init__(self, response):
        self._resp = response
        self.available = True
        self.last_user_payload = None

    def chat_json(self, system, user):
        self.last_user_payload = user
        return self._resp


def _make_strategy(llm):
    s = AIOrchestratorStrategy(llm=llm)

    class _Base:
        def decide_priority(self, store_id, wm):
            return _BaseDecision(store_id=store_id)

    s._base = _Base()
    return s


# ── world_model.agi_phase4 propagates into prompt ─────────


class TestAgiPhase4InOrchestratorPrompt:
    def test_world_model_agi_phase4_used_when_present(self):
        llm = _FakeLLM(response={
            "priority": "growing", "rationale": "ok",
        })
        s = _make_strategy(llm)
        wm = {
            "stats": {},
            "agi_phase4": {
                "verdict": "earning",
                "gross_profit": 500.0,
                "history_trend_14d": "improving",
                "critical_anomaly_count": 0,
            },
        }
        with patch(
            "engines._ai_strategies._ai_enabled",
            return_value=True,
        ):
            s.decide_priority("s1", wm)
        payload = json.loads(llm.last_user_payload)
        assert payload["agi_phase4"]["verdict"] == (
            "earning"
        )
        assert payload["agi_phase4"]["gross_profit"] == (
            500.0
        )

    def test_no_agi_phase4_falls_to_helper(self):
        """When world-model doesn't carry the section, the
        orchestrator falls back to _agi_phase4_context()."""
        llm = _FakeLLM(response={
            "priority": "at_risk", "rationale": "x",
        })
        s = _make_strategy(llm)
        wm = {"stats": {}}  # no agi_phase4 key

        @dataclass
        class _FakeSummary:
            verdict: str = "no_data"
            fleet_gross_profit: float = 0.0
            fleet_attribution_pct: float = 0.0
            monthly_run_rate: float = 0.0
            trend_verdict: str = "no_data"

        with patch(
            "engines._ai_strategies._ai_enabled",
            return_value=True,
        ), patch(
            "engines.agi_earnings_summary.summarizer."
            "compute_summary",
            return_value=_FakeSummary(),
        ):
            s.decide_priority("s1", wm)
        payload = json.loads(llm.last_user_payload)
        assert "agi_phase4" in payload
        assert payload["agi_phase4"]["verdict"] == "no_data"

    def test_non_dict_agi_phase4_falls_to_helper(self):
        llm = _FakeLLM(response={
            "priority": "mature", "rationale": "x",
        })
        s = _make_strategy(llm)
        wm = {
            "stats": {},
            "agi_phase4": "not a dict",
        }
        with patch(
            "engines._ai_strategies._ai_enabled",
            return_value=True,
        ):
            s.decide_priority("s1", wm)
        payload = json.loads(llm.last_user_payload)
        # Helper produced a dict
        assert isinstance(payload["agi_phase4"], dict)

    def test_ai_disabled_skips_prompt(self):
        llm = _FakeLLM(response=None)
        s = _make_strategy(llm)
        with patch(
            "engines._ai_strategies._ai_enabled",
            return_value=False,
        ):
            decision = s.decide_priority(
                "s1", {"agi_phase4": {"verdict": "earning"}},
            )
        # No prompt -> no last_user_payload
        assert llm.last_user_payload is None
        # Falls back to deterministic baseline
        assert decision.priority == "growing"

    def test_llm_response_none_falls_back(self):
        llm = _FakeLLM(response=None)
        s = _make_strategy(llm)
        with patch(
            "engines._ai_strategies._ai_enabled",
            return_value=True,
        ):
            decision = s.decide_priority(
                "s1", {"agi_phase4": {"verdict": "no_data"}},
            )
        assert decision.priority == "growing"

    def test_invalid_priority_falls_back(self):
        llm = _FakeLLM(response={
            "priority": "bogus", "rationale": "x",
        })
        s = _make_strategy(llm)
        with patch(
            "engines._ai_strategies._ai_enabled",
            return_value=True,
        ):
            decision = s.decide_priority(
                "s1", {"agi_phase4": {"verdict": "no_data"}},
            )
        assert decision.priority == "growing"
