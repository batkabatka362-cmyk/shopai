"""Tests for engines.agi_arm_recommender — W963-80."""
from __future__ import annotations

from engines.agi_arm_recommender import (
    AgiArmRecommenderEngine,
)
from engines.agi_arm_recommender.recommender import (
    ArmReport,
    EngineRecommendation,
    _build_headline,
    _build_next_action,
    _maybe_override,
    _verdict_recipe,
    recommend,
    _CONSERVATION_ENGINES,
    _DESTRUCTIVE_ENGINES,
    _EXPLORATION_ENGINES,
    _KICKSTART_ENGINES,
    _RETENTION_ENGINES,
    _REVENUE_DRIVING,
    _SPEND_ENGINES,
)


# ── _verdict_recipe ───────────────────────────────────────


class TestVerdictRecipe:
    def test_no_data_kickstart(self):
        arm, disarm, rationale = _verdict_recipe(
            "no_data", "no_data",
        )
        assert arm == list(_KICKSTART_ENGINES)
        assert disarm == []
        assert "kick-start" in rationale

    def test_organic_only_revenue_driving(self):
        arm, disarm, _ = _verdict_recipe(
            "organic_only", "flat",
        )
        assert set(arm) == set(_REVENUE_DRIVING)
        assert disarm == []

    def test_attributed_loss_spend_disarm(self):
        arm, disarm, _ = _verdict_recipe(
            "attributed_loss", "flat",
        )
        assert set(arm) == set(_CONSERVATION_ENGINES)
        assert set(disarm) == set(_SPEND_ENGINES)

    def test_earning_improving_explore(self):
        arm, disarm, _ = _verdict_recipe(
            "earning", "improved",
        )
        assert set(arm) == set(_EXPLORATION_ENGINES)
        assert disarm == []

    def test_earning_regressed_retention(self):
        arm, disarm, _ = _verdict_recipe(
            "earning", "regressed",
        )
        assert set(arm) == set(_RETENTION_ENGINES)
        assert set(disarm) == set(_SPEND_ENGINES)

    def test_earning_flat_maintain(self):
        arm, disarm, _ = _verdict_recipe(
            "earning", "flat",
        )
        assert arm == []
        assert disarm == []


# ── _maybe_override ───────────────────────────────────────


class TestOverride:
    def test_no_override_when_clean(self):
        sig = {"critical_anomaly_count": 0}
        arm, dis, override = _maybe_override(
            sig, ["x"], ["y"],
        )
        assert override is None
        assert arm == ["x"]
        assert dis == ["y"]

    def test_critical_anomaly_disarms_destructive(self):
        sig = {"critical_anomaly_count": 2}
        arm, dis, override = _maybe_override(
            sig, ["x"], [],
        )
        assert override is not None
        assert "critical_anomaly" in override
        # Destructive engines added to disarm
        for eng in _DESTRUCTIVE_ENGINES:
            assert eng in dis

    def test_critical_loss_streak_full_spend_disarm(self):
        sig = {
            "streak_top": "loss_streak",
            "streak_severity": "critical",
        }
        arm, dis, override = _maybe_override(
            sig, [], [],
        )
        assert override is not None
        assert "critical_loss_streak" in override
        for eng in _SPEND_ENGINES:
            assert eng in dis

    def test_critical_no_data_streak_kickstart_only(self):
        sig = {
            "streak_top": "no_data_streak",
            "streak_severity": "critical",
        }
        arm, dis, override = _maybe_override(
            sig, ["original"], [],
        )
        assert override is not None
        # Arm list overwritten to kick-start
        assert set(arm) == set(_KICKSTART_ENGINES)

    def test_warn_streak_does_not_override(self):
        sig = {
            "streak_top": "loss_streak",
            "streak_severity": "warn",  # not critical
        }
        arm, dis, override = _maybe_override(
            sig, ["x"], [],
        )
        assert override is None

    def test_overrides_compose_when_both_fire(self):
        """W963-93 regression: pre-fix, loss_streak
        override returned early so destructive engines
        weren't disarmed even when critical_anomaly also
        fired. Now the disarm list contains BOTH spend
        + destructive."""
        sig = {
            "streak_top": "loss_streak",
            "streak_severity": "critical",
            "critical_anomaly_count": 2,
        }
        arm, dis, override = _maybe_override(
            sig, [], [],
        )
        assert override is not None
        # Override label mentions BOTH reasons
        assert "critical_loss_streak" in override
        assert "critical_anomaly" in override
        # Disarm list contains BOTH classes
        for eng in _SPEND_ENGINES:
            assert eng in dis, (
                f"{eng} (spend) missing"
            )
        for eng in _DESTRUCTIVE_ENGINES:
            assert eng in dis, (
                f"{eng} (destructive) missing"
            )

    def test_no_data_streak_still_short_circuits(self):
        """no_data_streak overwrites arm to kick-start
        list -- it's mutually exclusive with other
        overrides because it changes the SHAPE of the
        plan, not just augments disarm."""
        sig = {
            "streak_top": "no_data_streak",
            "streak_severity": "critical",
            "critical_anomaly_count": 2,
        }
        arm, dis, override = _maybe_override(
            sig, ["x"], [],
        )
        assert "no_data_streak" in override
        # arm overwritten to kick-start, anomaly disarm
        # NOT applied because no_data_streak short-
        # circuits.
        assert set(arm) == set(_KICKSTART_ENGINES)


