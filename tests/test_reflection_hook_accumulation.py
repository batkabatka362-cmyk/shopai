"""Wave 6 #1: cross-cycle error accumulation in the reflection hook.

Wave 2 #5 wired a post-tick ``_run_reflection_hook`` onto the
controller but — in practice — it never promoted anything
because it only fed the synthesizer the CURRENT cycle's
``phase_errors`` dict. With ``min_occurrences=3`` the same
error had to hit three phases in one cycle, which almost never
happens — recurring errors show up once per cycle across many
cycles.

Wave 6 #1 fixes this by adding a bounded rolling buffer on the
controller. Every cycle:

1. Converts ``phase_errors`` into ``MemoryRecord`` objects
2. Extends the buffer (``deque(maxlen=...)``)
3. Mines the FULL buffer through the synthesizer

The synthesizer's own ``_promoted`` ledger prevents duplicate
promotions, so running over the growing buffer is idempotent.

These tests drive ``_run_reflection_hook`` directly on a bare
:class:`AutonomousController` instance (via ``__new__``) so we
don't need the full boot path to verify buffer behaviour.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.autonomous.controller import AutonomousController
from core.reflection.synthesizer import ReflectionSynthesizer
from engines.meta_governance.policy_store import PolicyStore, PolicyTier


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def controller(tmp_path: Path):
    """Bare controller with a fresh synthesizer bound to an
    isolated PolicyStore. No initialize() — we only exercise
    ``_run_reflection_hook``.
    """
    c = AutonomousController.__new__(AutonomousController)
    # Cheap synthesizer + isolated store so tests don't pollute
    # .shopai/policy_audit.jsonl.
    store = PolicyStore(audit_path=str(tmp_path / "audit.jsonl"))
    c._reflection_synth = ReflectionSynthesizer(
        policy_store=store, min_occurrences=3,
    )
    # Shrink the rolling window so tests can fill it fast.
    c._reflection_buffer_max = 20
    c._error_buffer = None  # hook will build the deque on first tick
    return c


def _tick(c: AutonomousController, errors: dict[str, str]) -> dict[str, Any]:
    """Run the reflection hook once with the given phase_errors
    and return the cycle_result dict it mutated."""
    cycle_result: dict[str, Any] = {"cycle_id": "test"}
    c._run_reflection_hook(cycle_result, errors)
    return cycle_result


# ---------------------------------------------------------------------------
# Regression: single-cycle pattern still works
# ---------------------------------------------------------------------------


def test_single_cycle_with_three_same_errors_still_promotes(controller):
    """Three phases of the same signature in ONE cycle should
    still promote. This is the pre-Wave-6 behaviour and must
    remain intact."""
    result = _tick(controller, {
        "analysis": "payment gateway timeout on order 1",
        "decide":   "payment gateway timeout on order 2",
        "execute":  "payment gateway timeout on order 3",
    })
    assert result.get("reflection", {}).get("patterns_promoted") == 1
    assert len(controller._error_buffer) == 3


# ---------------------------------------------------------------------------
# The headline fix: cross-cycle accumulation promotes
# ---------------------------------------------------------------------------


def test_cross_cycle_accumulation_promotes_after_three_cycles(controller):
    """Three cycles, each with ONE matching error — the Wave 2 #5
    version would never promote this. With the rolling buffer,
    cycle 3 crosses the threshold."""
    r1 = _tick(controller, {"analysis": "db connection refused on shard 1"})
    r2 = _tick(controller, {"analysis": "db connection refused on shard 2"})
    r3 = _tick(controller, {"analysis": "db connection refused on shard 3"})
    assert "reflection" not in r1
    assert "reflection" not in r2
    assert r3.get("reflection", {}).get("patterns_promoted") == 1
    # Buffer holds one record per cycle
    assert len(controller._error_buffer) == 3


def test_promoted_rule_lands_in_soft_tier(controller):
    for i in range(1, 4):
        _tick(controller, {"phase": f"auth failure for user u{i}"})
    soft = controller._reflection_synth._store.list_rules(tier=PolicyTier.SOFT)
    assert len(soft) == 1
    assert soft[0].source == "learned"


# ---------------------------------------------------------------------------
# Idempotency across cycles
# ---------------------------------------------------------------------------


def test_fourth_cycle_does_not_re_promote(controller):
    for i in range(1, 4):
        _tick(controller, {"phase": f"redis timeout on key k{i}"})
    # 4th cycle: same signature again, synth already promoted
    result = _tick(controller, {"phase": "redis timeout on key k4"})
    assert "reflection" not in result
    soft = controller._reflection_synth._store.list_rules(tier=PolicyTier.SOFT)
    assert len(soft) == 1  # still one, not two


# ---------------------------------------------------------------------------
# Buffer is bounded
# ---------------------------------------------------------------------------


def test_buffer_capped_at_max(controller):
    # maxlen=20 per the fixture — push 30 unique errors
    for i in range(30):
        _tick(controller, {"phase": f"distinct error number {i}"})
    assert len(controller._error_buffer) == 20
    # Earliest records were evicted
    payloads = [rec.payload["message"] for rec in controller._error_buffer]
    assert "distinct error number 0" not in payloads
    assert "distinct error number 29" in payloads


def test_buffer_eviction_can_hide_sub_threshold_pattern(controller):
    """A pattern that only has 2 occurrences inside the rolling
    window stays un-promoted even if 5 total instances hit the
    buffer — because the first 3 get evicted by unrelated
    errors. Documents the *intended* windowing behaviour.
    """
    controller._reflection_buffer_max = 5
    controller._error_buffer = None
    # Two matching errors
    _tick(controller, {"phase": "rare pattern event 1"})
    _tick(controller, {"phase": "rare pattern event 2"})
    # Four unrelated errors — pushes the rare pattern out of the
    # window (buffer maxlen=5)
    for i in range(4):
        _tick(controller, {"phase": f"unrelated filler event {i}"})
    # Another rare-pattern error lands
    result = _tick(controller, {"phase": "rare pattern event 3"})
    # The rare pattern has only 1 instance left in the window
    assert "reflection" not in result


# ---------------------------------------------------------------------------
# Multiple distinct patterns across cycles
# ---------------------------------------------------------------------------


def test_multiple_patterns_promoted_independently_across_cycles(controller):
    # Both patterns use numeric placeholders so _normalise_for_signature
    # collapses them to the same canonical form across cycles.
    _tick(controller, {
        "a": "payment gateway timeout on order 1",
        "b": "inventory desync on sku 101",
    })
    _tick(controller, {
        "a": "payment gateway timeout on order 2",
        "b": "inventory desync on sku 202",
    })
    r3 = _tick(controller, {
        "a": "payment gateway timeout on order 3",
        "b": "inventory desync on sku 303",
    })
    assert r3["reflection"]["patterns_promoted"] == 2
    soft = controller._reflection_synth._store.list_rules(tier=PolicyTier.SOFT)
    assert len(soft) == 2


# ---------------------------------------------------------------------------
# Empty phase_errors stays a no-op
# ---------------------------------------------------------------------------


def test_empty_phase_errors_is_noop(controller):
    result = _tick(controller, {})
    assert "reflection" not in result
    # Buffer hasn't even been created yet — the early return fires
    # before deque construction.
    assert controller._error_buffer is None


def test_empty_phase_errors_does_not_flush_existing_buffer(controller):
    _tick(controller, {"phase": "slow pattern event 1"})
    _tick(controller, {"phase": "slow pattern event 2"})
    # Empty cycle — buffer should be preserved untouched
    result = _tick(controller, {})
    assert "reflection" not in result
    assert len(controller._error_buffer) == 2
    # And a subsequent matching cycle still promotes because the
    # earlier records are still in the window
    r = _tick(controller, {"phase": "slow pattern event 3"})
    assert r["reflection"]["patterns_promoted"] == 1


# ---------------------------------------------------------------------------
# Buffer lazy-init on first tick
# ---------------------------------------------------------------------------


def test_buffer_initialised_from_class_default_when_override_absent():
    c = AutonomousController.__new__(AutonomousController)
    c._reflection_synth = None  # hook will build one via get_default_store
    c._error_buffer = None
    # No _reflection_buffer_max set — should use class constant
    cycle = {"cycle_id": "test"}
    c._run_reflection_hook(cycle, {"phase": "single error"})
    from collections import deque
    assert isinstance(c._error_buffer, deque)
    assert c._error_buffer.maxlen == AutonomousController._REFLECTION_BUFFER_MAX


# ---------------------------------------------------------------------------
# Report shape on promotion
# ---------------------------------------------------------------------------


def test_promotion_report_attached_to_cycle_result(controller):
    for i in range(1, 4):
        _tick(controller, {"phase": f"ssl handshake failed host h{i}"})
    cycle = {"cycle_id": "final"}
    controller._run_reflection_hook(cycle, {
        "phase": "ssl handshake failed host h4",
    })
    # The 4th tick shouldn't re-promote (already promoted on 3rd)
    # but if we start fresh: just assert the report from cycle 3
    c2 = AutonomousController.__new__(AutonomousController)
    from pathlib import Path
    # Use a different-but-similar bare setup
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        store = PolicyStore(audit_path=str(Path(td) / "a.jsonl"))
        c2._reflection_synth = ReflectionSynthesizer(
            policy_store=store, min_occurrences=3,
        )
        c2._reflection_buffer_max = 10
        c2._error_buffer = None
        _tick(c2, {"phase": "cache miss key1"})
        _tick(c2, {"phase": "cache miss key2"})
        r = _tick(c2, {"phase": "cache miss key3"})
        ref = r["reflection"]
        assert ref["patterns_promoted"] == 1
        assert len(ref["rule_ids"]) == 1
        assert ref["rule_ids"][0].startswith("learned::")
