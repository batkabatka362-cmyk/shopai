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


class TestAutoExecuteEligibility:
    """Phase 2c now surfaces per-step auto-execute
    eligibility based on the historical success rate
    decorated by the planner. Observability only --
    actual auto-execution is gated behind a future
    env-var opt-in (not yet shipped)."""

    def test_eligibility_block_present_in_output(self):
        audit_result = {
            "checks": [
                {"key": "legal_policies", "ok": False,
                 "applied": 0, "expected": 5,
                 "missing": [], "fix_hint": ""},
            ],
            "ready_to_launch": False,
            "completion_pct": 50,
            "missing_summary": "...",
            "next_action": "...",
        }
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=audit_result,
        ):
            result = _planner_consultation_phase(
                "store-a",
            )
        assert "auto_execute" in result
        auto = result["auto_execute"]
        # Keys consumers depend on
        assert "eligible_count" in auto
        assert "total_steps" in auto
        assert "min_sample" in auto
        assert "threshold" in auto
        assert "steps" in auto
        # Defaults applied
        assert auto["threshold"] == 0.9
        assert auto["min_sample"] == 5

    def test_no_history_means_zero_eligible(self):
        """Without historical data, every step has
        sample_size=0 -> nothing qualifies."""
        audit_result = {
            "checks": [
                {"key": "legal_policies", "ok": False,
                 "applied": 0, "expected": 5,
                 "missing": [], "fix_hint": ""},
            ],
            "ready_to_launch": False,
            "completion_pct": 50,
            "missing_summary": "...",
            "next_action": "...",
        }
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=audit_result,
        ):
            result = _planner_consultation_phase(
                "store-a",
            )
        auto = result["auto_execute"]
        assert auto["eligible_count"] == 0
        # All steps reported as ineligible
        for s in auto["steps"]:
            assert s["eligible"] is False

    def test_threshold_from_env_var(self, monkeypatch):
        """The threshold + min_sample come from env vars
        so operators can tune them without code change."""
        monkeypatch.setenv(
            "SHOPAI_AUTO_EXECUTE_THRESHOLD", "0.75",
        )
        monkeypatch.setenv(
            "SHOPAI_AUTO_EXECUTE_MIN_SAMPLE", "3",
        )
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
            result = _planner_consultation_phase(
                "any-store",
            )
        auto = result["auto_execute"]
        assert auto["threshold"] == 0.75
        assert auto["min_sample"] == 3

    def test_step_qualifies_when_history_passes_gates(self):
        """A step with historical sample_size + success
        rate above gates is marked eligible."""
        # Use direct call to _compute_auto_execute_eligibility
        # with a fabricated Plan to avoid mocking the
        # registry's actual capability lookups.
        from core.autonomous.controller import (
            _compute_auto_execute_eligibility,
        )
        from core.capability_planner.plan import (
            Plan, PlanStep,
        )
        plan = Plan(goal="x")
        plan.steps.append(PlanStep(
            capability_name="reliable_one",
            role="applier",
            description="...",
            history_sample_size=10,
            history_success_rate=0.95,
        ))
        plan.steps.append(PlanStep(
            capability_name="unreliable",
            role="applier",
            description="...",
            history_sample_size=10,
            history_success_rate=0.6,
        ))
        plan.steps.append(PlanStep(
            capability_name="sparse",
            role="applier",
            description="...",
            history_sample_size=2,
            history_success_rate=1.0,
        ))
        auto = _compute_auto_execute_eligibility(plan)
        assert auto["total_steps"] == 3
        assert auto["eligible_count"] == 1
        by_cap = {s["capability"]: s for s in auto["steps"]}
        assert by_cap["reliable_one"]["eligible"] is True
        assert by_cap["unreliable"]["eligible"] is False
        assert by_cap["sparse"]["eligible"] is False


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
