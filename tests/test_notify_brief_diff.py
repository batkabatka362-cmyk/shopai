"""Tests for notify brief-diff regression alerts (W963-75)."""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import patch


@dataclass
class _FakeDiff:
    sufficient: bool = True
    direction: str = "regressed"
    verdict_change: str = "regressed"
    previous_verdict: str = "earning"
    current_verdict: str = "attributed_loss"
    gross_profit_delta: float = -200.0
    attribution_pct_delta: float = -10.0


# ── alert emission ────────────────────────────────────────


class TestBriefDiffAlerts:
    def test_verdict_regressed_emits_critical(self):
        """When the verdict band itself regressed, alert
        severity is critical regardless of $ amount."""
        from engines._notify import collect_alerts
        fake = _FakeDiff(
            verdict_change="regressed",
            gross_profit_delta=-10.0,  # small but verdict
                                        # change makes
                                        # it critical
        )
        with patch(
            "engines.agi_brief_diff.differ.compute_diff",
            return_value=fake,
        ):
            alerts = collect_alerts()
        brief_alerts = [
            a for a in alerts
            if a.kind == "agi_brief_regression"
        ]
        assert len(brief_alerts) == 1
        assert brief_alerts[0].severity == "critical"

    def test_significant_dollar_drop_critical(self):
        """Verdict same but $ drop >= $50 should be
        critical."""
        from engines._notify import collect_alerts
        fake = _FakeDiff(
            verdict_change="no_change",
            current_verdict="earning",
            previous_verdict="earning",
            gross_profit_delta=-80.0,
        )
        with patch(
            "engines.agi_brief_diff.differ.compute_diff",
            return_value=fake,
        ):
            alerts = collect_alerts()
        brief_alerts = [
            a for a in alerts
            if a.kind == "agi_brief_regression"
        ]
        assert len(brief_alerts) == 1
        assert brief_alerts[0].severity == "critical"

    def test_small_drop_warn(self):
        """Verdict same and small $ drop -- still report
        but warn-level only."""
        from engines._notify import collect_alerts
        fake = _FakeDiff(
            verdict_change="no_change",
            current_verdict="earning",
            previous_verdict="earning",
            gross_profit_delta=-20.0,
        )
        with patch(
            "engines.agi_brief_diff.differ.compute_diff",
            return_value=fake,
        ):
            alerts = collect_alerts()
        brief_alerts = [
            a for a in alerts
            if a.kind == "agi_brief_regression"
        ]
        assert len(brief_alerts) == 1
        assert brief_alerts[0].severity == "warn"

    def test_improved_does_not_emit(self):
        """Improved direction should not push an alert."""
        from engines._notify import collect_alerts
        fake = _FakeDiff(
            direction="improved",
            verdict_change="improved",
            gross_profit_delta=100.0,
        )
        with patch(
            "engines.agi_brief_diff.differ.compute_diff",
            return_value=fake,
        ):
            alerts = collect_alerts()
        brief_alerts = [
            a for a in alerts
            if a.kind == "agi_brief_regression"
        ]
        assert brief_alerts == []

    def test_unchanged_does_not_emit(self):
        from engines._notify import collect_alerts
        fake = _FakeDiff(
            direction="unchanged",
            verdict_change="no_change",
            gross_profit_delta=0.0,
        )
        with patch(
            "engines.agi_brief_diff.differ.compute_diff",
            return_value=fake,
        ):
            alerts = collect_alerts()
        brief_alerts = [
            a for a in alerts
            if a.kind == "agi_brief_regression"
        ]
        assert brief_alerts == []

    def test_insufficient_diff_does_not_emit(self):
        """When fewer than 2 snapshots available."""
        from engines._notify import collect_alerts
        fake = _FakeDiff(
            sufficient=False, direction="no_data",
        )
        with patch(
            "engines.agi_brief_diff.differ.compute_diff",
            return_value=fake,
        ):
            alerts = collect_alerts()
        brief_alerts = [
            a for a in alerts
            if a.kind == "agi_brief_regression"
        ]
        assert brief_alerts == []

    def test_differ_raises_swallowed(self):
        from engines._notify import collect_alerts
        with patch(
            "engines.agi_brief_diff.differ.compute_diff",
            side_effect=RuntimeError("boom"),
        ):
            alerts = collect_alerts()
        assert isinstance(alerts, list)

    def test_alert_carries_context(self):
        from engines._notify import collect_alerts
        fake = _FakeDiff(
            verdict_change="regressed",
            previous_verdict="earning",
            current_verdict="organic_only",
            gross_profit_delta=-150.0,
            attribution_pct_delta=-60.0,
        )
        with patch(
            "engines.agi_brief_diff.differ.compute_diff",
            return_value=fake,
        ):
            alerts = collect_alerts()
        brief_alerts = [
            a for a in alerts
            if a.kind == "agi_brief_regression"
        ]
        ctx = brief_alerts[0].context
        assert ctx["previous_verdict"] == "earning"
        assert ctx["current_verdict"] == "organic_only"
        assert ctx["gross_profit_delta"] == -150.0
        assert ctx["attribution_pct_delta"] == -60.0

    def test_alert_message_includes_dollar_sign(self):
        """Bug guard: sign should be BEFORE $, not after."""
        from engines._notify import collect_alerts
        fake = _FakeDiff(
            verdict_change="regressed",
            gross_profit_delta=-250.0,
        )
        with patch(
            "engines.agi_brief_diff.differ.compute_diff",
            return_value=fake,
        ):
            alerts = collect_alerts()
        brief_alerts = [
            a for a in alerts
            if a.kind == "agi_brief_regression"
        ]
        msg = brief_alerts[0].message
        # Must show "-$250" not "$-250"
        assert "-$250" in msg
        assert "$-250" not in msg
