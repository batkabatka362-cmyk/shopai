"""Tests for core.mentality (Values + BeliefStore) and its
integration with :class:`core.judgment.judgment_advisor.JudgmentAdvisor`.

Covers:

* Values defaults, overrides, and validation
* Values.score — weighted-sum utility
* Values.check_multiplier — principle-to-check mapping
* Values.effective_check_weight — clamped multiplier application
* JudgmentAdvisor.evaluate honours Values by re-weighting checks
* JudgmentAdvisor.update_belief / get_belief_mean / get_belief_interval
* BeliefStore: prior, observations, mean, credible interval, reset,
  snapshot

None of these tests touch the network; the advisor's 6 checks are
pure-Python and the Values/BeliefStore types are in-memory.
"""
from __future__ import annotations

import pytest

from core.judgment.judgment_advisor import JudgmentAdvisor
from core.mentality import BeliefStore, Values


# ---------------------------------------------------------------------------
# Values: construction + validation
# ---------------------------------------------------------------------------


def test_values_defaults():
    v = Values()
    assert v.weight("safety") > v.weight("speed")
    assert v.weight("reliability") > 1.0
    # Unknown principle is neutral
    assert v.weight("unknown_principle") == 1.0


def test_values_overrides_merge_onto_defaults():
    v = Values.from_kwargs(safety=3.0, speed=0.2)
    assert v.weight("safety") == 3.0
    assert v.weight("speed") == 0.2
    # Unspecified principles keep defaults
    assert v.weight("reliability") > 0


def test_values_rejects_negative_weights():
    with pytest.raises(ValueError, match="non-negative"):
        Values(principles={"safety": -1.0})


def test_values_rejects_non_numeric():
    with pytest.raises(ValueError, match="must be numeric"):
        Values(principles={"safety": "high"})  # type: ignore[dict-item]


# ---------------------------------------------------------------------------
# Values: scoring
# ---------------------------------------------------------------------------


def test_values_score_favours_high_safety_with_high_safety_weight():
    v = Values.from_kwargs(safety=3.0, speed=0.5)
    safer = {"safety": 0.9, "speed": 0.2}
    faster = {"safety": 0.3, "speed": 0.9}
    assert v.score(safer) > v.score(faster)


def test_values_score_favours_speed_when_speed_is_primary():
    v = Values.from_kwargs(
        safety=0.3, reliability=0.3, long_term=0.3,
        short_term=0.3, automation=0.3, speed=3.0,
    )
    safer = {"safety": 0.9, "speed": 0.2}
    faster = {"safety": 0.3, "speed": 0.9}
    assert v.score(faster) > v.score(safer)


def test_values_score_ignores_unknown_keys():
    v = Values()
    scored = v.score({"safety": 0.5, "junk_key": 999})
    assert 0.0 <= scored <= 1.0


def test_values_score_zero_when_no_matching_principles():
    v = Values()
    assert v.score({}) == 0.0
    assert v.score({"unknown": 1.0}) == 0.0


# ---------------------------------------------------------------------------
# Values: check_multiplier / effective_check_weight
# ---------------------------------------------------------------------------


def test_check_multiplier_known_check():
    v = Values.from_kwargs(safety=2.0, reliability=1.0)
    # past_failures advances (safety, reliability, long_term)
    # mean of (2.0, 1.0, 1.2) = 1.4
    m = v.check_multiplier("past_failures")
    assert m == pytest.approx((2.0 + 1.0 + 1.2) / 3, rel=1e-6)


def test_check_multiplier_unknown_check_is_neutral():
    v = Values.from_kwargs(safety=5.0)
    assert v.check_multiplier("totally_new_check") == 1.0


def test_effective_check_weight_clamped():
    v = Values.from_kwargs(safety=100.0, reliability=100.0, long_term=100.0)
    # Base 0.25 * mean(100, 100, 100) = 25.0, clamped to 5.0
    effective = v.effective_check_weight("past_failures", 0.25)
    assert effective == 5.0


def test_effective_check_weight_min_clamp():
    v = Values.from_kwargs(safety=0.0, reliability=0.0, long_term=0.0)
    # Base 0.25 * 0 = 0, clamped to 0.02
    effective = v.effective_check_weight("past_failures", 0.25)
    assert effective == 0.02


# ---------------------------------------------------------------------------
# JudgmentAdvisor: Values integration
# ---------------------------------------------------------------------------


def _base_decision() -> dict:
    return {
        "action":           "launch ad campaign",
        "confidence_score": 30,  # low confidence → high magnitude risk
        "options_evaluated": 1,
    }


def _base_situation() -> dict:
    return {
        "financial":   {"health_grade": "B", "critical_alerts": 0},
        "health":      {"overall_grade": "B"},
        "inventory":   {},
        "customers":   {},
        "competitive": {},
        "events":      [],
    }


def test_advisor_no_values_matches_legacy_behaviour():
    advisor = JudgmentAdvisor()
    result = advisor.evaluate(_base_decision(), _base_situation())
    # baseline weights sum to 1.0 → risk_score is ~0.16
    # (0.8 magnitude risk * 0.20 weight / 1.0 total)
    assert 0.10 <= result["risk_score"] <= 0.25
    # Checks should not carry a 'base_weight' field when values
    # isn't supplied — that field is only added by the multiplier
    # path.
    for c in result["checks"]:
        assert "base_weight" not in c


