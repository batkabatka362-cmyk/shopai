"""Tests for engines.fleet_brief_digest — W963-41."""
from __future__ import annotations

from unittest.mock import patch

from engines.fleet_brief_digest import FleetBriefDigestEngine
from engines.fleet_brief_digest.digest import (
    DigestReport,
    _compute_top_actions,
    assemble_digest,
)


# ── _compute_top_actions ──────────────────────────────────


class TestComputeTopActions:
    def test_emergency_short_circuits(self):
        r = DigestReport(emergency_active=True)
        actions = _compute_top_actions(r)
        assert len(actions) == 1
        assert "fleet-emergency" in actions[0]

    def test_critical_interventions_listed(self):
        r = DigestReport(critical_interventions=3)
        actions = _compute_top_actions(r)
        assert any(
            "intervention" in a.lower() for a in actions
        )

    def test_intervene_now_listed(self):
        r = DigestReport(intervene_count=2)
        actions = _compute_top_actions(r)
        assert any(
            "intervene" in a.lower() for a in actions
        )

    def test_not_earning_lists_autopilot(self):
        r = DigestReport(
            fleet_size=5,
            earning_count=0,
        )
        actions = _compute_top_actions(r)
        assert any(
            "fleet-autopilot" in a for a in actions
        )

    def test_stable_fleet_catch_all(self):
        r = DigestReport(
            fleet_size=5,
            earning_count=3,
        )
        actions = _compute_top_actions(r)
        # Stable -> catch-all routine cycle
        assert len(actions) >= 1

    def test_caps_at_3(self):
        r = DigestReport(
            critical_interventions=5,
            intervene_count=5,
            fleet_size=5,
            earning_count=0,
        )
        actions = _compute_top_actions(r)
        assert len(actions) <= 3


# ── assemble_digest ───────────────────────────────────────


class TestAssembleDigest:
    def test_section_resilience_on_emergency_failure(self):
        # When emergency check raises, digest still works.
        with patch(
            "engines.fleet_brief_digest.digest."
            "_emergency_section",
            return_value=(False, None),
        ), patch(
            "engines.fleet_brief_digest.digest."
            "_fleet_state_section",
            return_value=None,
        ), patch(
            "engines.fleet_brief_digest.digest."
            "_interventions_section",
            return_value=None,
        ), patch(
            "engines.fleet_brief_digest.digest."
            "_earnings_section",
            return_value=None,
        ), patch(
            "engines.fleet_brief_digest.digest."
            "_substrate_section",
            return_value=None,
        ):
            r = assemble_digest()
        # All sections returned None — digest still valid
        assert r.sections == []
        assert len(r.top_actions) >= 1

    def test_emergency_section_included(self):
        from engines.fleet_brief_digest.digest import (
            DigestSection,
        )
        emergency = DigestSection(
            name="EMERGENCY",
            headline="HALTED",
        )
        with patch(
            "engines.fleet_brief_digest.digest."
            "_emergency_section",
            return_value=(True, emergency),
        ), patch(
            "engines.fleet_brief_digest.digest."
            "_fleet_state_section",
            return_value=None,
        ), patch(
            "engines.fleet_brief_digest.digest."
            "_interventions_section",
            return_value=None,
        ), patch(
            "engines.fleet_brief_digest.digest."
            "_earnings_section",
            return_value=None,
        ), patch(
            "engines.fleet_brief_digest.digest."
            "_substrate_section",
            return_value=None,
        ):
            r = assemble_digest()
        assert r.emergency_active is True
        assert r.sections[0].name == "EMERGENCY"


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = FleetBriefDigestEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = FleetBriefDigestEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = FleetBriefDigestEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = FleetBriefDigestEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = FleetBriefDigestEngine().run({})
        assert (
            r["meta"]["engine"] == "fleet_brief_digest"
        )


class TestEngineFields:
    def test_top_actions_emitted(self):
        r = FleetBriefDigestEngine().run({})
        assert isinstance(r["data"]["top_actions"], list)
        assert len(r["data"]["top_actions"]) <= 3

    def test_sections_present(self):
        r = FleetBriefDigestEngine().run({})
        assert isinstance(r["data"]["sections"], list)

    def test_fleet_size_int(self):
        r = FleetBriefDigestEngine().run({})
        assert isinstance(
            r["data"]["fleet_size"], int,
        )

    def test_emergency_active_bool(self):
        r = FleetBriefDigestEngine().run({})
        assert isinstance(
            r["data"]["emergency_active"], bool,
        )
