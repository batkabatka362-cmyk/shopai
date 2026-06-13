"""Tests for engines.warmup_plan — W963-17."""
from __future__ import annotations

from engines.warmup_plan import WarmupPlanEngine
from engines.warmup_plan.schedule import (
    WarmupDay,
    generate_plan,
    get_day,
    phase_summary,
)


# ── Schedule generator ────────────────────────────────────


class TestGeneratePlan:
    def test_returns_30_days(self):
        plan = generate_plan()
        assert len(plan) == 30
        assert plan[0].day == 1
        assert plan[-1].day == 30

    def test_days_are_warmupday_instances(self):
        plan = generate_plan()
        for d in plan:
            assert isinstance(d, WarmupDay)

    def test_phase_boundaries(self):
        plan = generate_plan()
        # Day 3 = foundation, day 4 = ignition, etc.
        assert plan[2].phase == "foundation"
        assert plan[3].phase == "ignition"
        assert plan[10].phase == "feedback"
        assert plan[20].phase == "compound"

    def test_every_day_has_intent_and_actions(self):
        plan = generate_plan(niche="beauty")
        for d in plan:
            assert d.intent
            assert d.measurement
            assert isinstance(d.actions, list)


class TestGetDay:
    def test_returns_none_for_invalid_day(self):
        assert get_day(0) is None
        assert get_day(31) is None
        assert get_day(-5) is None

    def test_in_range(self):
        d = get_day(15, niche="beauty")
        assert d is not None
        assert d.day == 15
        assert d.phase == "feedback"

    def test_day_1_has_launch_action(self):
        d = get_day(1)
        joined = " ".join(d.actions)
        assert "earn-bootstrap" in joined or "launch" in joined

    def test_day_30_is_retrospective(self):
        d = get_day(30)
        assert d.day == 30
        assert d.phase == "compound"
        assert "earnings" in " ".join(d.actions)


class TestNicheTuning:
    def test_social_heavy_niche_has_three_social_actions(self):
        # Day 5 = "First social pulse"
        d_beauty = get_day(5, niche="beauty")
        d_general = get_day(5, niche="general")
        assert len(d_beauty.actions) >= len(d_general.actions)

    def test_niche_propagated_into_day_2_blog(self):
        d = get_day(2, niche="tech")
        joined = " ".join(d.actions)
        assert "tech" in joined


class TestPhaseSummary:
    def test_returns_4_phases(self):
        ps = phase_summary()
        assert set(ps.keys()) == {
            "foundation", "ignition", "feedback", "compound",
        }

    def test_independent_dict_per_call(self):
        a = phase_summary()
        a["foundation"] = "MUTATED"
        b = phase_summary()
        assert b["foundation"] != "MUTATED"


# ── Engine Pattern Q envelope ─────────────────────────────


class TestEngineEnvelope:
    def test_empty_input_returns_full_plan(self):
        result = WarmupPlanEngine().run({})
        assert result["status"] == "success"
        assert result["data"]["action"] == "full"
        assert result["data"]["day_count"] == 30

    def test_none_input_success(self):
        result = WarmupPlanEngine().run(None)
        assert result["status"] == "success"

    def test_non_dict_input_error(self):
        result = WarmupPlanEngine().run("nope")
        assert result["status"] == "error"

    def test_fail_upstream(self):
        result = WarmupPlanEngine().run({
            "status": "fail", "error": "broken",
        })
        assert result["status"] == "error"

    def test_unknown_action(self):
        result = WarmupPlanEngine().run({
            "data": {"action": "skip"},
        })
        assert result["status"] == "error"

    def test_non_string_action_does_not_crash(self):
        # Regression: BUG-7
        for bad in (42, 3.14, [], {}, True):
            result = WarmupPlanEngine().run({
                "data": {"action": bad},
            })
            assert result["status"] in {"success", "error"}


class TestEngineActions:
    def test_full_returns_30_days(self):
        result = WarmupPlanEngine().run({
            "data": {"action": "full", "niche": "beauty"},
        })
        assert result["data"]["day_count"] == 30
        assert result["data"]["niche"] == "beauty"

    def test_day_returns_one_day(self):
        result = WarmupPlanEngine().run({
            "data": {"action": "day", "day": 7},
        })
        assert result["status"] == "success"
        assert result["data"]["day"]["day"] == 7

    def test_day_out_of_range_error(self):
        result = WarmupPlanEngine().run({
            "data": {"action": "day", "day": 42},
        })
        assert result["status"] == "error"

    def test_day_non_int_error(self):
        result = WarmupPlanEngine().run({
            "data": {"action": "day", "day": "abc"},
        })
        assert result["status"] == "error"

    def test_phases_returns_summary(self):
        result = WarmupPlanEngine().run({
            "data": {"action": "phases"},
        })
        assert result["status"] == "success"
        assert "phase_summary" in result["data"]

    def test_envelope_carries_engine_name(self):
        result = WarmupPlanEngine().run({})
        assert result["meta"]["engine"] == "warmup_plan"


class TestNextActions:
    def test_day_next_points_at_next_day(self):
        result = WarmupPlanEngine().run({
            "data": {"action": "day", "day": 14},
        })
        nxt = result["data"]["next_action"]
        assert "day 15" in nxt

    def test_day_30_next_is_schedule(self):
        result = WarmupPlanEngine().run({
            "data": {"action": "day", "day": 30},
        })
        nxt = result["data"]["next_action"]
        assert "cycle schedule" in nxt
