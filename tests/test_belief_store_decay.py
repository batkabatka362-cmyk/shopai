"""Wave 6 #11: exponential forgetting inside
:class:`core.mentality.BeliefStore`.

Waves 6 #2/#3/#4/#5 made the belief store load-bearing: every
action feeds the posterior and the judgment advisor reads it
before each decision. That exposed a classic issue with
beta-binomial accumulators: once ``alpha + beta`` is large, new
evidence barely moves the mean. A regime change (say a new
pricing strategy or a platform policy flip) is effectively
invisible to the gate because the old evidence drowns it out.

Wave 6 #11 adds an optional ``half_life_seconds`` to
``BeliefStore``. When set, each :meth:`observe` call first
exponentially shrinks the existing excess over the prior:

    factor = 0.5 ** (elapsed / half_life)
    alpha' = prior_alpha + (alpha - prior_alpha) * factor
    beta'  = prior_beta  + (beta  - prior_beta ) * factor

Then the new success/failure weight is added on top. The prior
itself is never decayed, so a belief can never drop below its
starting uncertainty. Decay is disabled by default so existing
deployments are unaffected.

These tests verify:

1. Backward compatibility — no decay without ``half_life_seconds``
2. Argument validation
3. First observation of a key is not decayed (no clock yet)
4. Decay shrinks excess toward the prior
5. The prior is invariant under decay
6. Decay timestamps round-trip through persistence
7. Rehydration without a timestamp is safe
8. Env-var configuration through
   :func:`get_default_belief_store`
9. Regime-change scenario — 200 failures then 30 successes under
   decay push the mean upward far faster than without decay
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.mentality import BeliefStore
from core.mentality.values import (
    Belief,
    get_default_belief_store,
    reset_default_belief_store,
    set_default_belief_store,
)


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


def test_default_construction_has_no_half_life():
    store = BeliefStore()
    assert store.half_life_seconds is None


def test_explicit_half_life_is_stored():
    store = BeliefStore(half_life_seconds=3600.0)
    assert store.half_life_seconds == 3600.0


def test_zero_half_life_rejected():
    with pytest.raises(ValueError):
        BeliefStore(half_life_seconds=0.0)


def test_negative_half_life_rejected():
    with pytest.raises(ValueError):
        BeliefStore(half_life_seconds=-1.0)


def test_non_numeric_half_life_rejected():
    with pytest.raises(ValueError):
        BeliefStore(half_life_seconds="fast")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Backward compatibility: no decay when disabled
# ---------------------------------------------------------------------------


def test_disabled_decay_preserves_legacy_math():
    store = BeliefStore()
    store.observe("k", True, now=0.0)
    store.observe("k", True, now=10_000_000.0)  # huge gap
    b = store.get("k")
    assert b is not None
    # Classic beta-binomial: prior(1,1) + 2 successes
    assert b.alpha == 3.0
    assert b.beta == 1.0


def test_disabled_decay_still_sets_last_updated_at():
    # Even with decay off, the field is populated so a later
    # config flip to enabled decay starts from a valid clock.
    store = BeliefStore()
    store.observe("k", True, now=123.0)
    b = store.get("k")
    assert b is not None
    assert b.last_updated_at == 123.0


# ---------------------------------------------------------------------------
# First observation is never decayed
# ---------------------------------------------------------------------------


def test_first_observation_uses_prior_exactly():
    store = BeliefStore(half_life_seconds=10.0)
    store.observe("fresh", True, now=1_000.0)
    b = store.get("fresh")
    assert b is not None
    # Brand new belief: prior(1,1) + 1 success
    assert b.alpha == 2.0
    assert b.beta == 1.0
    assert b.last_updated_at == 1_000.0


# ---------------------------------------------------------------------------
# Decay shrinks excess toward the prior
# ---------------------------------------------------------------------------


def test_decay_shrinks_excess_by_half_after_one_half_life():
    store = BeliefStore(half_life_seconds=100.0)
    # Build up some excess first.
    for _ in range(10):
        store.observe("k", True, now=0.0)
    b = store.get("k")
    assert b is not None
    # prior(1,1) + 10 successes  → (11, 1). Excess alpha = 10.
    assert b.alpha == 11.0
    assert b.beta == 1.0

    # Second observe exactly one half-life later should:
    #   alpha' = 1 + (11 - 1) * 0.5 = 1 + 5 = 6
    #   beta'  = 1 + (1 - 1) * 0.5  = 1
    # then + 1 success → alpha = 7, beta = 1
    store.observe("k", True, now=100.0)
    b = store.get("k")
    assert b is not None
    assert b.alpha == pytest.approx(7.0)
    assert b.beta == pytest.approx(1.0)


def test_decay_shrinks_both_sides_symmetrically():
    store = BeliefStore(half_life_seconds=50.0)
    # Mix of successes and failures → excess on both sides.
    for _ in range(4):
        store.observe("mixed", True, now=0.0)
    for _ in range(4):
        store.observe("mixed", False, now=0.0)
    b = store.get("mixed")
    assert b is not None
    assert b.alpha == 5.0
    assert b.beta == 5.0

    # Half-life later, one success:
    #   alpha' = 1 + (5 - 1) * 0.5 = 1 + 2 = 3
    #   beta'  = 1 + (5 - 1) * 0.5 = 1 + 2 = 3
    #   then + 1 success → alpha = 4, beta = 3
    store.observe("mixed", True, now=50.0)
    b = store.get("mixed")
    assert b is not None
    assert b.alpha == pytest.approx(4.0)
    assert b.beta == pytest.approx(3.0)


def test_decay_after_two_half_lives_shrinks_by_quarter():
    store = BeliefStore(half_life_seconds=10.0)
    for _ in range(8):
        store.observe("k", True, now=0.0)
    # (9, 1), excess alpha = 8
    store.observe("k", True, now=20.0)  # two half-lives → factor 0.25
    b = store.get("k")
    assert b is not None
    # alpha' = 1 + 8 * 0.25 = 3, then + 1 = 4
    assert b.alpha == pytest.approx(4.0)
    assert b.beta == pytest.approx(1.0)


def test_decay_with_no_elapsed_time_is_noop():
    store = BeliefStore(half_life_seconds=100.0)
    store.observe("k", True, now=500.0)
    store.observe("k", True, now=500.0)  # same timestamp
    b = store.get("k")
    assert b is not None
    # No decay: prior(1,1) + 2 successes
    assert b.alpha == 3.0
    assert b.beta == 1.0


def test_decay_never_drops_below_prior():
    """Even after astronomically long idle, a belief should
    asymptote to the prior, never below it."""
    store = BeliefStore(half_life_seconds=1.0)
    for _ in range(50):
        store.observe("k", True, now=0.0)
    # Huge gap — factor is effectively zero.
    store.observe("k", False, now=10_000.0)
    b = store.get("k")
    assert b is not None
    # Excess collapses → prior(1,1) + 1 failure = (1, 2)
    assert b.alpha == pytest.approx(1.0, abs=1e-9)
    assert b.beta == pytest.approx(2.0, abs=1e-9)


def test_custom_prior_is_the_decay_floor():
    store = BeliefStore(
        prior_alpha=3.0, prior_beta=2.0, half_life_seconds=1.0,
    )
    for _ in range(20):
        store.observe("k", True, now=0.0)
    store.observe("k", False, now=10_000.0)
    b = store.get("k")
    assert b is not None
    # Excess collapses to prior(3, 2) + 1 failure = (3, 3)
    assert b.alpha == pytest.approx(3.0, abs=1e-9)
    assert b.beta == pytest.approx(3.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Persistence round-trip
# ---------------------------------------------------------------------------


def test_last_updated_at_round_trips_through_disk(tmp_path: Path):
    path = tmp_path / "b.json"
    store = BeliefStore(persist_path=path, half_life_seconds=100.0)
    store.observe("k", True, now=42.0)

    raw = json.loads(path.read_text())
    assert raw["k"]["last_updated_at"] == 42.0

    # Rehydrate in a new store (same half-life).
    store2 = BeliefStore(persist_path=path, half_life_seconds=100.0)
    b = store2.get("k")
    assert b is not None
    assert b.last_updated_at == 42.0
    assert b.alpha == 2.0
    assert b.beta == 1.0


def test_rehydrated_state_decays_on_next_observe(tmp_path: Path):
    path = tmp_path / "b.json"
    store = BeliefStore(persist_path=path, half_life_seconds=10.0)
    for _ in range(10):
        store.observe("k", True, now=0.0)
    # (11, 1) on disk with last_updated_at=0.

    store2 = BeliefStore(persist_path=path, half_life_seconds=10.0)
    store2.observe("k", True, now=10.0)  # one half-life later
    b = store2.get("k")
    assert b is not None
    # alpha' = 1 + 10*0.5 = 6, + 1 success = 7
    assert b.alpha == pytest.approx(7.0)


def test_legacy_snapshot_without_last_updated_at_loads(tmp_path: Path):
    """Pre-Wave 6 #11 snapshots must still load. The missing field
    means "clock not started yet" — the first post-load observe
    simply starts the clock without decaying."""
    path = tmp_path / "b.json"
    # Hand-written legacy payload.
    path.write_text(json.dumps({
        "k": {"alpha": 11.0, "beta": 1.0},
    }))
    store = BeliefStore(persist_path=path, half_life_seconds=10.0)
    b = store.get("k")
    assert b is not None
    assert b.last_updated_at is None

    store.observe("k", True, now=10_000.0)  # huge gap
    b = store.get("k")
    assert b is not None
    # No decay on this step — clock was uninitialised.
    assert b.alpha == pytest.approx(12.0)
    assert b.beta == pytest.approx(1.0)
    # But now the timestamp is set, so the NEXT observe would decay.
    assert b.last_updated_at == 10_000.0


# ---------------------------------------------------------------------------
# Default singleton + env var
# ---------------------------------------------------------------------------


def test_env_var_enables_decay_on_default_store(
    monkeypatch, tmp_path: Path,
):
    monkeypatch.setenv("SHOPAI_BELIEFS_PATH", str(tmp_path / "b.json"))
    monkeypatch.setenv("SHOPAI_BELIEF_HALF_LIFE_SEC", "123.0")
    reset_default_belief_store()
    try:
        store = get_default_belief_store()
        assert store.half_life_seconds == 123.0
    finally:
        reset_default_belief_store()


def test_invalid_env_var_half_life_falls_back_to_disabled(
    monkeypatch, tmp_path: Path,
):
    monkeypatch.setenv("SHOPAI_BELIEFS_PATH", str(tmp_path / "b.json"))
    monkeypatch.setenv("SHOPAI_BELIEF_HALF_LIFE_SEC", "not-a-number")
    reset_default_belief_store()
    try:
        store = get_default_belief_store()
        assert store.half_life_seconds is None
    finally:
        reset_default_belief_store()


def test_non_positive_env_var_half_life_falls_back_to_disabled(
    monkeypatch, tmp_path: Path,
):
    monkeypatch.setenv("SHOPAI_BELIEFS_PATH", str(tmp_path / "b.json"))
    monkeypatch.setenv("SHOPAI_BELIEF_HALF_LIFE_SEC", "-5")
    reset_default_belief_store()
    try:
        store = get_default_belief_store()
        assert store.half_life_seconds is None
    finally:
        reset_default_belief_store()


def test_empty_env_var_half_life_disables_decay(
    monkeypatch, tmp_path: Path,
):
    monkeypatch.setenv("SHOPAI_BELIEFS_PATH", str(tmp_path / "b.json"))
    monkeypatch.setenv("SHOPAI_BELIEF_HALF_LIFE_SEC", "   ")
    reset_default_belief_store()
    try:
        store = get_default_belief_store()
        assert store.half_life_seconds is None
    finally:
        reset_default_belief_store()


def test_no_env_var_keeps_decay_disabled(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SHOPAI_BELIEFS_PATH", str(tmp_path / "b.json"))
    monkeypatch.delenv("SHOPAI_BELIEF_HALF_LIFE_SEC", raising=False)
    reset_default_belief_store()
    try:
        store = get_default_belief_store()
        assert store.half_life_seconds is None
    finally:
        reset_default_belief_store()


# ---------------------------------------------------------------------------
# Regime-change scenario
# ---------------------------------------------------------------------------


def test_decay_speeds_up_regime_change():
    """The whole point of Wave 6 #11: under heavy prior evidence
    from regime A, a flip to regime B should move the posterior
    much faster when decay is enabled than when it isn't."""
    no_decay = BeliefStore()
    decayed = BeliefStore(half_life_seconds=10.0)

    # Phase 1: 200 failures under "old regime" at t=0.
    # The wall-clock is stationary so even the decayed store
    # sees no decay here — both stores accumulate identically.
    for _ in range(200):
        no_decay.observe("strategy", False, now=0.0)
        decayed.observe("strategy", False, now=0.0)

    nd_after_p1 = no_decay.mean("strategy")
    d_after_p1 = decayed.mean("strategy")
    assert nd_after_p1 < 0.02
    assert d_after_p1 < 0.02

    # Phase 2: 30 successes 100 seconds later (= 10 half-lives for
    # the decayed store → shrink factor 2**-10 ≈ 0.001).
    for i in range(30):
        no_decay.observe("strategy", True, now=100.0 + i)
        decayed.observe("strategy", True, now=100.0 + i)

    nd_final = no_decay.mean("strategy")
    d_final = decayed.mean("strategy")

    # The no-decay store is still stuck near zero — 30 successes
    # can't fight 200 accumulated failures.
    assert nd_final < 0.20
    # The decayed store has effectively forgotten the old regime
    # by the time the first success arrived, so the mean climbs
    # well past the no-decay mean.
    assert d_final > 0.80
    # And of course: decay made a real difference.
    assert d_final > nd_final + 0.5


