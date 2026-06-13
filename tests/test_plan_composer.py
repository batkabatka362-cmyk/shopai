"""Tests for engines.plan_composer — W963-31."""
from __future__ import annotations

from unittest.mock import patch

from engines.plan_composer import PlanComposerEngine
from engines.plan_composer.composer import (
    Plan,
    PlanStep,
    _expand_drill,
    _match_template,
    _resolve_niche,
    available_templates,
    compose_plan,
)


# ── _match_template ───────────────────────────────────────


class TestMatchTemplate:
    def test_exact_key_match(self):
        assert _match_template("cold_start") == "cold_start"

    def test_alias_match(self):
        assert _match_template("first sale") == "cold_start"
        assert (
            _match_template("convert better")
            == "increase_conversion"
        )
        assert (
            _match_template("get traffic")
            == "increase_traffic"
        )

    def test_token_overlap_fallback(self):
        # "boost the conversion rate" -> alias "boost conversion"
        # ("boost"+"conversion" tokens) matches.
        assert (
            _match_template("boost conversion rate")
            == "increase_conversion"
        )

    def test_empty_returns_none(self):
        assert _match_template("") is None
        assert _match_template("   ") is None

    def test_no_match_returns_none(self):
        # "fly to the moon" — no token overlap
        assert _match_template("fly to the moon") is None


# ── _expand_drill ─────────────────────────────────────────


class TestExpandDrill:
    def test_substitutes_niche(self):
        out = _expand_drill(
            "shopai cmd --niche {niche}",
            niche="beauty", store_id="x",
        )
        assert "beauty" in out

    def test_substitutes_store_id(self):
        out = _expand_drill(
            "shopai cmd {store_id}",
            niche="beauty", store_id="X",
        )
        assert "X" in out

    def test_store_id_defaults_to_main(self):
        out = _expand_drill(
            "shopai cmd {store_id}",
            niche="beauty", store_id="",
        )
        assert "main" in out

    def test_no_placeholder_returns_unchanged(self):
        out = _expand_drill(
            "shopai cmd", niche="beauty", store_id="X",
        )
        assert out == "shopai cmd"

    def test_unknown_placeholder_silently_keeps(self):
        out = _expand_drill(
            "shopai cmd --x {unknown}",
            niche="beauty", store_id="X",
        )
        # KeyError caught, returns drill unchanged
        assert "{unknown}" in out


# ── _resolve_niche ────────────────────────────────────────


class TestResolveNiche:
    def test_no_store_returns_general(self):
        assert _resolve_niche("") == "general"

    def test_lookup_failure_returns_general(self):
        with patch(
            "data_pipeline.store.store_manager.StoreManager",
            side_effect=RuntimeError("nope"),
        ):
            assert _resolve_niche("X") == "general"


# ── compose_plan ──────────────────────────────────────────


class TestComposePlan:
    def test_cold_start_template(self):
        plan = compose_plan(goal="cold_start", store_id="main")
        assert plan.template_matched == "cold_start"
        assert plan.confidence == 0.9
        assert len(plan.steps) == 5

    def test_increase_conversion_template(self):
        plan = compose_plan(
            goal="convert better", store_id="main",
        )
        assert plan.template_matched == "increase_conversion"
        assert len(plan.steps) >= 3

    def test_increase_traffic_template(self):
        plan = compose_plan(goal="get traffic", store_id="X")
        assert plan.template_matched == "increase_traffic"

    def test_retain_customers_template(self):
        plan = compose_plan(
            goal="retention", store_id="X",
        )
        assert plan.template_matched == "retain_customers"

    def test_diagnose_template(self):
        plan = compose_plan(goal="diagnose", store_id="main")
        assert plan.template_matched == "diagnose"

    def test_max_steps_caps_template(self):
        plan = compose_plan(
            goal="cold_start", store_id="X", max_steps=2,
        )
        assert len(plan.steps) == 2

    def test_max_steps_floor(self):
        plan = compose_plan(
            goal="cold_start", store_id="X", max_steps=0,
        )
        # max(1, 0) = 1, so floor is 1
        assert len(plan.steps) == 1

    def test_steps_have_required_fields(self):
        plan = compose_plan(goal="cold_start", store_id="X")
        for s in plan.steps:
            assert s.action
            assert s.engine
            assert s.drill_command
            assert s.reasoning
            assert s.impact in {"high", "medium", "low"}

    def test_drill_command_niche_substituted(self):
        # niche="beauty" comes from a real lookup or default
        with patch(
            "engines.plan_composer.composer._resolve_niche",
            return_value="beauty",
        ):
            plan = compose_plan(
                goal="cold_start", store_id="X",
            )
        # first step uses {niche}
        assert "beauty" in plan.steps[0].drill_command

    def test_custom_compose_when_no_template_match(self):
        # No-token-overlap goal falls into custom compose
        with patch(
            "engines.capability_browser.searcher."
            "search_capabilities",
        ) as mock_search:
            mock_report = type("R", (), {"hits": []})()
            mock_search.return_value = mock_report
            plan = compose_plan(
                goal="fly to the moon",
                store_id="X",
            )
        assert plan.template_matched == ""
        # No steps because hits empty; notes explain
        assert len(plan.notes) >= 1

    def test_custom_compose_with_hits(self):
        from engines.capability_browser.searcher import (
            CapabilityHit,
        )
        hits = [
            CapabilityHit(
                name="loyalty",
                kind="engine",
                description="Reward repeat customers",
                cli_commands=["loyalty status"],
                score=4.0,
            ),
        ]
        mock_report = type("R", (), {"hits": hits})()
        with patch(
            "engines.capability_browser.searcher."
            "search_capabilities",
            return_value=mock_report,
        ):
            plan = compose_plan(
                goal="custom goal", store_id="X",
            )
        assert len(plan.steps) >= 1
        assert plan.steps[0].engine == "loyalty"


# ── available_templates ───────────────────────────────────


class TestAvailableTemplates:
    def test_returns_sorted_list(self):
        out = available_templates()
        assert isinstance(out, list)
        assert out == sorted(out)
        assert "cold_start" in out


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = PlanComposerEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = PlanComposerEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = PlanComposerEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = PlanComposerEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = PlanComposerEngine().run({})
        assert r["meta"]["engine"] == "plan_composer"


class TestEngineActions:
    def test_empty_goal_returns_no_steps(self):
        r = PlanComposerEngine().run({})
        assert r["data"]["step_count"] == 0
        assert "Pass a goal phrase" in r["data"]["next_action"]

    def test_goal_threaded(self):
        r = PlanComposerEngine().run({
            "data": {"goal": "cold_start"},
        })
        assert r["data"]["goal"] == "cold_start"
        assert r["data"]["step_count"] == 5

    def test_invalid_max_steps_falls_back(self):
        r = PlanComposerEngine().run({
            "data": {"goal": "cold_start", "max_steps": "x"},
        })
        # default 10, but template has 5 → 5
        assert r["data"]["step_count"] == 5

    def test_available_templates_included(self):
        r = PlanComposerEngine().run({})
        tmpls = r["data"]["available_templates"]
        assert "cold_start" in tmpls
        assert "diagnose" in tmpls
