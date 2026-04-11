"""Meta-Intelligence Governance -- flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Activity Monitor → Rule Engine → Policy Checker →
  Risk Controller → Constraint Enforcer → Decision Validator →
  Override Handler → System Feedback → Audit Logger →
  Memory Writer → Output

Engine contract:
  Input:  {status, data: {engine, action, context}, meta, error}
  Output: {status, data: {decision, issues, risks, violations, ...}, meta, error}

ALL engine output must pass through governance — no bypass allowed.
Decisions cannot execute without validation.
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .activity_monitor import monitor_activity
from .rule_engine import check_rules
from .policy_checker import check_policies
from .risk_controller import assess_risk
from .constraint_enforcer import enforce_constraints
from .decision_validator import validate_decision
from .override_handler import handle_override
from .system_feedback import generate_feedback
from .audit_logger import log_audit_entry
from .memory_writer import write_governance_record


class MetaGovernanceEngine:
    """Meta-Intelligence Governance Engine — orchestrator only, no logic."""

    ENGINE_NAME = "meta_governance"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full governance pipeline.

        Args:
            input_payload: GovernanceInput dict.

        Returns:
            GovernanceOutput dict.
        """
        start = time.monotonic()

        # ---- Stage 0: Input validation (no mutation) ----
        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)

        if payload.get("status") == "fail":
            return self._fail(
                payload.get("error", "Upstream failure"), 0.0,
            )

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        source_engine = str(data.get("engine", "unknown"))
        action = data.get("action", {})
        context = data.get("context", {})

        if not isinstance(action, dict) or not action:
            return self._fail("Input 'data.action' must be a non-empty dict", 0.0)

        # ---- Stage 1: Activity Monitor ----
        monitor_result = monitor_activity(
            source_engine=source_engine,
            action=action,
            context=context,
        )
        if monitor_result.get("status") == "error":
            return self._fail(
                f"Activity monitor failed: {monitor_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        activity = monitor_result["activity"]

        # ---- Stage 2: Rule Engine ----
        rule_result = check_rules(
            activity=activity,
            context=context,
        )
        violations = rule_result.get("violations", [])
        has_critical_violation = rule_result.get("has_critical", False)

        # ---- Stage 3: Policy Checker ----
        policy_result = check_policies(
            activity=activity,
            context=context,
        )
        policy_checks = policy_result.get("checks", [])
        policy_failures = [c for c in policy_checks if not c.get("passed", True)]

        # ---- Stage 4: Risk Controller ----
        risk_result = assess_risk(
            activity=activity,
            context=context,
            violations=violations,
            policy_failures=policy_failures,
        )
        risks = risk_result.get("risks", [])
        risk_score = float(risk_result.get("overall_score", 0.5))
        risk_level = risk_result.get("overall_level", "medium")

        # ---- Stage 5: Constraint Enforcer ----
        constraint_result = enforce_constraints(
            activity=activity,
            context=context,
        )
        constraint_results = constraint_result.get("results", [])
        any_constraint_enforced = constraint_result.get("any_enforced", False)

        # ---- Stage 6: Decision Validator ----
        validation_result = validate_decision(
            activity=activity,
            context=context,
            risk_score=risk_score,
            violations=violations,
            constraint_enforced=any_constraint_enforced,
        )
        validation_results = validation_result.get("results", [])
        validation_passed = validation_result.get("all_passed", False)
        validation_score = float(validation_result.get("validation_score", 0.0))

        # ---- Stage 7: Override Handler ----
        override_result = handle_override(
            activity=activity,
            context=context,
            violations=violations,
            policy_failures=policy_failures,
            risk_score=risk_score,
            risk_level=risk_level,
            constraint_enforced=any_constraint_enforced,
            validation_passed=validation_passed,
            validation_score=validation_score,
        )
        override_action = override_result.get("action", "approve")
        override_needed = override_result.get("override_needed", False)
        modifications = override_result.get("modifications", {})
        suggested_fix = override_result.get("suggested_fix")

        # ---- Determine final decision ----
        decision = self._determine_decision(
            override_action=override_action,
            override_needed=override_needed,
            has_critical_violation=has_critical_violation,
            violations=violations,
            policy_failures=policy_failures,
            risk_level=risk_level,
        )

        # Map decision to output status
        if decision == "rejected":
            output_status = "rejected"
        elif decision == "modified":
            output_status = "modified"
        else:
            output_status = "approved"

        # ---- Stage 8: System Feedback ----
        feedback_result = generate_feedback(
            activity=activity,
            decision=decision,
            violations=violations,
            policy_checks=policy_checks,
            risks=risks,
            risk_score=risk_score,
            risk_level=risk_level,
            constraint_results=constraint_results,
            validation_results=validation_results,
            validation_score=validation_score,
            override_decision=override_result,
        )
        feedback = feedback_result.get("feedback", {})
        issues = feedback.get("issues", [])

        # ---- Stage 9: Audit Logger (non-fatal) ----
        elapsed = time.monotonic() - start
        _audit = log_audit_entry(
            activity=activity,
            decision=decision,
            violations=violations,
            risks=risks,
            risk_score=risk_score,
            override_applied=override_needed,
            modifications=modifications,
            elapsed_seconds=elapsed,
        )

        # ---- Stage 10: Memory Writer (non-fatal) ----
        _memory = write_governance_record(
            activity=activity,
            decision=decision,
            issues=issues,
            risks=risks,
            risk_score=risk_score,
            violations=violations,
            override_applied=override_needed,
            modifications=modifications,
            validation_score=validation_score,
            feedback=feedback,
            elapsed_seconds=elapsed,
        )

        # ---- Stage 11: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": output_status,
            "data": {
                "decision": decision,
                "issues": issues,
                "risks": risks,
                "violations": violations,
                "suggested_fix": suggested_fix,
                "override": override_needed,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    # -------------------------------------------------------------------
    # Decision determination (pure data mapping, no business logic)
    # -------------------------------------------------------------------

    def _determine_decision(
        self,
        override_action: str,
        override_needed: bool,
        has_critical_violation: bool,
        violations: list[dict[str, Any]],
        policy_failures: list[dict[str, Any]],
        risk_level: str,
    ) -> str:
        """Map all governance signals into a final decision string."""
        # Override handler already decided to reject
        if override_action == "reject":
            return "rejected"

        # Override handler decided to modify
        if override_action == "modify":
            return "modified"

        # No override but there are warnings or non-critical issues
        has_warnings = any(
            v.get("severity") == "warning" for v in violations
        )
        has_non_critical_failures = bool(policy_failures)
        elevated_risk = risk_level in ("medium", "high")

        if has_warnings or has_non_critical_failures or elevated_risk:
            return "approved_with_warning"

        return "approved"

    # -------------------------------------------------------------------
    # Error output
    # -------------------------------------------------------------------

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        """Return a standardized failure output."""
        return {
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
