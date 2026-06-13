"""Tests for engines.fleet_intervention_alerts — W963-40."""
from __future__ import annotations

from unittest.mock import patch

from engines.fleet_intervention_alerts import (
    FleetInterventionAlertsEngine,
)
from engines.fleet_intervention_alerts.alerter import (
    InterventionAlert,
    InterventionReport,
    collect_interventions,
)


def _fake_anomaly_result(alerts=None):
    return {
        "status": "success",
        "data": {"alerts": alerts or []},
        "meta": {}, "error": None,
    }


def _fake_strategist_result(intervene=None):
    return {
        "status": "success",
        "data": {
            "by_bucket": {
                "intervene_now": intervene or [],
                "cold_start": [],
                "active": [],
                "quiet": [],
            },
        },
        "meta": {}, "error": None,
    }


# ── collect_interventions ────────────────────────────────


class TestCollectInterventions:
    def test_no_signals(self):
        with patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_anomaly_alerts",
            return_value=[],
        ), patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_fleet_strategist_intervene",
            return_value=[],
        ), patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_autonomy_paused_per_store",
            return_value=[],
        ), patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_fleet_emergency_marker",
            return_value=[],
        ):
            r = collect_interventions()
        assert r.total_signals_scanned == 0
        assert r.alerts == []

    def test_aggregates_multiple_sources(self):
        anomaly = InterventionAlert(
            store_id="s1", signal="anomaly",
            severity="critical", headline="rev down",
            severity_score=4.0,
        )
        strategist = InterventionAlert(
            store_id="s2", signal="strategist_intervene",
            severity="high", headline="fix it",
            severity_score=2.5,
        )
        with patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_anomaly_alerts",
            return_value=[anomaly],
        ), patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_fleet_strategist_intervene",
            return_value=[strategist],
        ), patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_autonomy_paused_per_store",
            return_value=[],
        ), patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_fleet_emergency_marker",
            return_value=[],
        ):
            r = collect_interventions()
        assert r.total_signals_scanned == 2
        # Sorted by severity_score desc
        assert r.alerts[0].store_id == "s1"
        assert r.alerts[1].store_id == "s2"

    def test_severity_counts(self):
        critical = InterventionAlert(
            store_id="a", signal="x",
            severity="critical", headline="x",
            severity_score=5.0,
        )
        high = InterventionAlert(
            store_id="b", signal="x",
            severity="high", headline="x",
            severity_score=2.0,
        )
        medium = InterventionAlert(
            store_id="c", signal="x",
            severity="medium", headline="x",
            severity_score=1.0,
        )
        with patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_anomaly_alerts",
            return_value=[critical, high, medium],
        ), patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_fleet_strategist_intervene",
            return_value=[],
        ), patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_autonomy_paused_per_store",
            return_value=[],
        ), patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_fleet_emergency_marker",
            return_value=[],
        ):
            r = collect_interventions()
        assert r.critical_count == 1
        assert r.high_count == 1
        assert r.medium_count == 1

    def test_by_store_groups(self):
        a1 = InterventionAlert(
            store_id="s1", signal="x",
            severity="high", headline="a", severity_score=2,
        )
        a2 = InterventionAlert(
            store_id="s1", signal="y",
            severity="critical", headline="b",
            severity_score=4,
        )
        with patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_anomaly_alerts",
            return_value=[a1, a2],
        ), patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_fleet_strategist_intervene",
            return_value=[],
        ), patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_autonomy_paused_per_store",
            return_value=[],
        ), patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_fleet_emergency_marker",
            return_value=[],
        ):
            r = collect_interventions()
        assert "s1" in r.by_store
        assert len(r.by_store["s1"]) == 2

    def test_emergency_marker_top_of_list(self):
        emergency = InterventionAlert(
            store_id="*fleet*", signal="fleet_emergency",
            severity="critical", headline="HALTED",
            severity_score=10.0,
        )
        regular = InterventionAlert(
            store_id="s1", signal="anomaly",
            severity="critical", headline="rev",
            severity_score=4.0,
        )
        with patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_anomaly_alerts",
            return_value=[regular],
        ), patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_fleet_strategist_intervene",
            return_value=[],
        ), patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_autonomy_paused_per_store",
            return_value=[],
        ), patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_fleet_emergency_marker",
            return_value=[emergency],
        ):
            r = collect_interventions()
        # Emergency always tops the list
        assert r.alerts[0].store_id == "*fleet*"

    def test_collector_failure_isolated(self):
        # If anomaly collector returns no alerts (due to
        # internal exception), the rest still work.
        with patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_anomaly_alerts",
            return_value=[],
        ), patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_fleet_strategist_intervene",
            return_value=[
                InterventionAlert(
                    store_id="s1", signal="x",
                    severity="high",
                    headline="ok",
                    severity_score=2,
                ),
            ],
        ), patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_autonomy_paused_per_store",
            return_value=[],
        ), patch(
            "engines.fleet_intervention_alerts.alerter."
            "_collect_fleet_emergency_marker",
            return_value=[],
        ):
            r = collect_interventions()
        assert r.total_signals_scanned == 1


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = FleetInterventionAlertsEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = FleetInterventionAlertsEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = FleetInterventionAlertsEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = FleetInterventionAlertsEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = FleetInterventionAlertsEngine().run({})
        assert (
            r["meta"]["engine"]
            == "fleet_intervention_alerts"
        )


class TestEngineActions:
    def test_top_filter_threaded(self):
        # Patch at flow.py import site since the function was
        # imported via `from .alerter import ...`
        with patch(
            "engines.fleet_intervention_alerts.flow."
            "collect_interventions",
        ) as mock:
            mock.return_value = InterventionReport(
                total_signals_scanned=5,
                critical_count=5,
                alerts=[
                    InterventionAlert(
                        store_id=f"s{i}", signal="x",
                        severity="critical",
                        headline="x",
                        severity_score=10 - i,
                    )
                    for i in range(5)
                ],
            )
            r = FleetInterventionAlertsEngine().run({
                "data": {"top": 2},
            })
        assert len(r["data"]["alerts"]) == 2

    def test_invalid_top_falls_back(self):
        r = FleetInterventionAlertsEngine().run({
            "data": {"top": "abc"},
        })
        assert r["status"] == "success"

    def test_no_signals_next_action(self):
        r = FleetInterventionAlertsEngine().run({})
        # On a quiet real fleet
        if r["data"]["total_signals_scanned"] == 0:
            assert (
                "Fleet is quiet" in r["data"]["next_action"]
            )