# ── recommend() ────────────────────────────────────────────


class TestRecommend:
    def test_returns_arm_report(self):
        r = recommend(
            signals_override={"verdict": "no_data"},
        )
        assert isinstance(r, ArmReport)
        assert r.verdict == "no_data"
        # no_data -> kick-start
        assert len(r.arm_recommendations) == len(
            _KICKSTART_ENGINES,
        )

    def test_each_recommendation_has_rationale(self):
        r = recommend(
            signals_override={
                "verdict": "attributed_loss",
                "trajectory": "flat",
            },
        )
        for rec in (
            r.arm_recommendations
            + r.disarm_recommendations
        ):
            assert rec.rationale
            assert rec.engine
            assert rec.action in ("arm", "disarm")

    def test_override_marks_critical_priority(self):
        r = recommend(
            signals_override={
                "verdict": "earning",
                "critical_anomaly_count": 1,
            },
        )
        # Override path -> critical priority on
        # affected engines
        assert r.override_applied is not None
        # Destructive engines disarmed
        eng_names = {
            rec.engine for rec in r.disarm_recommendations
        }
        assert eng_names & set(_DESTRUCTIVE_ENGINES)
        for rec in r.disarm_recommendations:
            assert rec.priority == "critical"

    def test_no_override_normal_priority(self):
        r = recommend(
            signals_override={
                "verdict": "organic_only",
                "trajectory": "flat",
            },
        )
        for rec in r.arm_recommendations:
            assert rec.priority == "normal"

    def test_loss_streak_preserves_base_rationale_for_pre_existing(self):
        """W963-97 regression: when loss_streak critical
        fires under verdict=attributed_loss, the base recipe
        ALREADY disarms _SPEND_ENGINES. Override adds the
        same _SPEND_ENGINES (zero new). Pre-fix, every
        disarm engine got override label + critical priority
        even though they were already in the base recipe.
        Post-fix: pre-existing engines keep base_rationale +
        normal; only override-ADDED engines escalate."""
        r = recommend(
            signals_override={
                "verdict": "attributed_loss",
                "trajectory": "flat",
                "streak_top": "loss_streak",
                "streak_severity": "critical",
            },
        )
        assert r.override_applied is not None
        assert "critical_loss_streak" in r.override_applied
        # All arm engines are CONSERVATION (pre-existing in
        # base recipe). They should keep normal priority +
        # base_rationale, NOT the override label.
        for rec in r.arm_recommendations:
            assert rec.priority == "normal", (
                f"arm {rec.engine} priority should be normal "
                f"(pre-existing in base recipe), got "
                f"{rec.priority}"
            )
            assert "Attributed loss" in rec.rationale, (
                f"arm {rec.engine} rationale should be base "
                "recipe, not override label"
            )
        # Disarm engines are SPEND (pre-existing in base
        # recipe too -- override added nothing new). Same
        # check.
        for rec in r.disarm_recommendations:
            assert rec.priority == "normal", (
                f"disarm {rec.engine} priority should be "
                f"normal, got {rec.priority}"
            )

    def test_critical_anomaly_under_earning_escalates_only_destructive(self):
        """W963-97 regression: verdict=earning + trajectory=
        improved arms _EXPLORATION_ENGINES. Critical anomaly
        override adds _DESTRUCTIVE_ENGINES to disarm. Pre-fix
        the EXPLORATION arm engines got critical priority +
        anomaly label even though they pre-existed. Post-fix:
        EXPLORATION (pre-existing arms) stay normal; only
        DESTRUCTIVE (added disarms) escalate."""
        r = recommend(
            signals_override={
                "verdict": "earning",
                "trajectory": "improved",
                "critical_anomaly_count": 2,
            },
        )
        assert r.override_applied is not None
        assert "critical_anomaly" in r.override_applied
        # EXPLORATION arm engines pre-existed in base recipe
        for rec in r.arm_recommendations:
            assert rec.priority == "normal", (
                f"arm {rec.engine} should be normal (pre-"
                f"existing exploration), got {rec.priority}"
            )
            assert "compound" in rec.rationale.lower() or \
                   "exploring" in rec.rationale.lower(), (
                f"arm {rec.engine} should keep base "
                "exploration rationale"
            )
        # DESTRUCTIVE disarm engines added by override
        for rec in r.disarm_recommendations:
            assert rec.priority == "critical", (
                f"disarm {rec.engine} should be critical "
                "(added by anomaly override)"
            )
            assert "anomaly" in rec.rationale.lower()