def test_advisor_safety_heavy_values_increase_risk_score():
    baseline = JudgmentAdvisor().evaluate(
        _base_decision(), _base_situation(),
    )
    safety_values = Values.from_kwargs(
        safety=5.0, reliability=5.0, speed=0.1, short_term=0.1,
    )
    advisor = JudgmentAdvisor(values=safety_values)
    weighted = advisor.evaluate(_base_decision(), _base_situation())

    # Safety-heavy values should amplify magnitude / past_failures /
    # system_stability — because the only non-zero risk here is
    # magnitude (0.8), bumping its multiplier has to raise the
    # weighted average.
    assert weighted["risk_score"] > baseline["risk_score"]

    # Checks should now carry a 'base_weight' snapshot so the audit
    # trail can distinguish original from effective weights.
    for c in weighted["checks"]:
        assert "base_weight" in c


def test_advisor_speed_heavy_values_lower_risk_score():
    baseline = JudgmentAdvisor().evaluate(
        _base_decision(), _base_situation(),
    )
    speed_values = Values.from_kwargs(
        safety=0.1, reliability=0.1, long_term=0.1,
        short_term=2.0, speed=5.0, automation=2.0,
    )
    advisor = JudgmentAdvisor(values=speed_values)
    weighted = advisor.evaluate(_base_decision(), _base_situation())

    # Dampening safety/reliability on a case where the only risky
    # check is magnitude (advances safety+reliability) must reduce
    # the weighted risk score.
    assert weighted["risk_score"] < baseline["risk_score"]


# ---------------------------------------------------------------------------
# BeliefStore: core semantics
# ---------------------------------------------------------------------------


def test_belief_store_prior_mean_is_half():
    store = BeliefStore()
    assert store.mean("never_seen") == 0.5


def test_belief_store_single_success_nudges_mean_up():
    store = BeliefStore()
    belief = store.observe("k", True)
    assert belief.mean > 0.5
    assert belief.n == 1


def test_belief_store_converges_with_many_observations():
    store = BeliefStore()
    for _ in range(80):
        store.observe("coin", True)
    for _ in range(20):
        store.observe("coin", False)
    assert 0.75 <= store.mean("coin") <= 0.82


def test_belief_store_credible_interval_shrinks_with_data():
    store = BeliefStore()
    for _ in range(5):
        store.observe("k", True)
    wide_lo, wide_hi = store.credible_interval_95("k")
    for _ in range(200):
        store.observe("k", True)
    narrow_lo, narrow_hi = store.credible_interval_95("k")
    assert (narrow_hi - narrow_lo) < (wide_hi - wide_lo)


def test_belief_store_small_n_returns_wide_interval():
    store = BeliefStore()
    store.observe("k", True)
    lo, hi = store.credible_interval_95("k")
    assert (lo, hi) == (0.0, 1.0)


def test_belief_store_unknown_key_wide_interval():
    store = BeliefStore()
    assert store.credible_interval_95("nothing") == (0.0, 1.0)


def test_belief_store_reset_one_key():
    store = BeliefStore()
    store.observe("a", True)
    store.observe("b", True)
    store.reset("a")
    assert "a" not in store.keys()
    assert "b" in store.keys()


def test_belief_store_reset_all():
    store = BeliefStore()
    store.observe("a", True)
    store.observe("b", True)
    store.reset()
    assert store.keys() == []


def test_belief_store_snapshot_structure():
    store = BeliefStore()
    store.observe("x", True)
    store.observe("x", False)
    snap = store.snapshot()
    assert "x" in snap
    # Wave 6 #12 added ``last_updated_at`` to every snapshot row.
    assert set(snap["x"].keys()) == {
        "alpha", "beta", "mean", "n", "last_updated_at",
    }


def test_belief_store_weighted_observations():
    store = BeliefStore()
    store.observe("k", True, weight=5.0)
    belief = store.get("k")
    assert belief is not None
    # prior 1 + 5 success-credit = 6
    assert belief.alpha == 6.0
    assert belief.beta == 1.0


def test_belief_store_rejects_bad_prior():
    with pytest.raises(ValueError):
        BeliefStore(prior_alpha=0.0, prior_beta=1.0)


def test_belief_store_rejects_negative_weight():
    store = BeliefStore()
    with pytest.raises(ValueError):
        store.observe("k", True, weight=-1.0)


# ---------------------------------------------------------------------------
# JudgmentAdvisor: belief accessors
# ---------------------------------------------------------------------------


def test_advisor_update_belief_creates_and_returns_snapshot():
    advisor = JudgmentAdvisor()
    snap = advisor.update_belief("price_cut::p123", True)
    assert snap is not None
    assert snap["alpha"] == 2.0
    assert snap["beta"] == 1.0
    assert snap["mean"] > 0.5


def test_advisor_get_belief_mean_default():
    advisor = JudgmentAdvisor()
    assert advisor.get_belief_mean("never_touched") == 0.5


def test_advisor_get_belief_mean_reflects_updates():
    advisor = JudgmentAdvisor()
    for _ in range(30):
        advisor.update_belief("k", True)
    for _ in range(5):
        advisor.update_belief("k", False)
    mean = advisor.get_belief_mean("k")
    assert mean > 0.8


def test_advisor_belief_interval():
    advisor = JudgmentAdvisor()
    for _ in range(30):
        advisor.update_belief("k", True)
    lo, hi = advisor.get_belief_interval("k")
    assert 0.0 <= lo <= hi <= 1.0


def test_advisor_explicit_belief_store_injection():
    shared = BeliefStore()
    shared.observe("pre_seeded", True)
    advisor = JudgmentAdvisor(belief_store=shared)
    # The advisor sees the pre-seeded belief
    assert advisor.get_belief_mean("pre_seeded") > 0.5
