"""Tests for engines.roas_guardrails — campaign metrics → kill/scale decisions.

Test structure:
  - TestEntryPoint          — engine name, wrapper, envelope
  - TestInputValidation     — bad campaigns, upstream failure
  - TestCopyOnEntry         — deepcopy isolation
  - TestKill                — ROAS < 1.0 → kill
  - TestReduce              — ROAS 1.0–1.5 → reduce 30%
  - TestHold                — ROAS 1.5–2.0 → hold
  - TestScale               — ROAS 2.0–3.0 → scale +20%
  - TestScaleAggressive     — ROAS ≥ 3.0 → scale +50%
  - TestLearningPhase       — spend < $50 → learning (protect downside)
  - TestCPACeiling          — CPA override even when ROAS ok
  - TestPausedCampaign      — already-paused logic
  - TestCustomThresholds    — non-default threshold overrides
  - TestBudgetCaps          — max_daily_budget guard
  - TestSummary             — summary rollup counts
  - TestMultiCampaign       — batch of mixed campaigns
  - TestEndToEnd            — full happy path
"""
from __future__ import annotations

import copy
from typing import Any

import pytest

from engines.roas_guardrails import ENGINE_NAME, RoasGuardrailsEngine, run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _campaign(
    campaign_id: str = "c_001",
    spend: float = 100.0,
    revenue: float = 250.0,
    purchases: int = 10,
    daily_budget: float = 20.0,
    **overrides: Any,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "campaign_id": campaign_id,
        "campaign_name": f"Campaign {campaign_id}",
        "spend": spend,
        "revenue": revenue,
        "purchases": purchases,
        "daily_budget": daily_budget,
        "status": "ACTIVE",
    }
    base.update(overrides)
    return base


def _call(campaigns: list[dict[str, Any]] | None = None, **kwargs: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "campaigns": campaigns or [_campaign()],
    }
    payload.update(kwargs)
    return run(payload)


# ===================================================================
# TestEntryPoint
# ===================================================================


class TestEntryPoint:
    def test_engine_name(self):
        assert ENGINE_NAME == "roas_guardrails"

    def test_class_wrapper(self):
        eng = RoasGuardrailsEngine()
        assert eng.ENGINE_NAME == "roas_guardrails"
        assert eng.engine_name == "roas_guardrails"

    def test_class_run(self):
        eng = RoasGuardrailsEngine()
        r = eng.run({"campaigns": [_campaign()]})
        assert r["status"] == "success"

    def test_meta_fields(self):
        r = _call()
        assert r["meta"]["engine"] == "roas_guardrails"
        assert "timestamp" in r["meta"]
        assert "elapsed_seconds" in r["meta"]
        assert r["error"] is None

    def test_data_has_decisions(self):
        r = _call()
        assert "decisions" in r["data"]
        assert "summary" in r["data"]
        assert "thresholds_used" in r["data"]


# ===================================================================
# TestInputValidation
# ===================================================================


class TestInputValidation:
    def test_none_input(self):
        r = run(None)
        assert r["status"] == "error"
        assert "campaigns" in r["error"].lower()

    def test_empty_dict(self):
        r = run({})
        assert r["status"] == "error"

    def test_campaigns_not_list(self):
        r = run({"campaigns": "bad"})
        assert r["status"] == "error"

    def test_campaigns_empty_list(self):
        r = run({"campaigns": []})
        assert r["status"] == "error"

    def test_upstream_failure(self):
        r = run({"status": "fail", "error": "upstream broke"})
        assert r["status"] == "error"
        assert "upstream" in r["error"].lower()

    def test_upstream_failure_default_msg(self):
        r = run({"status": "fail"})
        assert r["status"] == "error"


# ===================================================================
# TestCopyOnEntry
# ===================================================================


class TestCopyOnEntry:
    def test_input_not_mutated(self):
        original = {"campaigns": [_campaign()]}
        snapshot = copy.deepcopy(original)
        run(original)
        assert original == snapshot


# ===================================================================
# TestKill — ROAS < 1.0
# ===================================================================