def test_decay_belief_has_bounded_observation_count():
    """Under decay the effective n stays bounded instead of
    growing without limit, which is what keeps the credible
    interval meaningful after a regime change."""
    store = BeliefStore(half_life_seconds=10.0)
    # Hammer the key for many "ticks", one half-life apart.
    for i in range(500):
        store.observe("k", True, now=i * 10.0)
    b = store.get("k")
    assert b is not None
    # Without decay n would be 500. With per-step halving the
    # geometric series converges: each new success adds 1 but
    # existing excess is halved, so alpha → 1 + 2 = 3 in the
    # limit (geometric sum of 1 with ratio 0.5).
    assert b.alpha < 5.0
    assert b.beta == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Decay + snapshot()
# ---------------------------------------------------------------------------


def test_snapshot_reflects_decayed_values():
    store = BeliefStore(half_life_seconds=10.0)
    for _ in range(10):
        store.observe("k", True, now=0.0)
    store.observe("k", True, now=10.0)
    snap = store.snapshot()
    assert snap["k"]["alpha"] == pytest.approx(7.0)
    assert snap["k"]["beta"] == pytest.approx(1.0)
    assert snap["k"]["mean"] == pytest.approx(7.0 / 8.0)


# ---------------------------------------------------------------------------
# Wave 6 #12: snapshot telemetry
# ---------------------------------------------------------------------------


def test_snapshot_row_carries_last_updated_at():
    store = BeliefStore(half_life_seconds=10.0)
    store.observe("k", True, now=1234.5)
    snap = store.snapshot()
    assert "last_updated_at" in snap["k"]
    assert snap["k"]["last_updated_at"] == 1234.5


def test_snapshot_row_last_updated_at_is_none_when_unset():
    """Snapshots rehydrated from a pre-Wave 6 #11 ledger have no
    timestamp — the field round-trips as None."""
    store = BeliefStore()  # decay disabled
    # Reach in and construct a legacy-shaped Belief without the field.
    b = Belief(key="legacy", alpha=3.0, beta=2.0, last_updated_at=None)
    store._beliefs["legacy"] = b  # noqa: SLF001 - test helper
    snap = store.snapshot()
    assert snap["legacy"]["last_updated_at"] is None


def test_snapshot_row_tracks_subsequent_updates():
    store = BeliefStore(half_life_seconds=100.0)
    store.observe("k", True, now=10.0)
    store.observe("k", False, now=50.0)
    assert store.snapshot()["k"]["last_updated_at"] == 50.0
