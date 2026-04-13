"""Wave 6 #3: belief-informed past-success check in JudgmentAdvisor.

Wave 6 #2 wired every executed action into the advisor's belief
store via ``_update_beliefs_from_execution``, but no check in
``evaluate`` ever read from it — the posterior was write-only.

Wave 6 #3 closes the loop by adding
``_check_belief_posterior`` to the evaluate pipeline. The check:

1. Builds the same key format Wave 6 #2 writes
   (``"<target>::<action_type>"``)
2. Stays silent (``weight=0``) until at least
   ``_BELIEF_MIN_OBSERVATIONS`` outcomes are recorded, so
   historical decisions with no prior data see zero delta
3. Once evidence exists, risk scales linearly with
   ``1 - posterior_mean`` and the standard 0.15 weight

These tests drive the check directly and through
:meth:`JudgmentAdvisor.evaluate` so we verify both the unit
contract and the aggregate effect on the gate.
"""
from __future__ import annotations

import pytest

from core.judgment.judgment_advisor import JudgmentAdvisor
from core.mentality import BeliefStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def advisor() -> JudgmentAdvisor:
    """Advisor with a fresh, isolated belief store."""
    return JudgmentAdvisor(belief_store=BeliefStore())


def _neutral_situation() -> dict:
    """Situation that keeps every OTHER check at risk=0 so we can
    isolate the belief check's contribution to the aggregate."""
    return {
        "financial":   {"health_grade": "A", "critical_alerts": 0},
        "health":      {"overall_grade": "A"},
        "competitive": {"alerts": []},
        "customers":   {"churn_risk_pct": 0},
        "inventory":   {"stockout_risk": False},
        "events":      [],
    }


def _decision(target: str = "shopify", action_type: str = "pricing.update") -> dict:
    """Minimal decision dict that the belief check can key on and
    that scores cleanly on every other check."""
    return {
        "action":            "adjust pricing",
        "confidence_score":  85,
        "options_evaluated": 4,
        "target":            target,
        "action_type":       action_type,
    }


def _seed(advisor: JudgmentAdvisor, key: str, successes: int, failures: int) -> None:
    for _ in range(successes):
        advisor.update_belief(key, True)
    for _ in range(failures):
        advisor.update_belief(key, False)


# ---------------------------------------------------------------------------
# Unit tests against _check_belief_posterior directly
# ---------------------------------------------------------------------------


def test_no_belief_store_silent(advisor):
    advisor._beliefs = None
    out = advisor._check_belief_posterior(_decision())
    assert out["risk"] == 0.0
    assert out["weight"] == 0.0
    assert "No belief store" in out["reason"]


def test_no_prior_outcomes_silent(advisor):
    out = advisor._check_belief_posterior(_decision())
    assert out["risk"] == 0.0
    assert out["weight"] == 0.0
    assert "No prior outcomes" in out["reason"]
    assert "shopify::pricing.update" in out["reason"]


def test_insufficient_history_silent(advisor):
    # Only 2 observations — below the 3 threshold
    _seed(advisor, "shopify::pricing.update", successes=0, failures=2)
    out = advisor._check_belief_posterior(_decision())
    assert out["risk"] == 0.0
    assert out["weight"] == 0.0
    assert "Insufficient history" in out["reason"]
    assert "n=2" in out["reason"]


def test_key_format_matches_wave_6_two_writer(advisor):
    """The key the check reads must match what
    ``_update_beliefs_from_execution`` writes."""
    _seed(advisor, "warehouse::inventory.reorder", successes=5, failures=0)
    out = advisor._check_belief_posterior(_decision(
        target="warehouse", action_type="inventory.reorder",
    ))
    assert out["weight"] == 0.15
    # Perfect observed run with a uniform prior still leaves a
    # small amount of residual uncertainty — mean = 6/7 ≈ 0.857,
    # so risk ≈ 0.143 — but well below the recommendation bar.
    assert out["risk"] < 0.20
    assert "warehouse::inventory.reorder" in out["reason"]


def test_low_posterior_raises_risk(advisor):
    # 1 success, 5 failures → posterior mean ≈ (1+1)/(6+2) = 0.25
    _seed(advisor, "shopify::pricing.update", successes=1, failures=5)
    out = advisor._check_belief_posterior(_decision())
    assert out["weight"] == 0.15
    # risk = 1 - 0.25 = 0.75
    assert 0.70 <= out["risk"] <= 0.80
    # Recommendation fires when risk >= 0.5
    assert out["recommendation"]
    assert "consider a safer alternative" in out["recommendation"]


