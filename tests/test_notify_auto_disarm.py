"""Tests for notify auto-disarm push alert (W963-86)."""
from __future__ import annotations

from unittest.mock import patch


class TestAutoDisarmAlerts:
    def test_emits_critical_when_event_recent(self):
        from engines._notify import collect_alerts
        with patch(
            "engines.agi_arm_recommender.auto_disarm_log."
            "recent_events",
            return_value=[
                {
                    "ts": 12345.0,
                    "override_reason": (
                        "critical_loss_streak: full spend "
                        "disarm"
                    ),
                    "domains_disarmed": [
                        "marketing", "customer_support",
                    ],
                    "engines_recommended": [
                        "ads_launcher",
                    ],
                },
            ],
        ):
            alerts = collect_alerts()
        ad_alerts = [
            a for a in alerts
            if a.kind == "agi_auto_disarmed"
        ]
        assert len(ad_alerts) == 1
        assert ad_alerts[0].severity == "critical"
        assert "marketing" in ad_alerts[0].message
        assert (
            "customer_support" in ad_alerts[0].message
        )

    def test_no_alert_when_no_event(self):
        from engines._notify import collect_alerts
        with patch(
            "engines.agi_arm_recommender.auto_disarm_log."
            "recent_events",
            return_value=[],
        ):
            alerts = collect_alerts()
        ad_alerts = [
            a for a in alerts
            if a.kind == "agi_auto_disarmed"
        ]
        assert ad_alerts == []

    def test_log_raises_swallowed(self):
        from engines._notify import collect_alerts
        with patch(
            "engines.agi_arm_recommender.auto_disarm_log."
            "recent_events",
            side_effect=RuntimeError("boom"),
        ):
            alerts = collect_alerts()
        assert isinstance(alerts, list)

    def test_alert_carries_context(self):
        from engines._notify import collect_alerts
        with patch(
            "engines.agi_arm_recommender.auto_disarm_log."
            "recent_events",
            return_value=[
                {
                    "ts": 99.0,
                    "override_reason": "x",
                    "domains_disarmed": ["marketing"],
                    "engines_recommended": ["ads"],
                },
            ],
        ):
            alerts = collect_alerts()
        ad = next(
            a for a in alerts
            if a.kind == "agi_auto_disarmed"
        )
        assert ad.context["domains"] == ["marketing"]
        assert ad.context["override_reason"] == "x"
        assert ad.context["engines_recommended"] == ["ads"]

    def test_message_truncates_long_reason(self):
        from engines._notify import collect_alerts
        long_reason = "x" * 200
        with patch(
            "engines.agi_arm_recommender.auto_disarm_log."
            "recent_events",
            return_value=[
                {
                    "ts": 1.0,
                    "override_reason": long_reason,
                    "domains_disarmed": ["m"],
                },
            ],
        ):
            alerts = collect_alerts()
        ad = next(
            a for a in alerts
            if a.kind == "agi_auto_disarmed"
        )
        # Reason chopped to 80 char display in message
        assert "x" * 80 in ad.message