# ── headline / next_action ────────────────────────────────


class TestHeadline:
    def test_no_changes(self):
        r = ArmReport(
            verdict="earning",
            trajectory="flat",
            streak_severity="info",
            critical_anomaly_count=0,
        )
        h = _build_headline(r)
        assert "No changes" in h
        assert "earning" in h

    def test_with_changes(self):
        r = ArmReport(
            verdict="organic_only",
            trajectory="flat",
            streak_severity="info",
            critical_anomaly_count=0,
            arm_recommendations=[
                EngineRecommendation(
                    engine="loyalty",
                    action="arm",
                    rationale="x",
                ),
            ],
            disarm_recommendations=[],
        )
        h = _build_headline(r)
        assert "1 ARM" in h
        assert "0 DISARM" in h


class TestNextAction:
    def test_no_action_needed(self):
        r = ArmReport(
            verdict="earning",
            trajectory="flat",
            streak_severity="info",
            critical_anomaly_count=0,
        )
        n = _build_next_action(r)
        assert "No action needed" in n
        assert "cycle run" in n

    def test_arm_listed_in_next_action(self):
        r = ArmReport(
            verdict="organic_only",
            trajectory="flat",
            streak_severity="info",
            critical_anomaly_count=0,
            arm_recommendations=[
                EngineRecommendation(
                    engine="loyalty",
                    action="arm",
                    rationale="x",
                ),
                EngineRecommendation(
                    engine="email_marketing",
                    action="arm",
                    rationale="x",
                ),
            ],
        )
        n = _build_next_action(r)
        assert "loyalty" in n
        assert "email_marketing" in n

    def test_truncates_after_5(self):
        recs = [
            EngineRecommendation(
                engine=f"e_{i}",
                action="arm", rationale="x",
            )
            for i in range(8)
        ]
        r = ArmReport(
            verdict="x", trajectory="x",
            streak_severity="info",
            critical_anomaly_count=0,
            arm_recommendations=recs,
        )
        n = _build_next_action(r)
        assert "3 more" in n


# ── Pattern Q envelope ────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = AgiArmRecommenderEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = AgiArmRecommenderEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = AgiArmRecommenderEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = AgiArmRecommenderEngine().run({
            "status": "fail", "error": "x",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = AgiArmRecommenderEngine().run({})
        assert (
            r["meta"]["engine"] == "agi_arm_recommender"
        )

    def test_data_has_recommendations(self):
        r = AgiArmRecommenderEngine().run({})
        assert "arm_recommendations" in r["data"]
        assert "disarm_recommendations" in r["data"]