class TestKill:
    def test_roas_below_1(self):
        c = _campaign(spend=100, revenue=50)  # ROAS = 0.5
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert d["action"] == "kill"
        assert d["roas"] == 0.5

    def test_roas_exactly_0(self):
        c = _campaign(spend=100, revenue=0)
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert d["action"] == "kill"

    def test_kill_reason_mentions_roas(self):
        c = _campaign(spend=100, revenue=80)
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert "roas" in d["reason"].lower() or "ROAS" in d["reason"]

    def test_kill_no_new_budget(self):
        c = _campaign(spend=100, revenue=50)
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert "new_daily_budget" not in d


# ===================================================================
# TestReduce — ROAS 1.0–1.5
# ===================================================================


class TestReduce:
    def test_roas_1_2(self):
        c = _campaign(spend=100, revenue=120)  # ROAS = 1.2
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert d["action"] == "reduce"

    def test_reduce_30_pct(self):
        c = _campaign(spend=100, revenue=120, daily_budget=20.0)
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert d["new_daily_budget"] == 14.0  # 20 * 0.70

    def test_reduce_floor_1_dollar(self):
        c = _campaign(spend=100, revenue=110, daily_budget=1.0)
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert d["new_daily_budget"] >= 1.0

    def test_roas_exactly_1(self):
        c = _campaign(spend=100, revenue=100)  # ROAS = 1.0
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert d["action"] == "reduce"


# ===================================================================
# TestHold — ROAS 1.5–2.0
# ===================================================================


class TestHold:
    def test_roas_1_7(self):
        c = _campaign(spend=100, revenue=170)
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert d["action"] == "hold"

    def test_roas_1_5(self):
        c = _campaign(spend=100, revenue=150)
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert d["action"] == "hold"

    def test_hold_no_budget_change(self):
        c = _campaign(spend=100, revenue=170)
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert "new_daily_budget" not in d


# ===================================================================
# TestScale — ROAS 2.0–3.0
# ===================================================================


class TestScale:
    def test_roas_2_5(self):
        c = _campaign(spend=100, revenue=250)
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert d["action"] == "scale"

    def test_scale_20_pct(self):
        c = _campaign(spend=100, revenue=250, daily_budget=20.0)
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert d["new_daily_budget"] == 24.0  # 20 * 1.20

    def test_roas_2_0(self):
        c = _campaign(spend=100, revenue=200)
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert d["action"] == "scale"


# ===================================================================
# TestScaleAggressive — ROAS ≥ 3.0
# ===================================================================


class TestScaleAggressive:
    def test_roas_4_0(self):
        c = _campaign(spend=100, revenue=400)
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert d["action"] == "scale_aggressive"

    def test_scale_50_pct(self):
        c = _campaign(spend=100, revenue=400, daily_budget=20.0)
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert d["new_daily_budget"] == 30.0  # 20 * 1.50

    def test_roas_exactly_3(self):
        c = _campaign(spend=100, revenue=300)
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert d["action"] == "scale_aggressive"


# ===================================================================
# TestLearningPhase — spend < $50
# ===================================================================


class TestLearningPhase:
    def test_low_spend_learning(self):
        c = _campaign(spend=30, revenue=20, daily_budget=10)  # ROAS < 1 but in learning
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert d["action"] == "learning"
        assert d["in_learning"] is True

    def test_learning_protects_from_kill(self):
        c = _campaign(spend=10, revenue=2)  # terrible ROAS but only $10 spent
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert d["action"] == "learning"
        assert d["action"] != "kill"

    def test_learning_allows_scale(self):
        c = _campaign(spend=30, revenue=90, daily_budget=15)  # ROAS 3.0 during learning
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert d["action"] == "scale"

    def test_custom_spend_floor(self):
        c = _campaign(spend=80, revenue=40)  # ROAS 0.5, but under custom floor
        r = _call([c], thresholds={"spend_floor_usd": 100})
        d = r["data"]["decisions"][0]
        assert d["action"] == "learning"

    def test_zero_spend_floor(self):
        c = _campaign(spend=5, revenue=2)  # ROAS 0.4
        r = _call([c], thresholds={"spend_floor_usd": 0})
        d = r["data"]["decisions"][0]
        assert d["action"] == "kill"

    def test_no_spend_no_budget(self):
        c = _campaign(spend=0, revenue=0, daily_budget=0)
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert d["action"] == "learning"


