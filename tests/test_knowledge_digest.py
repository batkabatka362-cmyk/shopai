"""Tests for the insight-digest renderer.

The digest reads four signal streams and produces a one-page
Markdown briefing. Coverage:

  1. Header — frontmatter + timestamp + window label.
  2. Active goal section — pulls from GoalManager, falls back to
     ``maximize_profit`` when manager unavailable / raises.
  3. Top recommendations — uses engine_recommender, degrades to
     "no recommendations available" when the recommender raises.
  4. Goal leaderboard — sorted by effectiveness desc, every
     canonical goal listed (zero-sample fallback rendered as
     no_data).
  5. Recent decisions window — filtered by ``since_days``,
     capped by ``decision_limit``.
  6. Engine activity counter — from windowed decisions, top 10.
  7. Skipped section — appended when any source raised.
  8. write_to helper — file written, parent dir created.
  9. DigestStats serialisation.
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.knowledge import DigestStats, InsightDigest
from core.goals.goal_manager import GoalManager


@pytest.fixture
def fresh_manager() -> GoalManager:
    return GoalManager()


def _decision(
    *,
    engine: str = "cart_recovery",
    action_type: str = "mint_recovery_code",
    status_value: str = "executed",
    decided_at: float | None = None,
    narrative: str = "test decision",
) -> MagicMock:
    """Build a fake ApprovalAction-like object."""
    action = MagicMock()
    action.engine = engine
    action.action_type = action_type
    status = MagicMock()
    status.value = status_value
    action.status = status
    action.decided_at = (
        decided_at if decided_at is not None else time.time()
    )
    action.narrative = narrative
    return action


# ─── Header / frontmatter ──────────────────────────────────────


class TestHeader:

    def test_frontmatter_present(self, fresh_manager):
        md, _ = InsightDigest(
            goal_manager=fresh_manager,
        ).render()
        assert md.startswith("---\n")
        assert "type: digest" in md
        assert "source: shopai" in md
        assert "since_days: 7" in md

    def test_title_visible(self, fresh_manager):
        md, _ = InsightDigest(
            goal_manager=fresh_manager,
        ).render()
        assert "# ShopAI Insight Digest" in md


# ─── Active goal ───────────────────────────────────────────────


class TestActiveGoal:

    def test_default_goal_when_no_outcomes(self, fresh_manager):
        md, stats = InsightDigest(
            goal_manager=fresh_manager,
        ).render()
        # Default goal in fresh GoalManager is maximize_profit
        assert stats.active_goal == "maximize_profit"
        assert "[[maximize_profit]]" in md
        assert "no_data" in md

    def test_uses_manager_goal(self, fresh_manager):
        # Force a switch (mock simpler than running select_goal)
        mgr = MagicMock()
        mgr.get_current_goal.return_value = "grow_customers"
        mgr.get_effectiveness.return_value = 0.7
        mgr.get_effectiveness_stats.return_value = {
            "grow_customers": {"effectiveness": 0.7, "n": 5},
        }
        md, stats = InsightDigest(goal_manager=mgr).render()
        assert stats.active_goal == "grow_customers"
        assert "**[[grow_customers]]**" in md

    def test_manager_failure_falls_back(self):
        mgr = MagicMock()
        mgr.get_current_goal.side_effect = RuntimeError("boom")
        md, stats = InsightDigest(goal_manager=mgr).render()
        # Falls back to maximize_profit
        assert stats.active_goal == "maximize_profit"
        # Skip diagnostic recorded
        assert any(
            "active_goal" in s for s in (stats.skipped or [])
        )


# ─── Top recommendations ──────────────────────────────────────


class TestRecommendations:

    def test_table_rendered_with_picks(self, fresh_manager):
        md, _ = InsightDigest(
            goal_manager=fresh_manager,
            recommendation_limit=3,
        ).render()
        assert "## Top recommendations" in md
        # Table header
        assert "| Rank | Engine | Priority | Effectiveness |" in md
        # Some picks present
        assert "| 1 | [[" in md

    def test_recommender_failure_renders_placeholder(
        self, fresh_manager,
    ):
        with patch(
            "core.brain.engine_recommender.recommend_engines",
            side_effect=RuntimeError("boom"),
        ):
            md, stats = InsightDigest(
                goal_manager=fresh_manager,
            ).render()
        assert "no recommendations available" in md
        assert any(
            "recommendations" in s for s in (stats.skipped or [])
        )


# ─── Goal leaderboard ──────────────────────────────────────────


class TestGoalLeaderboard:

    def test_every_canonical_goal_listed(self, fresh_manager):
        md, _ = InsightDigest(
            goal_manager=fresh_manager,
        ).render()
        for goal in [
            "maximize_profit", "grow_customers", "increase_aov",
            "survive_crisis", "capture_opportunity",
        ]:
            assert f"[[{goal}]]" in md

    def test_no_data_renders_for_neutral_goals(self, fresh_manager):
        md, _ = InsightDigest(
            goal_manager=fresh_manager,
        ).render()
        # Leaderboard section contains no_data
        leaderboard = md.split("## Goal effectiveness leaderboard")[1]
        leaderboard = leaderboard.split("##")[0]
        # All 5 goals at neutral → 5 no_data rows
        assert leaderboard.count("no_data") == 5

    def test_recorded_outcomes_surface_value(self, fresh_manager):
        for _ in range(3):
            fresh_manager.record_goal_outcome(
                "grow_customers",
                {"profit_delta": 5, "health_delta": 1},
            )
        md, _ = InsightDigest(
            goal_manager=fresh_manager,
        ).render()
        # Leaderboard row for grow_customers shows numeric value
        # (not no_data) and a sample count > 0
        assert "0.5" not in md.split("[[grow_customers]]")[1].split("|")[0]
        # samples column reflects 3
        # find the leaderboard line for grow_customers
        for line in md.splitlines():
            if "[[grow_customers]]" in line and "| 3 |" in line:
                break
        else:
            pytest.fail("grow_customers row with 3 samples not found")


# ─── Recent decisions ──────────────────────────────────────────


class TestRecentDecisions:

    def test_empty_window_renders_placeholder(self, fresh_manager):
        fake_queue = MagicMock()
        fake_queue.list_executed.return_value = []
        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            md, stats = InsightDigest(
                goal_manager=fresh_manager,
            ).render()
        assert "no decisions in this window" in md
        assert stats.decisions_window == 0

    def test_populated_window(self, fresh_manager):
        # 3 fresh + 1 old
        now = time.time()
        fake_queue = MagicMock()
        fake_queue.list_executed.return_value = [
            _decision(engine="cart_recovery", decided_at=now - 60),
            _decision(engine="loyalty", decided_at=now - 120),
            _decision(engine="cart_recovery", decided_at=now - 180),
            _decision(  # outside the window
                engine="discount_strategy",
                decided_at=now - 365 * 86400,
            ),
        ]
        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            md, stats = InsightDigest(
                goal_manager=fresh_manager,
                since_days=7,
            ).render()
        # Window shows 3 (the fourth is filtered out)
        assert stats.decisions_window == 3
        assert "[[cart_recovery]]" in md
        # Engine activity table reflects the windowed counts
        # (cart_recovery appears twice, loyalty once)
        activity = md.split("## Engine activity in window")[1]
        assert "[[cart_recovery]]" in activity
        assert "| 2 |" in activity.split("[[cart_recovery]]")[1].split("|")[1] or "| 2 |" in activity

    def test_totals_count_full_history_not_window(
        self, fresh_manager,
    ):
        now = time.time()
        far_past = now - 365 * 86400
        fake_queue = MagicMock()
        # 1 executed in window, 1 executed outside, 1 failed outside
        actions = [
            _decision(status_value="executed", decided_at=now - 60),
            _decision(status_value="executed", decided_at=far_past),
            _decision(status_value="failed", decided_at=far_past),
        ]
        fake_queue.list_executed.return_value = actions
        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            md, stats = InsightDigest(
                goal_manager=fresh_manager,
            ).render()
        # Cumulative counts include outside-window entries
        assert stats.decisions_total_executed == 2
        assert stats.decisions_total_failed == 1
        # Window only has the recent one
        assert stats.decisions_window == 1

    def test_decision_limit_caps_list(self, fresh_manager):
        now = time.time()
        actions = [
            _decision(engine=f"engine_{i}", decided_at=now - i)
            for i in range(50)
        ]
        fake_queue = MagicMock()
        fake_queue.list_executed.return_value = actions
        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            _, stats = InsightDigest(
                goal_manager=fresh_manager,
                decision_limit=10,
            ).render()
        assert stats.decisions_window == 10

    def test_queue_unavailable_records_skip(self, fresh_manager):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("db missing"),
        ):
            md, stats = InsightDigest(
                goal_manager=fresh_manager,
            ).render()
        assert any(
            "decisions" in s for s in (stats.skipped or [])
        )
        # Section still renders header + placeholder
        assert "## Recent decisions" in md
        assert "no decisions" in md


# ─── write_to helper ───────────────────────────────────────────


class TestWriteTo:

    def test_writes_to_file(self, tmp_path: Path, fresh_manager):
        target = tmp_path / "subdir" / "digest.md"
        # Parent dir doesn't exist — write_to creates it
        digest = InsightDigest(goal_manager=fresh_manager)
        stats = digest.write_to(target)
        assert target.exists()
        content = target.read_text(encoding="utf-8")
        assert content.startswith("---\n")
        assert "ShopAI Insight Digest" in content
        assert isinstance(stats, DigestStats)


# ─── DigestStats serialisation ─────────────────────────────────


class TestDigestStatsSerialization:

    def test_to_dict_round_trip(self):
        s = DigestStats(
            active_goal="grow_customers",
            decisions_window=5,
            decisions_total_executed=10,
            decisions_total_failed=2,
            top_engine="cart_recovery",
            skipped=["x: err"],
        )
        d = s.to_dict()
        assert d["active_goal"] == "grow_customers"
        assert d["decisions_window"] == 5
        assert d["decisions_total_executed"] == 10
        assert d["decisions_total_failed"] == 2
        assert d["top_engine"] == "cart_recovery"
        assert d["skipped"] == ["x: err"]


# ─── Edge cases ────────────────────────────────────────────────


class TestEdgeCases:

    def test_zero_since_days_clamped_to_one(self, fresh_manager):
        digest = InsightDigest(
            goal_manager=fresh_manager, since_days=0,
        )
        assert digest.since_days == 1

    def test_negative_decision_limit_clamped(self, fresh_manager):
        digest = InsightDigest(
            goal_manager=fresh_manager, decision_limit=-5,
        )
        assert digest.decision_limit == 0

    def test_zero_recommendation_limit_clamped(self, fresh_manager):
        digest = InsightDigest(
            goal_manager=fresh_manager, recommendation_limit=0,
        )
        assert digest.recommendation_limit == 1