def test_high_posterior_lowers_risk(advisor):
    # 8 successes, 0 failures → mean = 9/10 = 0.9
    _seed(advisor, "shopify::pricing.update", successes=8, failures=0)
    out = advisor._check_belief_posterior(_decision())
    assert out["weight"] == 0.15
    assert out["risk"] <= 0.15
    assert not out["recommendation"]


def test_balanced_posterior_is_mid_risk(advisor):
    # 3 successes, 3 failures → mean = 4/8 = 0.5 → risk = 0.5
    _seed(advisor, "shopify::pricing.update", successes=3, failures=3)
    out = advisor._check_belief_posterior(_decision())
    assert out["weight"] == 0.15
    assert 0.45 <= out["risk"] <= 0.55


def test_missing_target_falls_back_to_unknown(advisor):
    _seed(advisor, "unknown::pricing.update", successes=0, failures=4)
    out = advisor._check_belief_posterior({
        "action": "x", "action_type": "pricing.update",
    })
    assert out["weight"] == 0.15
    assert out["risk"] > 0.6
    assert "unknown::pricing.update" in out["reason"]


def test_missing_action_type_falls_back_to_unknown(advisor):
    _seed(advisor, "shopify::unknown", successes=0, failures=4)
    out = advisor._check_belief_posterior({"action": "x", "target": "shopify"})
    assert out["weight"] == 0.15
    assert out["risk"] > 0.6


# ---------------------------------------------------------------------------
# Integration: check rides the full evaluate() pipeline
# ---------------------------------------------------------------------------


def test_evaluate_includes_belief_check(advisor):
    result = advisor.evaluate(_decision(), _neutral_situation())
    names = [c["check"] for c in result["checks"]]
    assert "belief_posterior" in names
    assert len(result["checks"]) == 7


def test_evaluate_with_no_history_is_noop_baseline(advisor):
    """When no beliefs are fed, risk_score must equal what the
    pre-Wave-6 gate would have produced. The belief check is
    silent (weight=0) so it contributes nothing to numerator or
    denominator."""
    result = advisor.evaluate(_decision(), _neutral_situation())
    # All 6 legacy checks return risk=0 for this decision; risk
    # score must therefore be exactly 0.
    assert result["risk_score"] == 0.0
    assert result["verdict"] == "proceed"


def test_evaluate_high_failure_posterior_bends_risk_upward(advisor):
    """A decision with a bad track record should score higher than
    the exact same decision with no history."""
    baseline = advisor.evaluate(_decision(), _neutral_situation())
    _seed(advisor, "shopify::pricing.update", successes=0, failures=10)
    tainted = advisor.evaluate(_decision(), _neutral_situation())
    assert tainted["risk_score"] > baseline["risk_score"]
    # The tainted risk should be noticeable but not catastrophic
    # (single check with 0.15 weight).
    assert tainted["risk_score"] > 0.05


def test_evaluate_strong_success_history_keeps_verdict_proceed(advisor):
    """Piling up successes should not flip the verdict — the
    check only adds risk for failures, never negative risk."""
    _seed(advisor, "shopify::pricing.update", successes=20, failures=0)
    result = advisor.evaluate(_decision(), _neutral_situation())
    assert result["verdict"] == "proceed"


def test_evaluate_crash_in_belief_check_does_not_break_gate(advisor):
    """A belief store that raises on access must be handled by
    ``_safe_check`` and not take down the whole advisor."""
    class _Boom:
        def get(self, key):  # noqa: D401
            raise RuntimeError("belief store crashed")

    advisor._beliefs = _Boom()
    result = advisor.evaluate(_decision(), _neutral_situation())
    # The belief check should be marked degraded...
    belief = next(c for c in result["checks"] if c["check"] == "belief_posterior")
    assert belief.get("degraded") is True
    # ...but the other 6 checks still ran and the gate produced a verdict.
    assert result["verdict"] in {"proceed", "delay", "escalate_to_human"}


def test_evaluate_updates_from_update_belief_are_visible(advisor):
    """End-to-end loop: feed outcomes via the public API, then
    call evaluate and confirm the risk reflects them."""
    # Simulate Wave 6 #2 feeding 5 failures
    for _ in range(5):
        advisor.update_belief("shopify::pricing.update", False)
    result = advisor.evaluate(_decision(), _neutral_situation())
    belief = next(c for c in result["checks"] if c["check"] == "belief_posterior")
    assert belief["weight"] == 0.15
    assert belief["risk"] > 0.5
    assert result["risk_score"] > 0.05


def test_default_weight_is_zero_in_check_defaults():
    """The crash-path default weight must be 0.0 so a crashing
    belief check can't suddenly penalise decisions with no
    evidence. (The degraded-ratchet still kicks in.)"""
    assert JudgmentAdvisor._CHECK_DEFAULTS["belief_posterior"] == 0.0
