"""Tests for engines.fleet_notifier — W963-42."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from engines.fleet_notifier import FleetNotifierEngine
from engines.fleet_notifier import state as state_mod
from engines.fleet_notifier.notifier import (
    CandidateEvent,
    NotifyReport,
    default_cooldowns,
    kind_severity,
    run_notifier,
)


def _candidate(kind="fleet_emergency", scope="fleet"):
    return CandidateEvent(
        kind=kind,
        scope=scope,
        severity="critical",
        message="test event",
        context={"x": 1},
    )


# ── state module ──────────────────────────────────────────


class TestState:
    def test_empty_default_zero(self, tmp_path):
        state_mod.reset_path(tmp_path / "fn.json")
        assert state_mod.last_sent_at("x") == 0.0

    def test_pattern_j_blocks_mark(self, tmp_path):
        state_mod.reset_path(tmp_path / "fn.json")
        assert state_mod.mark_sent("x", "y") is False

    def test_pattern_j_blocks_clear(self, tmp_path):
        state_mod.reset_path(tmp_path / "fn.json")
        assert state_mod.clear_all() is False

    def test_cooldown_zero_when_never_sent(self, tmp_path):
        state_mod.reset_path(tmp_path / "fn.json")
        assert state_mod.cooldown_remaining(
            "x", 100.0,
        ) == 0.0

    def test_cooldown_remaining_computed(self, tmp_path):
        state_mod.reset_path(tmp_path / "fn.json")
        # Override the test guard so mark_sent persists
        with patch.object(
            state_mod, "_is_test_environment",
            return_value=False,
        ):
            state_mod.mark_sent("x", "", ts=100.0)
            r = state_mod.cooldown_remaining(
                "x", 60.0, now=150.0,
            )
            # elapsed=50, cooldown=60 -> remaining=10
            assert abs(r - 10.0) < 1.0


# ── default_cooldowns + kind_severity ────────────────────


class TestDefaultCooldowns:
    def test_critical_kinds_present(self):
        cd = default_cooldowns()
        assert "fleet_emergency" in cd
        assert cd["fleet_emergency"] == 86400.0

    def test_kind_severity_map(self):
        ks = kind_severity()
        assert ks["fleet_emergency"] == "critical"
        assert ks["anomaly_outlier"] == "high"


# ── run_notifier ──────────────────────────────────────────


class TestRunNotifier:
    def test_no_candidates(self):
        with patch(
            "engines.fleet_notifier.notifier."
            "_collect_emergency",
            return_value=[],
        ), patch(
            "engines.fleet_notifier.notifier."
            "_collect_interventions",
            return_value=[],
        ), patch(
            "engines.fleet_notifier.notifier."
            "_collect_anomaly_outliers",
            return_value=[],
        ), patch(
            "engines.fleet_notifier.notifier."
            "_collect_calibrator_blocked",
            return_value=[],
        ):
            r = run_notifier(confirmed=False)
        assert r.candidates_scanned == 0

    def test_dry_run_does_not_dispatch(self, tmp_path):
        state_mod.reset_path(tmp_path / "fn.json")
        with patch(
            "engines.fleet_notifier.notifier."
            "_collect_emergency",
            return_value=[_candidate()],
        ), patch(
            "engines.fleet_notifier.notifier."
            "_collect_interventions",
            return_value=[],
        ), patch(
            "engines.fleet_notifier.notifier."
            "_collect_anomaly_outliers",
            return_value=[],
        ), patch(
            "engines.fleet_notifier.notifier."
            "_collect_calibrator_blocked",
            return_value=[],
        ), patch(
            "engines.fleet_notifier.notifier."
            "_dispatch_event",
        ) as disp:
            r = run_notifier(confirmed=False)
        assert r.eligible_count == 1
        assert r.sent_count == 0
        assert r.skip_reasons.get("dry_run") == 1
        assert not disp.called

    def test_cooldown_skips_event(self, tmp_path):
        state_mod.reset_path(tmp_path / "fn.json")
        with patch.object(
            state_mod, "_is_test_environment",
            return_value=False,
        ):
            state_mod.mark_sent(
                "fleet_emergency", "fleet",
            )
        with patch(
            "engines.fleet_notifier.notifier."
            "_collect_emergency",
            return_value=[_candidate()],
        ), patch(
            "engines.fleet_notifier.notifier."
            "_collect_interventions",
            return_value=[],
        ), patch(
            "engines.fleet_notifier.notifier."
            "_collect_anomaly_outliers",
            return_value=[],
        ), patch(
            "engines.fleet_notifier.notifier."
            "_collect_calibrator_blocked",
            return_value=[],
        ):
            r = run_notifier(confirmed=True)
        # Cooldown of 24h still active
        assert r.skip_reasons.get("cooldown_active") == 1

    def test_kind_filter_narrows(self, tmp_path):
        state_mod.reset_path(tmp_path / "fn.json")
        with patch(
            "engines.fleet_notifier.notifier."
            "_collect_emergency",
            return_value=[_candidate("fleet_emergency")],
        ), patch(
            "engines.fleet_notifier.notifier."
            "_collect_interventions",
            return_value=[_candidate(
                "critical_intervention", "s1",
            )],
        ), patch(
            "engines.fleet_notifier.notifier."
            "_collect_anomaly_outliers",
            return_value=[],
        ), patch(
            "engines.fleet_notifier.notifier."
            "_collect_calibrator_blocked",
            return_value=[],
        ):
            r = run_notifier(
                confirmed=False,
                kind_filter="fleet_emergency",
            )
        assert r.skip_reasons.get("kind_filter") == 1

    def test_confirmed_dispatch_marks_sent(self, tmp_path):
        state_mod.reset_path(tmp_path / "fn.json")
        with patch(
            "engines.fleet_notifier.notifier."
            "_collect_emergency",
            return_value=[_candidate()],
        ), patch(
            "engines.fleet_notifier.notifier."
            "_collect_interventions",
            return_value=[],
        ), patch(
            "engines.fleet_notifier.notifier."
            "_collect_anomaly_outliers",
            return_value=[],
        ), patch(
            "engines.fleet_notifier.notifier."
            "_collect_calibrator_blocked",
            return_value=[],
        ), patch(
            "engines.fleet_notifier.notifier."
            "_dispatch_event",
            return_value=(True, ""),
        ), patch.object(
            state_mod, "_is_test_environment",
            return_value=False,
        ):
            r = run_notifier(confirmed=True)
        assert r.sent_count == 1

    def test_dispatch_failure_captured(self, tmp_path):
        state_mod.reset_path(tmp_path / "fn.json")
        with patch(
            "engines.fleet_notifier.notifier."
            "_collect_emergency",
            return_value=[_candidate()],
        ), patch(
            "engines.fleet_notifier.notifier."
            "_collect_interventions",
            return_value=[],
        ), patch(
            "engines.fleet_notifier.notifier."
            "_collect_anomaly_outliers",
            return_value=[],
        ), patch(
            "engines.fleet_notifier.notifier."
            "_collect_calibrator_blocked",
            return_value=[],
        ), patch(
            "engines.fleet_notifier.notifier."
            "_dispatch_event",
            return_value=(False, "http_500"),
        ):
            r = run_notifier(confirmed=True)
        assert r.sent_count == 0
        assert r.skip_reasons.get("http_500") == 1


# ── _dispatch_event (HTTP) ────────────────────────────────


class TestDispatchEvent:
    def test_no_webhook_url(self):
        from engines.fleet_notifier.notifier import (
            _dispatch_event,
        )
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(
                "SHOPAI_NOTIFY_WEBHOOK_URL", None,
            )
            sent, err = _dispatch_event(_candidate())
        assert sent is False
        assert err == "no_webhook_url"

    def test_invalid_url(self):
        from engines.fleet_notifier.notifier import (
            _dispatch_event,
        )
        with patch.dict(
            os.environ,
            {"SHOPAI_NOTIFY_WEBHOOK_URL": "ftp://x"},
            clear=False,
        ):
            sent, err = _dispatch_event(_candidate())
        assert sent is False
        assert err == "invalid_webhook_url"


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = FleetNotifierEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = FleetNotifierEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = FleetNotifierEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = FleetNotifierEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = FleetNotifierEngine().run({})
        assert r["meta"]["engine"] == "fleet_notifier"


class TestEngineActions:
    def test_double_gate_blocks(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(
                "SHOPAI_FLEET_NOTIFIER_ENABLED", None,
            )
            r = FleetNotifierEngine().run({
                "data": {"confirmed": True},
            })
        assert r["data"]["confirmed"] is False

    def test_both_gates_set(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_FLEET_NOTIFIER_ENABLED": "1"},
            clear=False,
        ):
            r = FleetNotifierEngine().run({
                "data": {"confirmed": True},
            })
        assert r["data"]["confirmed"] is True

    def test_reset_path_under_pytest_skipped(self):
        # Pattern J skips clear_all under pytest
        r = FleetNotifierEngine().run({
            "data": {"reset": True},
        })
        assert r["data"]["reset_result"] == "skipped_test_env"

    def test_default_cooldowns_emitted(self):
        r = FleetNotifierEngine().run({})
        cd = r["data"]["default_cooldowns"]
        assert "fleet_emergency" in cd

    def test_webhook_url_detected(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_NOTIFY_WEBHOOK_URL": "https://x.com/wh"},
            clear=False,
        ):
            r = FleetNotifierEngine().run({})
        assert r["data"]["webhook_url_set"] is True
