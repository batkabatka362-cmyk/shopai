"""Tests for engines.agi_morning_brief — W963-54."""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import patch

from engines.agi_morning_brief import AgiMorningBriefEngine
from engines.agi_morning_brief.briefer import (
    MorningBrief,
    _build_headline,
    _build_next_action,
    build_morning_brief,
)


# ── _build_headline ───────────────────────────────────────


class TestHeadline:
    def test_no_data(self):
        b = MorningBrief(store_id="", verdict="no_data")
        assert "IDLE" in _build_headline(b)

    def test_attributed_loss(self):
        b = MorningBrief(
            store_id="",
            verdict="attributed_loss",
            gross_profit=-100.0,
            attribution_pct=50.0,
        )
        h = _build_headline(b)
        assert "BLEEDING" in h
        # W963-93: sign-prefix-before-$ rendering.
        assert "-$100" in h
        assert "$-100" not in h

    def test_organic_only(self):
        b = MorningBrief(
            store_id="",
            verdict="organic_only",
            gross_profit=200.0,
        )
        h = _build_headline(b)
        assert "EARNING" in h
        assert "0% AGI" in h

    def test_earning_with_improving_trend(self):
        b = MorningBrief(
            store_id="",
            verdict="earning",
            gross_profit=300.0,
            attribution_pct=75.0,
            monthly_run_rate=1200.0,
            history_trend_verdict="improving",
        )
        h = _build_headline(b)
        assert "EARNING" in h
        assert "UP" in h
        assert "1200" in h

    def test_earning_with_declining_trend(self):
        b = MorningBrief(
            store_id="",
            verdict="earning",
            history_trend_verdict="declining",
            gross_profit=10.0,
            monthly_run_rate=40.0,
        )
        h = _build_headline(b)
        assert "DOWN" in h

    def test_earning_flat_no_arrow(self):
        b = MorningBrief(
            store_id="",
            verdict="earning",
            history_trend_verdict="flat",
            gross_profit=10.0,
            monthly_run_rate=40.0,
        )
        h = _build_headline(b)
        assert "EARNING" in h
        assert "UP" not in h
        assert "DOWN" not in h


# ── _build_next_action ────────────────────────────────────


class TestNextAction:
    def test_empty_no_action(self):
        b = MorningBrief(store_id="")
        assert _build_next_action(b) == (
            "No next-action proposed."
        )

    def test_no_critique_for_top(self):
        b = MorningBrief(
            store_id="",
            proposed=[{
                "rank": 1,
                "action": "do x",
                "cli_command": "shopai x",
            }],
        )
        out = _build_next_action(b)
        assert "do x" in out
        assert "shopai x" in out
        assert "[WARN]" not in out
        assert "[CRITICAL]" not in out

    def test_critical_critique_tagged(self):
        b = MorningBrief(
            store_id="",
            proposed=[{
                "rank": 1,
                "action": "do x",
                "cli_command": "shopai x",
            }],
            critiques=[{
                "rank": 1,
                "severity": "critical",
            }],
        )
        out = _build_next_action(b)
        assert "CRITICAL" in out

    def test_warn_critique_tagged(self):
        b = MorningBrief(
            store_id="",
            proposed=[{
                "rank": 1,
                "action": "y",
                "cli_command": "shopai y",
            }],
            critiques=[{
                "rank": 1, "severity": "warn",
            }],
        )
        out = _build_next_action(b)
        assert "WARN" in out

    def test_critical_anomaly_escalates_above_plan(self):
        b = MorningBrief(
            store_id="",
            proposed=[{
                "rank": 1, "action": "y",
                "cli_command": "shopai y",
            }],
            anomalies=[{
                "type": "VERDICT_FLIP",
                "severity": "critical",
            }],
            anomaly_critical_count=1,
        )
        out = _build_next_action(b)
        assert "CRITICAL anomaly" in out
        assert "VERDICT_FLIP" in out

    def test_brief_has_diff_fields(self):
        b = MorningBrief(store_id="")
        # Defaults
        assert b.diff_direction == "no_data"
        assert b.diff_headline == ""
        assert b.diff_gross_profit_delta == 0.0

    def test_brief_has_attention_fields(self):
        b = MorningBrief(store_id="")
        assert b.attention_needed is False
        assert b.attention_top_streak == ""
        assert b.attention_top_count == 0
        assert b.attention_top_severity == "info"

    def test_critical_streak_escalates_above_anomaly(self):
        b = MorningBrief(
            store_id="",
            proposed=[{
                "rank": 1, "action": "y",
                "cli_command": "shopai y",
            }],
            anomalies=[{
                "type": "VERDICT_FLIP",
                "severity": "critical",
            }],
            anomaly_critical_count=1,
            attention_needed=True,
            attention_top_streak="loss_streak",
            attention_top_count=7,
            attention_top_severity="critical",
        )
        out = _build_next_action(b)
        # Critical streak ladder beats critical anomaly
        assert "CRITICAL streak" in out
        assert "loss_streak" in out
        assert "7 cycles" in out

    def test_warn_streak_falls_back_to_anomaly(self):
        b = MorningBrief(
            store_id="",
            proposed=[{
                "rank": 1, "action": "y",
                "cli_command": "shopai y",
            }],
            anomalies=[{
                "type": "VERDICT_FLIP",
                "severity": "critical",
            }],
            anomaly_critical_count=1,
            attention_needed=True,
            attention_top_severity="warn",
        )
        out = _build_next_action(b)
        # warn streak doesn't escalate; anomaly does
        assert "CRITICAL anomaly" in out

    def test_warn_anomaly_does_not_escalate(self):
        b = MorningBrief(
            store_id="",
            proposed=[{
                "rank": 1, "action": "y",
                "cli_command": "shopai y",
            }],
            anomalies=[{
                "type": "ORPHAN_BURST",
                "severity": "warn",
            }],
            anomaly_critical_count=0,
        )
        out = _build_next_action(b)
        # Warn-only anomalies don't escalate; plan rank-1
        # still surfaces
        assert "y" in out
        assert "CRITICAL anomaly" not in out


