"""Tests for ``_planner_consultation_phase`` -- the
autonomous controller's read-only Phase 2c that surfaces
the capability planner's recommendation per cycle.

Lives at module level (see ``core.autonomous.controller``)
so the autonomous loop can call it once per cycle, tests can
exercise it without spinning up the full controller, and
observability dashboards see the trajectory across cycles.

Coverage:

  1. Healthy store (audit passes, no failing checks) ->
     ready_to_launch=True with empty plan_steps.
  2. Failing-audit store -> plan_steps populated with the
     capabilities the planner picked.
  3. Audit raise -> dict with error key (no exception
     propagates).
  4. Planner raise -> dict with error key.
  5. Output shape matches what the controller's
     ``cycle_result["phases"]["planner"]`` consumers
     expect.
"""
from __future__ import annotations

from unittest.mock import patch

from core.autonomous.controller import (
    _planner_consultation_phase,
)


class TestPassingAudit:

    def test_ready_store_empty_plan(self):
        audit_result = {
            "checks": [
                {"key": "legal_policies", "ok": True,
                 "applied": 5, "expected": 5,
                 "missing": [], "fix_hint": ""},
            ],
            "ready_to_launch": True,
            "completion_pct": 100,
            "missing_summary": "all checks passed",
            "next_action": "",
        }
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=audit_result,
        ):
            result = _planner_consultation_phase("store-a")
        assert result["ready_to_launch"] is True
        assert result["completion_pct"] == 100
        # Passing audit -> no failing keys -> planner emits
        # empty plan (no steps)
        assert result["plan_steps"] == []
        assert result["next_action"] == ""


class TestFailingAudit:

    def test_failing_audit_surfaces_plan(self):
        audit_result = {
            "checks": [
                {"key": "legal_policies", "ok": False,
                 "applied": 0, "expected": 5,
                 "missing": ["REFUND_POLICY"],
                 "fix_hint": "Run: shopai launch ..."},
                {"key": "active_products", "ok": False,
                 "applied": 0, "expected": 1,
                 "missing": ["need 1 more"],
                 "fix_hint": "..."},
            ],
            "ready_to_launch": False,
            "completion_pct": 30,
            "missing_summary": "...",
            "next_action": (
                "shopai launch --store-name <NAME> "
                "--niche <NICHE> --seed-products"
            ),
        }
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=audit_result,
        ):
            result = _planner_consultation_phase("store-a")
        assert result["ready_to_launch"] is False
        assert result["completion_pct"] == 30
        # Failing checks routed into planner -> launch_store
        # orchestrator covers both -> plan_steps not empty
        assert len(result["plan_steps"]) > 0
        assert "launch_store" in result["plan_steps"]
        # next_action passes through from the audit
        assert "shopai launch" in result["next_action"]
        # CLI sequence has at least the orchestrator command
        assert any(
            "shopai launch" in c
            for c in result["cli_sequence"]
        )


class TestErrorPaths:

    def test_audit_raise_returns_error_dict(self):
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            side_effect=RuntimeError("network blip"),
        ):
            result = _planner_consultation_phase("store-a")
        assert "error" in result
        assert "audit_failed" in result["error"]
        assert "network blip" in result["error"]

    def test_planner_raise_returns_error_dict(self):
        audit_result = {
            "checks": [
                {"key": "legal_policies", "ok": False,
                 "applied": 0, "expected": 5,
                 "missing": [], "fix_hint": ""},
            ],
            "ready_to_launch": False,
            "completion_pct": 50,
            "missing_summary": "",
            "next_action": "",
        }
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=audit_result,
        ), patch(
            "core.capability_planner.plan_for_audit_gaps",
            side_effect=RuntimeError("planner broke"),
        ):
            result = _planner_consultation_phase("store-a")
        assert "error" in result
        assert "planner_failed" in result["error"]

    def test_no_exception_propagates(self):
        """No raise from the helper -- always returns a dict
        with either the plan fields OR an error key."""
        # Trigger import-time path by patching at the module
        # location the helper imports from.
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            side_effect=RuntimeError("oops"),
        ):
            result = _planner_consultation_phase("any-id")
        # No raise, just an error dict
        assert isinstance(result, dict)


class TestOutputShape:

    def test_keys_match_consumer_contract(self):
        """Lock in the dict shape -- consumers
        (cycle_result, daily-brief future, controller
        observability) read these keys."""
        audit_result = {
            "checks": [],
            "ready_to_launch": True,
            "completion_pct": 100,
            "missing_summary": "",
            "next_action": "",
        }
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=audit_result,
        ):
            result = _planner_consultation_phase("any-id")
        # Required keys -- consumers may break if these drift
        assert "ready_to_launch" in result
        assert "completion_pct" in result
        assert "next_action" in result
        assert "plan_steps" in result
        assert "cli_sequence" in result