# ===================================================================
# TestCPACeiling
# ===================================================================


class TestCPACeiling:
    def test_cpa_override_reduces(self):
        # ROAS = 2.5 (would normally scale), but CPA = $10 > ceiling $8
        c = _campaign(spend=100, revenue=250, purchases=10, daily_budget=20)
        r = _call([c], thresholds={"cpa_ceiling_usd": 8.0})
        d = r["data"]["decisions"][0]
        assert d["action"] == "reduce"
        assert "cpa" in d["reason"].lower()

    def test_cpa_ok_no_override(self):
        c = _campaign(spend=100, revenue=250, purchases=10, daily_budget=20)
        r = _call([c], thresholds={"cpa_ceiling_usd": 15.0})
        d = r["data"]["decisions"][0]
        assert d["action"] == "scale"

    def test_cpa_ceiling_not_during_learning(self):
        c = _campaign(spend=20, revenue=50, purchases=2, daily_budget=10)
        r = _call([c], thresholds={"cpa_ceiling_usd": 5.0})
        d = r["data"]["decisions"][0]
        # CPA = $10 > $5 ceiling, but in learning — should scale (ROAS 2.5)
        assert d["action"] == "scale"


# ===================================================================
# TestPausedCampaign
# ===================================================================


class TestPausedCampaign:
    def test_paused_hold(self):
        c = _campaign(spend=100, revenue=120, status="PAUSED")
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert d["action"] == "hold"

    def test_paused_recommend_resume(self):
        c = _campaign(spend=100, revenue=250, status="PAUSED")
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert d["action"] == "scale"
        assert "resume" in d["reason"].lower()


# ===================================================================
# TestCustomThresholds
# ===================================================================


class TestCustomThresholds:
    def test_stricter_kill(self):
        c = _campaign(spend=100, revenue=140)  # ROAS 1.4 — normally reduce
        r = _call([c], thresholds={"kill": 1.5})
        d = r["data"]["decisions"][0]
        assert d["action"] == "kill"

    def test_lower_hold_threshold(self):
        c = _campaign(spend=100, revenue=160)  # ROAS 1.6 — normally hold, but hold=1.5 makes it scale band
        r = _call([c], thresholds={"hold": 1.5})
        d = r["data"]["decisions"][0]
        assert d["action"] == "scale"

    def test_custom_reduce_pct(self):
        c = _campaign(spend=100, revenue=120, daily_budget=20)
        r = _call([c], thresholds={"reduce_pct": 0.50})
        d = r["data"]["decisions"][0]
        assert d["new_daily_budget"] == 10.0

    def test_custom_scale_pct(self):
        c = _campaign(spend=100, revenue=250, daily_budget=20)
        r = _call([c], thresholds={"scale_pct": 0.30})
        d = r["data"]["decisions"][0]
        assert d["new_daily_budget"] == 26.0


# ===================================================================
# TestBudgetCaps
# ===================================================================


class TestBudgetCaps:
    def test_scale_capped_at_max(self):
        c = _campaign(spend=500, revenue=2000, daily_budget=90)
        r = _call([c], thresholds={"max_daily_budget_usd": 100.0})
        d = r["data"]["decisions"][0]
        assert d["new_daily_budget"] <= 100.0

    def test_aggressive_scale_capped(self):
        c = _campaign(spend=500, revenue=2000, daily_budget=80)
        r = _call([c], thresholds={"max_daily_budget_usd": 100.0})
        d = r["data"]["decisions"][0]
        # 80 * 1.5 = 120 → capped at 100
        assert d["new_daily_budget"] == 100.0


# ===================================================================
# TestSummary
# ===================================================================


