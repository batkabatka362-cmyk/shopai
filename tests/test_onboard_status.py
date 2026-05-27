"""Tests for engines.store_setup.onboard_status."""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.onboard_status import (
    OnboardStatus,
    _verdict,
    get_onboard_status,
)


def _fake_sm(*, niche="", created_at=None):
    """StoreManager stub with a single store row."""
    sm = MagicMock()
    sm.get_store.return_value = {
        "store_id": "s1",
        "shop_url": "s1.myshopify.com",
        "niche": niche,
        "created_at": created_at,
    }
    return sm


def _fake_run(*, started_at, verdict="ok"):
    return SimpleNamespace(
        started_at=started_at,
        verdict=verdict,
    )


class TestStoreLookup:

    def test_missing_store_marks_not_found(self):
        sm = MagicMock()
        sm.get_store.return_value = None
        result = get_onboard_status(
            "missing", store_manager=sm,
        )
        assert result.found is False
        assert "not found" in result.error

    def test_get_store_raises_returns_error(self):
        sm = MagicMock()
        sm.get_store.side_effect = RuntimeError("db down")
        result = get_onboard_status(
            "s1", store_manager=sm,
        )
        assert result.found is False
        assert "db down" in result.error


class TestOnboardingAge:

    def test_age_hours_computed_from_created_at(self):
        # Onboarded 2 hours ago
        sm = _fake_sm(created_at=time.time() - 7200)
        with patch(
            "engines._cycle_history.recent_runs",
            return_value=[],
        ):
            result = get_onboard_status(
                "s1", store_manager=sm,
            )
        assert result.onboarded_age_hours is not None
        assert abs(result.onboarded_age_hours - 2.0) < 0.1

    def test_missing_created_at_leaves_age_none(self):
        sm = _fake_sm(created_at=None)
        with patch(
            "engines._cycle_history.recent_runs",
            return_value=[],
        ):
            result = get_onboard_status(
                "s1", store_manager=sm,
            )
        assert result.onboarded_age_hours is None

    def test_niche_active_when_non_general(self):
        sm = _fake_sm(
            niche="beauty",
            created_at=time.time() - 7200,
        )
        with patch(
            "engines._cycle_history.recent_runs",
            return_value=[],
        ):
            result = get_onboard_status(
                "s1", store_manager=sm,
            )
        assert result.niche == "beauty"
        assert result.niche_active is True

    def test_niche_inactive_when_general(self):
        sm = _fake_sm(
            niche="general",
            created_at=time.time() - 7200,
        )
        with patch(
            "engines._cycle_history.recent_runs",
            return_value=[],
        ):
            result = get_onboard_status(
                "s1", store_manager=sm,
            )
        assert result.niche_active is False


class TestCycleActivity:

    def test_only_cycles_since_onboarding_counted(self):
        # Onboarded 3 hours ago
        now = time.time()
        sm = _fake_sm(created_at=now - 3 * 3600)
        # Cycle 4h ago = before onboarding (excluded);
        # cycles at 2h + 1h + 30min = post-onboarding
        runs = [
            _fake_run(started_at=now - 30 * 60),
            _fake_run(started_at=now - 1 * 3600),
            _fake_run(started_at=now - 2 * 3600),
            _fake_run(started_at=now - 4 * 3600),
        ]
        with patch(
            "engines._cycle_history.recent_runs",
            return_value=runs,
        ):
            result = get_onboard_status(
                "s1", store_manager=sm,
            )
        # 3 post-onboarding cycles
        assert result.cycles_since_onboarding == 3
        # Latest is 30min ago = 0.5h
        assert result.last_cycle_age_hours is not None
        assert abs(result.last_cycle_age_hours - 0.5) < 0.1

    def test_no_cycles_leaves_last_age_none(self):
        sm = _fake_sm(created_at=time.time() - 7200)
        with patch(
            "engines._cycle_history.recent_runs",
            return_value=[],
        ):
            result = get_onboard_status(
                "s1", store_manager=sm,
            )
        assert result.cycles_since_onboarding == 0
        assert result.last_cycle_age_hours is None