# ── build_morning_brief (integration via mocks) ───────────


@dataclass
class _FakeSummary:
    verdict: str = "earning"
    fleet_gross_profit: float = 100.0
    fleet_attribution_pct: float = 50.0
    monthly_run_rate: float = 400.0
    trend_verdict: str = "flat"


@dataclass
class _FakeRecon:
    fleet_orphan_action_count: int = 2


@dataclass
class _FakeAction:
    rank: int
    action: str
    cli_command: str
    rationale: str = "r"
    priority: str = "normal"


@dataclass
class _FakeReport:
    proposed: list = field(default_factory=list)
    verdict: str = "earning"


class TestBuildMorningBrief:
    def test_composes_all_substrate(self):
        fake_summary = _FakeSummary()
        fake_recon = _FakeRecon()
        fake_props = _FakeReport(
            proposed=[
                _FakeAction(
                    rank=1, action="A",
                    cli_command="shopai A",
                ),
                _FakeAction(
                    rank=2, action="B",
                    cli_command="shopai B",
                ),
            ],
            verdict="earning",
        )

        # W963-71+: also mock anomaly + streak + diff so
        # real history snapshots don't bleed into the test.
        # W963-81+: also mock arm-recommender.
        # W963-89+: also mock earn-path.
        @dataclass
        class _FakeEarnPath:
            completed_count: int = 8
            total_count: int = 8
            next_command: str | None = None
            next_title: str | None = None

        @dataclass
        class _FakeArmReport:
            override_applied: str | None = None
            arm_recommendations: list = field(
                default_factory=list,
            )
            disarm_recommendations: list = field(
                default_factory=list,
            )

        @dataclass
        class _FakeAnomReport:
            anomalies: list = field(default_factory=list)

        @dataclass
        class _FakeStreak:
            name: str = "loss_streak"
            count: int = 0
            severity: str = "info"

        @dataclass
        class _FakeStreakReport:
            attention_needed: bool = False
            top_streak: str = ""
            loss_streak: _FakeStreak = field(
                default_factory=_FakeStreak,
            )
            no_data_streak: _FakeStreak = field(
                default_factory=_FakeStreak,
            )
            anomaly_streak: _FakeStreak = field(
                default_factory=_FakeStreak,
            )

        @dataclass
        class _FakeDiff:
            direction: str = "no_data"
            headline: str = ""
            gross_profit_delta: float = 0.0

        with patch(
            "engines.agi_earnings_summary.summarizer."
            "compute_summary",
            return_value=fake_summary,
        ), patch(
            "engines.agi_earnings_history.store."
            "compute_trend",
            return_value={
                "verdict": "improving",
                "sample_count": 5,
            },
        ), patch(
            "engines.revenue_reconciliation.reconciler."
            "reconcile_fleet",
            return_value=fake_recon,
        ), patch(
            "core.approval.queue.get_approval_queue",
        ) as fake_q, patch(
            "engines._cycle_history.last_run",
            return_value=None,
        ), patch(
            "engines.llm_action_proposer.proposer.propose",
            return_value=fake_props,
        ), patch(
            "engines.agi_anomaly_detector.detector.detect",
            return_value=_FakeAnomReport(),
        ), patch(
            "engines.agi_recommend_streak.detector."
            "detect_streaks",
            return_value=_FakeStreakReport(),
        ), patch(
            "engines.agi_brief_diff.differ.compute_diff",
            return_value=_FakeDiff(),
        ), patch(
            "engines.agi_arm_recommender.recommender."
            "recommend",
            return_value=_FakeArmReport(),
        ), patch(
            "engines.earn_path.guide.build_path",
            return_value=_FakeEarnPath(),
        ), patch(
            "engines.llm_action_critic.critic.critique",
        ) as fake_critique:
            fake_q.return_value.list_by_status\
                .return_value = ["p1", "p2", "p3"]

            @dataclass
            class _FakeCriticReport:
                critiques: list = field(default_factory=list)

            @dataclass
            class _FakeCritique:
                rank: int
                severity: str
                risk_flags: list
                counter_rationale: str

            fake_critique.return_value = _FakeCriticReport(
                critiques=[
                    _FakeCritique(
                        rank=1, severity="warn",
                        risk_flags=["wide"],
                        counter_rationale="ok",
                    ),
                ],
            )
            b = build_morning_brief()

        assert b.verdict == "earning"
        assert b.gross_profit == 100.0
        assert b.history_trend_verdict == "improving"
        assert b.orphan_action_count == 2
        assert b.pending_approvals == 3
        assert len(b.proposed) == 2
        assert len(b.critiques) == 1
        assert "EARNING" in b.headline
        assert "WARN" in b.next_action

    def test_resilient_when_substrate_raises(self):
        # Every gather raises; brief still returns sane defaults
        with patch(
            "engines.agi_earnings_summary.summarizer."
            "compute_summary",
            side_effect=RuntimeError("x"),
        ), patch(
            "engines.agi_earnings_history.store."
            "compute_trend",
            side_effect=RuntimeError("y"),
        ), patch(
            "engines.revenue_reconciliation.reconciler."
            "reconcile_fleet",
            side_effect=RuntimeError("z"),
        ), patch(
            "core.approval.queue.get_approval_queue",
            side_effect=RuntimeError("a"),
        ), patch(
            "engines._cycle_history.last_run",
            side_effect=RuntimeError("b"),
        ), patch(
            "engines.llm_action_proposer.proposer.propose",
            side_effect=RuntimeError("c"),
        ), patch(
            "engines.agi_anomaly_detector.detector.detect",
            side_effect=RuntimeError("d"),
        ), patch(
            "engines.agi_recommend_streak.detector."
            "detect_streaks",
            side_effect=RuntimeError("e"),
        ), patch(
            "engines.agi_brief_diff.differ.compute_diff",
            side_effect=RuntimeError("f"),
        ), patch(
            "engines.agi_arm_recommender.recommender."
            "recommend",
            side_effect=RuntimeError("g"),
        ), patch(
            "engines.earn_path.guide.build_path",
            side_effect=RuntimeError("h"),
        ):
            b = build_morning_brief()
        assert b.verdict == "no_data"
        assert b.headline.startswith("Empire IDLE")
        assert b.next_action == "No next-action proposed."


# ── Pattern Q envelope ────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = AgiMorningBriefEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = AgiMorningBriefEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = AgiMorningBriefEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = AgiMorningBriefEngine().run({
            "status": "fail", "error": "x",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = AgiMorningBriefEngine().run({})
        assert (
            r["meta"]["engine"] == "agi_morning_brief"
        )

    def test_has_headline(self):
        r = AgiMorningBriefEngine().run({})
        assert "headline" in r["data"]
        assert r["data"]["headline"]