class TestSummary:
    def test_summary_counts(self):
        campaigns = [
            _campaign("c1", spend=100, revenue=50),    # kill
            _campaign("c2", spend=100, revenue=120),   # reduce
            _campaign("c3", spend=100, revenue=170),   # hold
            _campaign("c4", spend=100, revenue=250),   # scale
            _campaign("c5", spend=100, revenue=400),   # scale_aggressive
            _campaign("c6", spend=20, revenue=10),     # learning
        ]
        r = _call(campaigns)
        s = r["data"]["summary"]
        assert s["total_campaigns"] == 6
        assert s["kill"] == 1
        assert s["reduce"] == 1
        assert s["hold"] == 1
        assert s["scale"] == 1
        assert s["scale_aggressive"] == 1
        assert s["learning"] == 1


# ===================================================================
# TestMultiCampaign
# ===================================================================


class TestMultiCampaign:
    def test_decisions_per_campaign(self):
        campaigns = [
            _campaign("c1", spend=100, revenue=50),
            _campaign("c2", spend=100, revenue=250),
        ]
        r = _call(campaigns)
        decisions = r["data"]["decisions"]
        assert len(decisions) == 2
        assert decisions[0]["campaign_id"] == "c1"
        assert decisions[0]["action"] == "kill"
        assert decisions[1]["campaign_id"] == "c2"
        assert decisions[1]["action"] == "scale"

    def test_non_dict_campaigns_skipped(self):
        campaigns = [_campaign(), "not a dict", None, 42]
        r = _call(campaigns)
        assert len(r["data"]["decisions"]) == 1


# ===================================================================
# TestDecisionFields
# ===================================================================


class TestDecisionFields:
    def test_all_fields_present(self):
        r = _call()
        d = r["data"]["decisions"][0]
        assert "campaign_id" in d
        assert "campaign_name" in d
        assert "action" in d
        assert "reason" in d
        assert "roas" in d
        assert "cpa" in d
        assert "spend" in d
        assert "revenue" in d
        assert "purchases" in d
        assert "in_learning" in d

    def test_roas_calculation(self):
        c = _campaign(spend=200, revenue=500)
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert d["roas"] == 2.5

    def test_cpa_calculation(self):
        c = _campaign(spend=100, revenue=250, purchases=10)
        r = _call([c])
        d = r["data"]["decisions"][0]
        assert d["cpa"] == 10.0


# ===================================================================
# TestThresholdsUsed
# ===================================================================


class TestThresholdsUsed:
    def test_default_thresholds_echoed(self):
        r = _call()
        t = r["data"]["thresholds_used"]
        assert t["kill"] == 1.0
        assert t["reduce"] == 1.5
        assert t["hold"] == 2.0
        assert t["scale"] == 3.0
        assert t["spend_floor_usd"] == 50.0
        assert t["max_daily_budget_usd"] == 100.0

    def test_custom_thresholds_echoed(self):
        r = _call(thresholds={"kill": 0.8, "spend_floor_usd": 30})
        t = r["data"]["thresholds_used"]
        assert t["kill"] == 0.8
        assert t["spend_floor_usd"] == 30.0


# ===================================================================
# TestEndToEnd
# ===================================================================


class TestEndToEnd:
    def test_full_flow(self):
        campaigns = [
            _campaign("winner", spend=200, revenue=600, purchases=20, daily_budget=25),
            _campaign("loser", spend=150, revenue=60, purchases=3, daily_budget=15),
            _campaign("new", spend=30, revenue=10, purchases=1, daily_budget=10),
        ]
        r = _call(campaigns)
        assert r["status"] == "success"

        decisions = r["data"]["decisions"]
        assert len(decisions) == 3

        winner = decisions[0]
        assert winner["action"] == "scale_aggressive"
        assert winner["roas"] == 3.0
        assert winner["new_daily_budget"] > 25

        loser = decisions[1]
        assert loser["action"] == "kill"
        assert loser["roas"] == 0.4

        new = decisions[2]
        assert new["action"] == "learning"