class TestVerdict:

    def _build(self, **kw):
        defaults = dict(
            store_id="s1",
            onboarded_age_hours=24.0,
            cycles_since_onboarding=10,
            last_cycle_age_hours=1.0,
            activity_executed=0,
            activity_failed=0,
            launch_gaps_total=0,
            launch_gaps_manual=0,
            launch_gaps_closeable=0,
        )
        defaults.update(kw)
        return OnboardStatus(**defaults)

    def test_just_onboarded_when_fresh(self):
        s = self._build(onboarded_age_hours=0.5)
        verdict, _ = _verdict(s)
        assert verdict == "just_onboarded"

    def test_thriving_when_activity_and_recent_cycle(self):
        s = self._build(
            activity_executed=5, last_cycle_age_hours=1.0,
        )
        verdict, _ = _verdict(s)
        assert verdict == "thriving"

    def test_needs_attention_when_no_cycle_after_24h(self):
        s = self._build(
            onboarded_age_hours=48.0,
            last_cycle_age_hours=None,
        )
        verdict, _ = _verdict(s)
        assert verdict == "needs_attention"

    def test_needs_attention_when_stale_cycle(self):
        s = self._build(
            last_cycle_age_hours=72.0,
        )
        verdict, _ = _verdict(s)
        assert verdict == "needs_attention"

    def test_needs_attention_when_failure_dominant(self):
        s = self._build(
            activity_executed=1,
            activity_failed=5,
        )
        verdict, _ = _verdict(s)
        assert verdict == "needs_attention"

    def test_needs_attention_when_closeable_gaps_open(self):
        s = self._build(
            launch_gaps_total=2, launch_gaps_closeable=2,
        )
        verdict, _ = _verdict(s)
        assert verdict == "needs_attention"

    def test_quiet_when_only_manual_gaps(self):
        s = self._build(
            launch_gaps_total=1, launch_gaps_manual=1,
        )
        verdict, _ = _verdict(s)
        # Operator-only gaps; orchestrator can't help
        assert verdict == "quiet"

    def test_quiet_when_cycles_ran_but_no_activity(self):
        s = self._build(
            activity_executed=0,
            last_cycle_age_hours=2.0,
        )
        verdict, _ = _verdict(s)
        assert verdict == "quiet"


class TestNextAction:

    def test_needs_attention_no_cycle_suggests_schedule(self):
        s = OnboardStatus(
            store_id="s1",
            verdict="needs_attention",
            onboarded_age_hours=48.0,
            last_cycle_age_hours=None,
        )
        from engines.store_setup.onboard_status import (
            _next_action,
        )
        out = _next_action(s)
        assert "cycle schedule" in out

    def test_needs_attention_closeable_gaps_suggests_launch(
        self,
    ):
        s = OnboardStatus(
            store_id="s1",
            verdict="needs_attention",
            last_cycle_age_hours=1.0,
            launch_gaps_closeable=2,
        )
        from engines.store_setup.onboard_status import (
            _next_action,
        )
        out = _next_action(s)
        assert "shopai launch" in out

    def test_thriving_suggests_daily_brief(self):
        s = OnboardStatus(
            store_id="s1",
            verdict="thriving",
        )
        from engines.store_setup.onboard_status import (
            _next_action,
        )
        out = _next_action(s)
        assert "daily-brief" in out


class TestAuditOptIn:

    def test_audit_off_by_default_no_gap_query(self):
        sm = _fake_sm(created_at=time.time() - 7200)
        with patch(
            "engines._cycle_history.recent_runs",
            return_value=[],
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
        ) as audit_mock:
            get_onboard_status("s1", store_manager=sm)
        # Audit not invoked
        audit_mock.assert_not_called()

    def test_audit_on_populates_gap_counts(self):
        sm = _fake_sm(created_at=time.time() - 7200)
        with patch(
            "engines._cycle_history.recent_runs",
            return_value=[],
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value={
                "manual_admin_gaps": ["shop_identity"],
                "launch_closeable_gaps": [
                    "active_discounts", "curated_collections",
                ],
            },
        ):
            result = get_onboard_status(
                "s1", store_manager=sm, include_audit=True,
            )
        assert result.launch_gaps_manual == 1
        assert result.launch_gaps_closeable == 2
        assert result.launch_gaps_total == 3
