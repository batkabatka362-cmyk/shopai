"""Wave 6 #10: throttled auto-decay inside the controller's
reflection hook.

Wave 6 #9 gave ``ReflectionSynthesizer`` a
``decay_stale_rules`` method but nothing actually called it.
Wave 6 #10 wires it into ``AutonomousController._run_reflection_hook``
with a throttle so decay runs at most once per
``_REFLECTION_DECAY_INTERVAL_SEC`` and retires any learned rule
whose last activity is older than ``_REFLECTION_DECAY_MAX_IDLE_SEC``.

These tests verify:

1. The decay call is throttled — two hook ticks inside the
   interval only trigger one decay call
2. After the interval elapses, the next tick does trigger
3. The env-var overrides apply
4. Retired rules surface in ``cycle_result["reflection"]["retired_rules"]``
5. Exceptions from ``decay_stale_rules`` are swallowed
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.autonomous.controller import AutonomousController
from core.reflection.synthesizer import ReflectionSynthesizer
from engines.meta_governance.policy_store import PolicyStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _CountingSynth:
    """ReflectionSynthesizer stand-in that tracks decay calls."""

    def __init__(self, retired_each_call: list[list[str]] | None = None,
                 raise_on_decay: Exception | None = None):
        self.run_calls = 0
        self.decay_calls: list[tuple[float, float]] = []
        self._retired = retired_each_call or []
        self._raise = raise_on_decay

    def run(self, records):  # noqa: ARG002 - contract
        self.run_calls += 1
        return type("R", (), {
            "patterns_promoted": 0,
            "as_dict": lambda _self=None: {},
        })()

    def decay_stale_rules(self, max_idle, *, now=None):
        self.decay_calls.append((float(max_idle), float(now or 0.0)))
        if self._raise is not None:
            raise self._raise
        if not self._retired:
            return []
        return self._retired.pop(0)


@pytest.fixture
def controller(tmp_path: Path):
    c = AutonomousController.__new__(AutonomousController)
    c._reflection_synth = _CountingSynth()
    c._reflection_buffer_max = 20
    c._error_buffer = None
    return c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tick(controller, now: float) -> dict[str, Any]:
    import time as _time
    original = _time.time
    try:
        _time.time = lambda: now  # type: ignore[assignment]
        cycle_result: dict[str, Any] = {"cycle_id": f"cyc-{int(now)}"}
        controller._run_reflection_hook(
            cycle_result, {"phase_a": "boom"},
        )
        return cycle_result
    finally:
        _time.time = original  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Throttle
# ---------------------------------------------------------------------------


def test_first_tick_calls_decay(controller):
    _tick(controller, now=10.0)
    assert len(controller._reflection_synth.decay_calls) == 1


def test_second_tick_within_interval_does_not_call_decay(controller):
    _tick(controller, now=10.0)
    _tick(controller, now=100.0)  # same second bucket
    assert len(controller._reflection_synth.decay_calls) == 1


def test_tick_after_interval_calls_decay_again(controller):
    _tick(controller, now=10.0)
    _tick(controller, now=10.0 + AutonomousController._REFLECTION_DECAY_INTERVAL_SEC + 1.0)
    assert len(controller._reflection_synth.decay_calls) == 2


def test_many_ticks_are_throttled_to_one_call_per_interval(controller):
    start = 1_000.0
    interval = AutonomousController._REFLECTION_DECAY_INTERVAL_SEC
    for i in range(20):
        _tick(controller, now=start + i * (interval / 10))  # 10 ticks/interval
    # 20 ticks spanning ~2 intervals → decay called ~2 times.
    assert 2 <= len(controller._reflection_synth.decay_calls) <= 3


# ---------------------------------------------------------------------------
# Env-var overrides
# ---------------------------------------------------------------------------


def test_interval_env_var_shortens_throttle(controller, monkeypatch):
    monkeypatch.setenv("SHOPAI_REFLECTION_DECAY_INTERVAL_SEC", "0")
    _tick(controller, now=1.0)
    _tick(controller, now=2.0)
    # With interval=0, every tick decays.
    assert len(controller._reflection_synth.decay_calls) == 2


def test_max_idle_env_var_is_forwarded(controller, monkeypatch):
    # Wave 7b (GAP-18): values below 60s are clamped, so use a
    # value above the floor to test env-var forwarding.
    monkeypatch.setenv("SHOPAI_REFLECTION_DECAY_MAX_IDLE_SEC", "120")
    _tick(controller, now=5.0)
    assert controller._reflection_synth.decay_calls[0][0] == 120.0


def test_max_idle_default_is_thirty_days(controller):
    _tick(controller, now=5.0)
    thirty_days = 30.0 * 24.0 * 3600.0
    assert controller._reflection_synth.decay_calls[0][0] == thirty_days


# ---------------------------------------------------------------------------
# Result plumbing
# ---------------------------------------------------------------------------


def test_retired_rules_surface_in_cycle_result(tmp_path: Path):
    c = AutonomousController.__new__(AutonomousController)
    c._reflection_synth = _CountingSynth(
        retired_each_call=[["error:stale1", "error:stale2"]],
    )
    c._reflection_buffer_max = 20
    c._error_buffer = None
    result = _tick(c, now=10.0)
    assert (
        result["reflection"]["retired_rules"]
        == ["error:stale1", "error:stale2"]
    )


def test_no_retirements_leaves_reflection_key_untouched(controller):
    result = _tick(controller, now=10.0)
    assert "reflection" not in result or "retired_rules" not in result.get(
        "reflection", {},
    )


# ---------------------------------------------------------------------------
# Fail-soft
# ---------------------------------------------------------------------------


def test_decay_exception_does_not_break_hook(tmp_path: Path):
    c = AutonomousController.__new__(AutonomousController)
    c._reflection_synth = _CountingSynth(
        raise_on_decay=RuntimeError("boom"),
    )
    c._reflection_buffer_max = 20
    c._error_buffer = None
    # Must not raise
    result = _tick(c, now=10.0)
    # Hook still updated the throttle timestamp so we don't
    # hammer a broken decay every tick.
    assert c._last_reflection_decay_at == 10.0
    # And the reflection key does not carry bogus retired_rules.
    assert result.get("reflection", {}).get("retired_rules") in (None, [])


# ---------------------------------------------------------------------------
# End-to-end with a real synthesizer + policy store
# ---------------------------------------------------------------------------


def test_e2e_decay_retires_stale_soft_rule(tmp_path: Path):
    from core.memory.quality_engine import MemoryRecord
    from engines.meta_governance.policy_store import PolicyTier

    store = PolicyStore(audit_path=str(tmp_path / "a.jsonl"))
    synth = ReflectionSynthesizer(
        policy_store=store, persist_path=tmp_path / "ledger.jsonl",
    )

    # Seed synth with one old pattern (learned 9999s ago) directly.
    synth.run([
        MemoryRecord(
            kind="error", quality=0.6, confidence=0.7,
            success_rate=0.0, usage=1, created_at=100.0,
            payload={"message": f"ancient error occurrence {i}"},
        )
        for i in range(3)
    ])
    assert len(store.list_rules(tier=PolicyTier.SOFT)) == 1

    # Now run the hook at "now" = 10_100.0 with a 1-second idle window
    # via env var, on top of the real synth.
    c = AutonomousController.__new__(AutonomousController)
    c._reflection_synth = synth
    c._reflection_buffer_max = 20
    c._error_buffer = None

    import os
    os.environ["SHOPAI_REFLECTION_DECAY_INTERVAL_SEC"] = "0"
    os.environ["SHOPAI_REFLECTION_DECAY_MAX_IDLE_SEC"] = "1"
    try:
        result = _tick(c, now=10_100.0)
    finally:
        os.environ.pop("SHOPAI_REFLECTION_DECAY_INTERVAL_SEC", None)
        os.environ.pop("SHOPAI_REFLECTION_DECAY_MAX_IDLE_SEC", None)

    # The old rule was retired by the hook's auto-decay.
    assert store.list_rules(tier=PolicyTier.SOFT) == []
    assert result["reflection"]["retired_rules"]
