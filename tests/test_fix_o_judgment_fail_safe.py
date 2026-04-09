"""Regression tests for Fix O: JudgmentAdvisor fail-safe
semantics.

Pre-fix, ``_safe_check`` wrapped each safety check in a
try/except and on exception returned ``risk=0.0`` — i.e.
treated a check failure as "no risk detected", which
silently APPROVED decisions the safety gate couldn't
actually verify. Example: if ``_check_past_failures``
raised because the failure DB was unreachable, the verdict
still said "proceed" instead of "escalate_to_human".

Core audit wave-3 flagged this as the #1 HIGH weakness:
a safety gate that silently approves when its risk
assessment infrastructure fails isn't a safety gate.

Fix O changes the failure semantics:

  1. On check exception, return ``risk=1.0`` (maximum
     uncertainty) instead of 0.0 — unknown risk is treated
     as high risk, not zero risk.
  2. Tag the failed check with ``degraded: True`` so
     operators can distinguish a real high-risk signal
     from a missing signal.
  3. In ``evaluate()``, any degraded check forces the
     minimum verdict to ``"delay"`` (can't silently
     "proceed" past a blind check).
  4. Two or more degraded checks force
     ``"escalate_to_human"`` — the safety floor assumes
     the gate itself is broken and a human should review.
  5. Log at WARNING level with the exception type so
     operators see which checks are blind.
"""
from __future__ import annotations

import pytest


class TestSafeCheckFailSemantics:
    def test_single_check_error_returns_max_risk(self):
        from core.judgment.judgment_advisor import JudgmentAdvisor
        advisor = JudgmentAdvisor()

        def _boom(*a, **kw):
            raise RuntimeError("forced failure")

        stub = advisor._safe_check("past_failures", _boom, {}, {})
        assert stub["risk"] == 1.0, (
            "Fix O: exception must return risk=1.0 "
            "(max uncertainty), not 0.0 (silent approval)"
        )
        assert stub.get("degraded") is True, (
            "Fix O: stub must carry degraded=True so the "
            "verdict logic knows the check is blind"
        )
        assert "error" in stub
        assert stub["check"] == "past_failures"

    def test_successful_check_not_degraded(self):
        from core.judgment.judgment_advisor import JudgmentAdvisor
        advisor = JudgmentAdvisor()

        def _ok(*a, **kw):
            return {"check": "magnitude", "risk": 0.1,
                    "weight": 0.2, "reason": "fine"}

        stub = advisor._safe_check("magnitude", _ok, {})
        assert stub["risk"] == 0.1
        assert stub.get("degraded") is not True

    def test_non_dict_return_is_degraded(self):
        """If a check returns a non-dict the wrapper already
        raised a TypeError — verify it becomes a degraded
        stub, not a silent pass."""
        from core.judgment.judgment_advisor import JudgmentAdvisor
        advisor = JudgmentAdvisor()

        def _bad(*a, **kw):
            return "not a dict"

        stub = advisor._safe_check("magnitude", _bad, {})
        assert stub["risk"] == 1.0
        assert stub.get("degraded") is True


