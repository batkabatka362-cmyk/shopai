"""Tests for engines._approval_sla."""
from __future__ import annotations

import time
from types import SimpleNamespace

from engines._approval_sla import (
    SLAClassification,
    classify_action,
    compute_sla_report,
    critical_threshold_hours,
    warn_threshold_hours,
)


def _action(*, action_id="a", engine="x", proposed_at=None):
    return SimpleNamespace(
        id=action_id,
        engine=engine,
        proposed_at=proposed_at,
    )


class TestThresholds:

    def test_warn_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_APPROVAL_SLA_WARN_HOURS", raising=False,
        )
        assert warn_threshold_hours() == 4.0

    def test_warn_custom(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_APPROVAL_SLA_WARN_HOURS", "2",
        )
        assert warn_threshold_hours() == 2.0

    def test_warn_invalid_returns_default(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_APPROVAL_SLA_WARN_HOURS", "junk",
        )
        assert warn_threshold_hours() == 4.0

    def test_critical_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_APPROVAL_SLA_CRITICAL_HOURS", raising=False,
        )
        assert critical_threshold_hours() == 24.0


class TestClassify:

    def test_fresh_action_on_time(self):
        now = time.time()
        a = _action(proposed_at=now - 60)  # 1 minute old
        c = classify_action(a, now=now, warn_h=4, critical_h=24)
        assert c.band == "on_time"
        assert c.age_hours < 0.1

    def test_aging(self):
        now = time.time()
        a = _action(proposed_at=now - 5 * 3600)  # 5h
        c = classify_action(a, now=now, warn_h=4, critical_h=24)
        assert c.band == "aging"

    def test_breached(self):
        now = time.time()
        a = _action(proposed_at=now - 48 * 3600)  # 48h
        c = classify_action(a, now=now, warn_h=4, critical_h=24)
        assert c.band == "breached"
        assert c.is_breached is True
        assert c.age_hours > 47

    def test_no_proposed_at_returns_none(self):
        a = _action(proposed_at=None)
        c = classify_action(a, now=time.time())
        assert c is None

    def test_invalid_proposed_at_returns_none(self):
        a = _action(proposed_at="not_a_timestamp")
        c = classify_action(a, now=time.time())
        assert c is None


class TestSLAReport:

    def test_empty_actions(self):
        r = compute_sla_report(actions=[])
        assert r.total_pending == 0
        assert r.has_breaches is False

    def test_mixed_bands(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_APPROVAL_SLA_WARN_HOURS", "4",
        )
        monkeypatch.setenv(
            "SHOPAI_APPROVAL_SLA_CRITICAL_HOURS", "24",
        )
        now = time.time()
        actions = [
            _action(action_id="fresh", proposed_at=now - 60),
            _action(action_id="aging", proposed_at=now - 5 * 3600),
            _action(action_id="old", proposed_at=now - 30 * 3600),
        ]
        r = compute_sla_report(actions=actions)
        assert r.total_pending == 3
        assert r.on_time == 1
        assert r.aging == 1
        assert r.breached == 1
        assert r.has_breaches is True
        assert r.oldest_breach is not None
        assert r.oldest_breach.action_id == "old"

    def test_breached_actions_sorted_oldest_first(
        self, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_APPROVAL_SLA_CRITICAL_HOURS", "24",
        )
        now = time.time()
        actions = [
            _action(
                action_id="48h", proposed_at=now - 48 * 3600,
            ),
            _action(
                action_id="100h", proposed_at=now - 100 * 3600,
            ),
            _action(
                action_id="30h", proposed_at=now - 30 * 3600,
            ),
        ]
        r = compute_sla_report(actions=actions)
        assert r.breached == 3
        # Oldest first
        assert r.breached_actions[0].action_id == "100h"
        assert r.breached_actions[-1].action_id == "30h"
