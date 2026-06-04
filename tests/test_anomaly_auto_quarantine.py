"""Tests for engines.anomaly_auto_quarantine — W963-38."""
from __future__ import annotations

import os
from unittest.mock import patch

from engines.anomaly_auto_quarantine import (
    AnomalyAutoQuarantineEngine,
)
from engines.anomaly_auto_quarantine.quarantiner import (
    AnomalyQuarantineReport,
    _already_paused,
    default_pause_engines,
    run_quarantine,
)


def _alert(
    store_id="s1",
    metric="revenue_7d",
    deviation_mads=5.0,
    direction="low",
):
    return {
        "store_id": store_id,
        "metric": metric,
        "deviation_mads": deviation_mads,
        "direction": direction,
    }


# ── _already_paused ────────────────────────────────────────


class TestAlreadyPaused:
    def test_empty_state(self):
        assert _already_paused(None, "loyalty", "s1") is False

    def test_exact_tuple_match(self):
        state = frozenset([("loyalty", "s1")])
        assert _already_paused(state, "loyalty", "s1")

    def test_fleet_wide_covers_store(self):
        state = frozenset([("loyalty", None)])
        assert _already_paused(state, "loyalty", "s1")

    def test_different_engine_no_match(self):
        state = frozenset([("ads_launcher", "s1")])
        assert not _already_paused(state, "loyalty", "s1")

    def test_legacy_string_format(self):
        # Legacy format: bare engine string = fleet-wide
        state = ["loyalty"]
        assert _already_paused(state, "loyalty", "s1")


# ── default_pause_engines ─────────────────────────────────


class TestDefaultPauseEngines:
    def test_includes_writers(self):
        eng = default_pause_engines()
        assert "welcome_series" in eng
        assert "review_request" in eng


# ── run_quarantine ────────────────────────────────────────


class TestRunQuarantine:
    def test_no_alerts(self):
        with patch(
            "engines.anomaly_auto_quarantine.quarantiner."
            "_run_anomaly_scan",
            return_value=[],
        ):
            r = run_quarantine(confirmed=False)
        assert r.alerts_scanned == 0
        assert r.eligible_alerts == 0

    def test_below_threshold_skipped(self):
        a = _alert(deviation_mads=2.0)
        with patch(
            "engines.anomaly_auto_quarantine.quarantiner."
            "_load_alert_pause_set",
            return_value=None,
        ):
            r = run_quarantine(
                confirmed=False,
                min_deviation=4.0,
                alerts=[a],
            )
        assert r.eligible_alerts == 0
        assert r.skip_reasons.get("below_threshold") == 1

    def test_no_store_id_skipped(self):
        a = _alert()
        a["store_id"] = ""
        with patch(
            "engines.anomaly_auto_quarantine.quarantiner."
            "_load_alert_pause_set",
            return_value=None,
        ):
            r = run_quarantine(
                confirmed=False, alerts=[a],
            )
        assert r.skip_reasons.get("no_store_id") == 1

    def test_duplicate_store_dedupe(self):
        a1 = _alert(metric="revenue_7d")
        a2 = _alert(metric="funnel_drop_rate")
        with patch(
            "engines.anomaly_auto_quarantine.quarantiner."
            "_load_alert_pause_set",
            return_value=None,
        ):
            r = run_quarantine(
                confirmed=False, alerts=[a1, a2],
            )
        # First alert -> eligible, second alert -> duplicate
        assert r.eligible_alerts == 2  # both eligible
        assert (
            r.skip_reasons.get("duplicate_store") == 1
        )

    def test_dry_run_does_not_pause(self):
        a = _alert()
        with patch(
            "engines.anomaly_auto_quarantine.quarantiner."
            "_load_alert_pause_set",
            return_value=None,
        ), patch(
            "engines.anomaly_auto_quarantine.quarantiner."
            "_add_pause",
        ) as add_mock:
            r = run_quarantine(
                confirmed=False, alerts=[a],
            )
        assert not add_mock.called
        assert r.total_pauses_added == 0

    def test_confirmed_pauses_each_engine(self):
        a = _alert()
        with patch(
            "engines.anomaly_auto_quarantine.quarantiner."
            "_load_alert_pause_set",
            return_value=None,
        ), patch(
            "engines.anomaly_auto_quarantine.quarantiner."
            "_add_pause",
            return_value=True,
        ) as add_mock:
            r = run_quarantine(
                confirmed=True,
                alerts=[a],
                pause_engines=["X", "Y"],
            )
        assert add_mock.call_count == 2
        assert r.total_pauses_added == 2
        assert r.decisions[0].engines_paused == ["X", "Y"]

    def test_already_paused_skipped_per_engine(self):
        a = _alert()
        with patch(
            "engines.anomaly_auto_quarantine.quarantiner."
            "_load_alert_pause_set",
            return_value=frozenset([("X", "s1")]),
        ), patch(
            "engines.anomaly_auto_quarantine.quarantiner."
            "_add_pause",
            return_value=True,
        ) as add_mock:
            r = run_quarantine(
                confirmed=True,
                alerts=[a],
                pause_engines=["X", "Y"],
            )
        # X skipped, Y added
        assert add_mock.call_count == 1
        assert r.total_pauses_added == 1
        assert (
            "X"
            in r.decisions[0].engines_skipped_existing
        )

    def test_pause_failure_does_not_halt(self):
        a = _alert()
        with patch(
            "engines.anomaly_auto_quarantine.quarantiner."
            "_load_alert_pause_set",
            return_value=None,
        ), patch(
            "engines.anomaly_auto_quarantine.quarantiner."
            "_add_pause",
            return_value=False,
        ):
            r = run_quarantine(
                confirmed=True,
                alerts=[a],
                pause_engines=["X"],
            )
        assert r.total_pauses_added == 0
        # Decision recorded even when pause fails silently
        assert len(r.decisions) == 1


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = AnomalyAutoQuarantineEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = AnomalyAutoQuarantineEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = AnomalyAutoQuarantineEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = AnomalyAutoQuarantineEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = AnomalyAutoQuarantineEngine().run({})
        assert (
            r["meta"]["engine"]
            == "anomaly_auto_quarantine"
        )


class TestEngineActions:
    def test_double_gate_blocks(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(
                "SHOPAI_ANOMALY_AUTO_QUARANTINE", None,
            )
            r = AnomalyAutoQuarantineEngine().run({
                "data": {"confirmed": True},
            })
        assert r["data"]["confirmed"] is False

    def test_both_gates_set(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_ANOMALY_AUTO_QUARANTINE": "1"},
            clear=False,
        ):
            r = AnomalyAutoQuarantineEngine().run({
                "data": {"confirmed": True},
            })
        assert r["data"]["confirmed"] is True

    def test_invalid_threshold_falls_back(self):
        r = AnomalyAutoQuarantineEngine().run({
            "data": {"min_deviation": "abc"},
        })
        assert r["data"]["min_deviation"] == 4.0

    def test_default_pause_engines_emitted(self):
        r = AnomalyAutoQuarantineEngine().run({})
        defaults = r["data"]["default_pause_engines"]
        assert "welcome_series" in defaults

    def test_custom_pause_engines_threaded(self):
        r = AnomalyAutoQuarantineEngine().run({
            "data": {"pause_engines": ["X", "Y"]},
        })
        assert r["data"]["pause_engines"] == ["X", "Y"]
