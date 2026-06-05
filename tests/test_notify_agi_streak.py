"""Tests for notify AGI attention streak alerts (W963-71)."""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import patch


@dataclass
class _FakeStreak:
    name: str
    count: int = 0
    severity: str = "info"
    drill: str = ""
    detail: str = ""


@dataclass
class _FakeStreakReport:
    loss_streak: _FakeStreak = field(
        default_factory=lambda: _FakeStreak("loss_streak"),
    )
    no_data_streak: _FakeStreak = field(
        default_factory=lambda: _FakeStreak("no_data_streak"),
    )
    anomaly_streak: _FakeStreak = field(
        default_factory=lambda: _FakeStreak("anomaly_streak"),
    )


class TestStreakAlerts:
    def test_critical_loss_emits_alert(self):
        from engines._notify import collect_alerts
        fake = _FakeStreakReport(
            loss_streak=_FakeStreak(
                name="loss_streak",
                count=7,
                severity="critical",
                detail="loss for 7 cycles",
                drill="shopai roas",
            ),
        )
        with patch(
            "engines.agi_recommend_streak.detector."
            "detect_streaks",
            return_value=fake,
        ):
            alerts = collect_alerts()
        streak_alerts = [
            a for a in alerts
            if a.kind == "agi_attention_streak"
        ]
        assert len(streak_alerts) == 1
        assert streak_alerts[0].severity == "critical"
        assert "loss_streak" in streak_alerts[0].message

    def test_warn_streak_does_not_emit(self):
        from engines._notify import collect_alerts
        fake = _FakeStreakReport(
            loss_streak=_FakeStreak(
                name="loss_streak",
                count=3,
                severity="warn",
            ),
        )
        with patch(
            "engines.agi_recommend_streak.detector."
            "detect_streaks",
            return_value=fake,
        ):
            alerts = collect_alerts()
        streak_alerts = [
            a for a in alerts
            if a.kind == "agi_attention_streak"
        ]
        assert streak_alerts == []

    def test_only_one_alert_when_multiple_critical(self):
        from engines._notify import collect_alerts
        fake = _FakeStreakReport(
            loss_streak=_FakeStreak(
                name="loss_streak",
                count=6, severity="critical",
            ),
            no_data_streak=_FakeStreak(
                name="no_data_streak",
                count=7, severity="critical",
            ),
        )
        with patch(
            "engines.agi_recommend_streak.detector."
            "detect_streaks",
            return_value=fake,
        ):
            alerts = collect_alerts()
        streak_alerts = [
            a for a in alerts
            if a.kind == "agi_attention_streak"
        ]
        assert len(streak_alerts) == 1
        # First in iteration (loss_streak) wins
        assert "loss_streak" in streak_alerts[0].message

    def test_detector_raises_swallowed(self):
        from engines._notify import collect_alerts
        with patch(
            "engines.agi_recommend_streak.detector."
            "detect_streaks",
            side_effect=RuntimeError("boom"),
        ):
            alerts = collect_alerts()
        assert isinstance(alerts, list)

    def test_no_streaks_no_alert(self):
        from engines._notify import collect_alerts
        fake = _FakeStreakReport()
        with patch(
            "engines.agi_recommend_streak.detector."
            "detect_streaks",
            return_value=fake,
        ):
            alerts = collect_alerts()
        streak_alerts = [
            a for a in alerts
            if a.kind == "agi_attention_streak"
        ]
        assert streak_alerts == []

    def test_alert_carries_context(self):
        from engines._notify import collect_alerts
        fake = _FakeStreakReport(
            anomaly_streak=_FakeStreak(
                name="anomaly_streak",
                count=8, severity="critical",
                detail="x", drill="shopai anomalies",
            ),
        )
        with patch(
            "engines.agi_recommend_streak.detector."
            "detect_streaks",
            return_value=fake,
        ):
            alerts = collect_alerts()
        streak_alerts = [
            a for a in alerts
            if a.kind == "agi_attention_streak"
        ]
        ctx = streak_alerts[0].context
        assert ctx["streak"] == "anomaly_streak"
        assert ctx["count"] == 8
        assert ctx["drill"] == "shopai anomalies"