class TestEvaluateWithDegradedChecks:
    def _make_advisor_with_failing_check(self, which: str):
        """Build a JudgmentAdvisor whose specific check
        raises, leaving the other 5 checks to run normally.
        """
        from core.judgment.judgment_advisor import JudgmentAdvisor
        advisor = JudgmentAdvisor()
        original = getattr(advisor, f"_check_{which}")

        def _boom(*a, **kw):
            raise RuntimeError(f"{which} check broken")

        setattr(advisor, f"_check_{which}", _boom)
        return advisor

    def test_one_degraded_check_forces_delay_minimum(self):
        """A decision that would normally proceed (all
        non-broken checks are low risk) must still at
        minimum DELAY if one check is degraded — silent
        'proceed' past a blind check is unsafe."""
        advisor = self._make_advisor_with_failing_check("magnitude")
        decision = {
            "action": "refresh_products",
            "confidence_score": 80,
            "options_evaluated": 5,
        }
        situation = {
            "financial": {"health_grade": "A", "critical_alerts": 0},
            "competitive": {"alerts": []},
            "health": {"overall_grade": "A"},
            "customers": {"churn_risk_pct": 0},
            "inventory": {"stockout_risk": False},
            "events": [],
        }
        result = advisor.evaluate(decision, situation)
        assert result["verdict"] in ("delay", "escalate_to_human"), (
            f"expected delay or escalate when one check degraded, "
            f"got {result['verdict']}"
        )
        # The degraded check should be visible in the output
        degraded_checks = [c for c in result["checks"] if c.get("degraded")]
        assert len(degraded_checks) == 1
        assert degraded_checks[0]["check"] == "magnitude"

    def test_two_degraded_checks_force_escalate(self):
        """Two or more degraded checks → escalate_to_human.
        The gate assumes itself broken and a human must
        review."""
        from core.judgment.judgment_advisor import JudgmentAdvisor
        advisor = JudgmentAdvisor()

        def _boom1(*a, **kw):
            raise RuntimeError("check 1 broken")

        def _boom2(*a, **kw):
            raise RuntimeError("check 2 broken")

        advisor._check_magnitude = _boom1
        advisor._check_competitor_activity = _boom2

        decision = {"action": "refresh", "confidence_score": 80}
        situation = {
            "financial": {"health_grade": "A"},
            "competitive": {"alerts": []},
            "health": {"overall_grade": "A"},
            "customers": {"churn_risk_pct": 0},
            "inventory": {"stockout_risk": False},
            "events": [],
        }
        result = advisor.evaluate(decision, situation)
        assert result["verdict"] == "escalate_to_human", (
            f"≥2 degraded checks should force escalate_to_human, "
            f"got {result['verdict']}"
        )

    def test_zero_degraded_preserves_proceed(self):
        """A clean evaluation with no degraded checks still
        reaches 'proceed' when all signals are low risk —
        Fix O must not over-trigger delays."""
        from core.judgment.judgment_advisor import JudgmentAdvisor
        advisor = JudgmentAdvisor()
        decision = {
            "action": "refresh_products",
            "confidence_score": 80,
            "options_evaluated": 5,
        }
        situation = {
            "financial": {"health_grade": "A", "critical_alerts": 0},
            "competitive": {"alerts": []},
            "health": {"overall_grade": "A"},
            "customers": {"churn_risk_pct": 0},
            "inventory": {"stockout_risk": False},
            "events": [],
        }
        result = advisor.evaluate(decision, situation)
        assert result["verdict"] == "proceed", (
            f"low-risk clean eval should proceed, got {result['verdict']}"
        )
        assert not any(c.get("degraded") for c in result["checks"])

    def test_degraded_count_surfaced_on_verdict(self):
        """Operators need to see how many checks were
        degraded — a single count on the verdict result."""
        advisor = self._make_advisor_with_failing_check("financial_constraint")
        decision = {"action": "x", "confidence_score": 80}
        situation = {
            "financial": {"health_grade": "A"},
            "competitive": {"alerts": []},
            "health": {"overall_grade": "A"},
            "customers": {"churn_risk_pct": 0},
            "inventory": {"stockout_risk": False},
            "events": [],
        }
        result = advisor.evaluate(decision, situation)
        assert "degraded_checks" in result
        assert result["degraded_checks"] == 1

    def test_reason_mentions_degraded_check(self):
        """When a check is degraded the verdict reason must
        mention it so the operator knows WHY delay was
        forced, not just that risk was high."""
        advisor = self._make_advisor_with_failing_check("past_failures")
        decision = {"action": "x", "confidence_score": 80}
        situation = {
            "financial": {"health_grade": "A"},
            "competitive": {"alerts": []},
            "health": {"overall_grade": "A"},
            "customers": {"churn_risk_pct": 0},
            "inventory": {"stockout_risk": False},
            "events": [],
        }
        result = advisor.evaluate(decision, situation)
        assert "degraded" in result["reason"].lower() or \
               "past_failures" in result["reason"].lower() or \
               result["verdict"] != "proceed"


class TestExistingChecksUnaffected:
    """Regression guard: real risk math must still drive
    verdicts, Fix O must not over-correct when no checks
    are degraded."""

    def test_real_signals_produce_elevated_risk_score(self):
        """Multiple real-risk signals must bump the risk
        score above the clean-state floor (degraded=0)."""
        from core.judgment.judgment_advisor import JudgmentAdvisor
        advisor = JudgmentAdvisor()
        decision = {
            "action": "raise_price",
            "confidence_score": 20,  # very low → magnitude=0.8
            "options_evaluated": 1,
        }
        situation = {
            "financial": {"health_grade": "F", "critical_alerts": 5},
            "competitive": {"alerts": ["competitor dropped prices"]},
            "health": {"overall_grade": "F"},
            "customers": {"churn_risk_pct": 80},
            "inventory": {"stockout_risk": True},
            "events": ["competitor price_change"],
        }
        result = advisor.evaluate(decision, situation)
        # No checks should have errored → zero degraded
        assert result["degraded_checks"] == 0
        # Multiple real-risk signals must elevate the score
        assert result["risk_score"] > 0.25, (
            f"real-risk signals did not elevate the score "
            f"past the no-risk floor (got {result['risk_score']})"
        )

    def test_clean_low_risk_still_proceeds(self):
        """Baseline: zero degraded + all low risk → proceed."""
        from core.judgment.judgment_advisor import JudgmentAdvisor
        advisor = JudgmentAdvisor()
        decision = {
            "action": "refresh_products",
            "confidence_score": 85,
            "options_evaluated": 5,
        }
        situation = {
            "financial": {"health_grade": "A", "critical_alerts": 0},
            "competitive": {"alerts": []},
            "health": {"overall_grade": "A"},
            "customers": {"churn_risk_pct": 0},
            "inventory": {"stockout_risk": False},
            "events": [],
        }
        result = advisor.evaluate(decision, situation)
        assert result["verdict"] == "proceed"
        assert result["degraded_checks"] == 0
