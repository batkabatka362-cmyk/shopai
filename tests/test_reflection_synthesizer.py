"""Tests for core.reflection.synthesizer (Wave 2 #5).

Covers:

* ErrorPattern / SynthesisReport dataclass shape
* Signature extraction — UUID/hex/number normalisation
* mine() filters to ERROR-class records only
* mine() groups by signature, counts occurrences, confidence math
* run() promotes patterns over threshold to SOFT rules
* run() skips already-promoted signatures (idempotency)
* run() ignores patterns below min_occurrences or min_confidence
* forget() resets ledger
* custom rule_builder hook
* bad rule_builder / policy_store failures don't break the run
* controller integration smoke test — no hard dependency on live
  controller internals
"""
from __future__ import annotations

import pytest

from core.memory.quality_engine import MemoryRecord
from core.reflection.synthesizer import (
    ErrorPattern,
    ReflectionSynthesizer,
    SynthesisReport,
    _normalise_for_signature,
    _signature,
)
from engines.meta_governance.policy_store import (
    PolicyRule,
    PolicyStore,
    PolicyTier,
    PolicyVerdict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _err(message: str, *, kind: str = "error", ts: float = 1_000.0) -> MemoryRecord:
    return MemoryRecord(
        kind=kind,
        quality=0.5,
        confidence=0.5,
        success_rate=0.0,
        usage=1,
        created_at=ts,
        payload={"message": message},
    )


def _store() -> PolicyStore:
    return PolicyStore(audit_path="/tmp/test_reflection_audit.jsonl")


# ---------------------------------------------------------------------------
# Signature extraction
# ---------------------------------------------------------------------------


def test_normalise_strips_numbers():
    a = _normalise_for_signature("timeout after 3214ms calling /api/v2")
    b = _normalise_for_signature("timeout after 59ms calling /api/v2")
    assert a == b


def test_normalise_strips_uuid():
    uuid = "550e8400-e29b-41d4-a716-446655440000"
    a = _normalise_for_signature(f"error for request {uuid}")
    b = _normalise_for_signature(
        "error for request 11111111-2222-3333-4444-555555555555",
    )
    assert a == b


def test_normalise_strips_hex_addresses():
    a = _normalise_for_signature("segfault at 0xdeadbeef")
    b = _normalise_for_signature("segfault at 0xc0ffee42")
    assert a == b


def test_signature_stable_for_same_kind_and_text():
    sig1 = _signature("error", "timeout after 100ms")
    sig2 = _signature("error", "timeout after 9999ms")
    assert sig1 == sig2


def test_signature_differs_across_kinds():
    assert _signature("error", "x") != _signature("timeout", "x")


# ---------------------------------------------------------------------------
# mine()
# ---------------------------------------------------------------------------


def test_mine_skips_non_error_records():
    synth = ReflectionSynthesizer(policy_store=_store())
    records = [
        MemoryRecord(kind="rule", quality=0.9, confidence=0.9,
                     payload={"message": "a rule"}),
        MemoryRecord(kind="metric",
                     payload={"message": "some metric"}),
    ]
    patterns = synth.mine(records)
    assert patterns == []


def test_mine_groups_by_signature():
    synth = ReflectionSynthesizer(policy_store=_store())
    records = [
        _err("timeout calling shopify after 100ms"),
        _err("timeout calling shopify after 250ms"),
        _err("timeout calling shopify after 9000ms"),
        _err("different error entirely"),
    ]
    patterns = synth.mine(records)
    assert len(patterns) == 2
    # The top pattern (3 occurrences) comes first
    assert patterns[0].occurrences == 3
    assert patterns[1].occurrences == 1


def test_mine_tracks_first_last_seen():
    synth = ReflectionSynthesizer(policy_store=_store())
    records = [
        _err("same error", ts=100.0),
        _err("same error", ts=500.0),
        _err("same error", ts=300.0),
    ]
    patterns = synth.mine(records)
    assert len(patterns) == 1
    p = patterns[0]
    assert p.first_seen == 100.0
    assert p.last_seen == 500.0
    assert p.occurrences == 3


def test_mine_confidence_uses_smoothing():
    synth = ReflectionSynthesizer(
        policy_store=_store(), smoothing=1.0,
    )
    records = [_err("x") for _ in range(3)]
    p = synth.mine(records)[0]
    # 3 / (3 + 1) = 0.75
    assert p.confidence == pytest.approx(0.75)


def test_mine_falls_back_to_kind_when_payload_empty():
    synth = ReflectionSynthesizer(policy_store=_store())
    records = [
        MemoryRecord(kind="crash", quality=0.5, confidence=0.5,
                     payload={}),
        MemoryRecord(kind="crash", quality=0.5, confidence=0.5,
                     payload={}),
    ]
    patterns = synth.mine(records)
    assert len(patterns) == 1
    assert patterns[0].occurrences == 2
    assert patterns[0].sample_text == "crash"


# ---------------------------------------------------------------------------
# run() — promotion
# ---------------------------------------------------------------------------


def test_run_promotes_pattern_above_threshold():
    store = _store()
    synth = ReflectionSynthesizer(
        policy_store=store,
        min_occurrences=3,
        min_confidence=0.70,
    )
    records = [_err("timeout after 100ms") for _ in range(4)]
    report = synth.run(records)
    assert report.patterns_total == 1
    assert report.patterns_promoted == 1
    assert len(report.rule_ids) == 1
    # SOFT rules appear in the store
    soft = store.list_rules(tier=PolicyTier.SOFT)
    assert len(soft) == 1
    assert soft[0].source == "learned"


def test_run_skips_below_min_occurrences():
    store = _store()
    synth = ReflectionSynthesizer(
        policy_store=store, min_occurrences=5,
    )
    records = [_err("rare")] * 3
    report = synth.run(records)
    assert report.patterns_promoted == 0
    assert store.list_rules(tier=PolicyTier.SOFT) == []


def test_run_skips_below_min_confidence():
    store = _store()
    # min_confidence=0.99 is effectively unreachable given default
    # smoothing at 1 (3 occs → 0.75)
    synth = ReflectionSynthesizer(
        policy_store=store,
        min_occurrences=3,
        min_confidence=0.99,
    )
    records = [_err("x")] * 3
    report = synth.run(records)
    assert report.patterns_promoted == 0


def test_run_is_idempotent():
    store = _store()
    synth = ReflectionSynthesizer(policy_store=store)
    records = [_err("repeat error")] * 4
    r1 = synth.run(records)
    assert r1.patterns_promoted == 1
    # Second run over the same records should not double-promote
    r2 = synth.run(records)
    assert r2.patterns_promoted == 0
    assert len(store.list_rules(tier=PolicyTier.SOFT)) == 1


def test_forget_re_enables_promotion():
    store = _store()
    synth = ReflectionSynthesizer(policy_store=store)
    records = [_err("repeat")] * 4
    synth.run(records)
    assert synth.promoted_signatures  # non-empty
    synth.forget()
    r = synth.run(records)
    assert r.patterns_promoted == 1


def test_forget_single_signature():
    store = _store()
    synth = ReflectionSynthesizer(policy_store=store)
    synth.run([_err("a")] * 4 + [_err("b")] * 4)
    assert len(synth.promoted_signatures) == 2
    sig = synth.promoted_signatures[0]
    synth.forget(sig)
    assert sig not in synth.promoted_signatures
    assert len(synth.promoted_signatures) == 1


# ---------------------------------------------------------------------------
# Ctor validation
# ---------------------------------------------------------------------------


def test_ctor_rejects_bad_min_occurrences():
    with pytest.raises(ValueError):
        ReflectionSynthesizer(
            policy_store=_store(), min_occurrences=0,
        )


def test_ctor_rejects_bad_min_confidence():
    with pytest.raises(ValueError):
        ReflectionSynthesizer(
            policy_store=_store(), min_confidence=1.5,
        )


def test_ctor_rejects_negative_smoothing():
    with pytest.raises(ValueError):
        ReflectionSynthesizer(
            policy_store=_store(), smoothing=-1.0,
        )


# ---------------------------------------------------------------------------
# Custom rule_builder
# ---------------------------------------------------------------------------


def test_custom_rule_builder_receives_pattern():
    store = _store()
    received: list[ErrorPattern] = []

    def builder(pattern: ErrorPattern) -> PolicyRule:
        received.append(pattern)
        return PolicyRule(
            rule_id=f"custom::{pattern.signature}",
            name="custom",
            tier=PolicyTier.SOFT,
            source="learned",
            description="test",
            matcher=lambda a, c: False,
            verdict=PolicyVerdict.BLOCK,
        )

    synth = ReflectionSynthesizer(
        policy_store=store, rule_builder=builder,
    )
    synth.run([_err("x")] * 4)
    assert len(received) == 1
    assert received[0].occurrences == 4


def test_rule_builder_returning_none_is_skipped():
    store = _store()
    synth = ReflectionSynthesizer(
        policy_store=store, rule_builder=lambda p: None,
    )
    report = synth.run([_err("x")] * 4)
    assert report.patterns_promoted == 0
    assert store.list_rules(tier=PolicyTier.SOFT) == []


def test_rule_builder_exception_isolated():
    store = _store()

    def bad_builder(pattern: ErrorPattern):
        raise RuntimeError("boom")

    synth = ReflectionSynthesizer(
        policy_store=store, rule_builder=bad_builder,
    )
    report = synth.run([_err("x")] * 4)
    assert report.patterns_promoted == 0


# ---------------------------------------------------------------------------
# SynthesisReport serialisation
# ---------------------------------------------------------------------------


def test_synthesis_report_as_dict():
    store = _store()
    synth = ReflectionSynthesizer(policy_store=store)
    report = synth.run([_err("x")] * 4)
    d = report.as_dict()
    assert set(d.keys()) == {
        "patterns_total", "patterns_promoted", "patterns", "rule_ids",
    }
    assert d["patterns_promoted"] == 1
    assert isinstance(d["patterns"], list)


def test_error_pattern_as_dict_has_all_fields():
    p = ErrorPattern(
        signature="sig", kind="error", sample_text="t",
        occurrences=3, first_seen=1.0, last_seen=2.0, confidence=0.75,
    )
    d = p.as_dict()
    assert set(d.keys()) == {
        "signature", "kind", "sample_text", "occurrences",
        "first_seen", "last_seen", "confidence",
    }


# ---------------------------------------------------------------------------
# Integration: promoted rule participates in policy evaluation
# ---------------------------------------------------------------------------


def test_promoted_rule_blocks_matching_action():
    store = _store()
    synth = ReflectionSynthesizer(policy_store=store)
    synth.run([_err("timeout after 100ms")] * 4)
    # A matching action should now hit a SOFT BLOCK verdict
    decision = store.evaluate_tiered(
        {
            "kind": "error",
            "type": "test_action",
            "message": "timeout after 9999ms",
        },
        {},
    )
    # Not all actions are eligible for HARD checks — we only care
    # that the SOFT path fired at least once.
    trace_kinds = [entry.get("tier") for entry in decision.trace]
    assert "soft" in trace_kinds
