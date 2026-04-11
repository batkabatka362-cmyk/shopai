"""Wave 5 #A: end-to-end learning feedback loop.

Eight subsystems shipped in Wave 2 and were integrated in Waves
3–4, but no test exercised the FULL chain as one story:

    error memory records
      → ReflectionSynthesizer.run()
      → PolicyStore.promote_soft_rule()   (learning)
      → PolicyStore.evaluate_tiered()      (application)
      → JSONL audit log                    (observability)

This file drives all five steps in one test, proving that the
in-place improvements deliver a true closed-loop learning
system: a recurring error pattern gets MINED, LEARNED as a
SOFT rule, APPLIED to a new matching action, and AUDITED.

Tests below also cover:

* Idempotency — running the synthesizer twice over the same
  errors only promotes once
* Control case — matching actions BEFORE promotion pass through
* Non-matching actions — stay unaffected by the learned rule
* Pattern signature robustness — order ids / numbers differ
  between records but the normalised signature still matches
* Audit trail fidelity — every step's decision lands in
  ``policy_audit.jsonl`` with the correct rule_id and tier
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from core.memory.quality_engine import MemoryRecord
from core.reflection.synthesizer import ReflectionSynthesizer
from engines.meta_governance.policy_store import (
    PolicyStore,
    PolicyTier,
    PolicyVerdict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _error_record(
    message: str,
    *,
    kind: str = "failure:payment_gateway",
    created_at: float | None = None,
) -> MemoryRecord:
    """Build an ERROR-classed MemoryRecord for the synthesizer.

    Uses ``tags=("error",)`` so :func:`classify` lands on
    :class:`MemoryClass.ERROR` without depending on a specific
    kind string matching the frozen ``_ERROR_KINDS`` set.
    """
    return MemoryRecord(
        kind=kind,
        quality=0.3,
        confidence=0.6,
        success_rate=0.0,
        usage=0,
        tags=("error",),
        payload={"message": message, "severity": "high"},
        created_at=created_at or time.time(),
    )


def _store_with_audit(tmp_path: Path) -> PolicyStore:
    """Build a fresh PolicyStore writing audit records under a
    temp directory so tests don't pollute ``.shopai/policy_audit.jsonl``.
    """
    audit_path = str(tmp_path / "policy_audit.jsonl")
    return PolicyStore(audit_path=audit_path)


def _read_audit(store: PolicyStore) -> list[dict[str, Any]]:
    path = store._audit_path
    if not Path(path).is_file():
        return []
    entries: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


# ---------------------------------------------------------------------------
# The main loop: errors → synth → policy → evaluate → audit
# ---------------------------------------------------------------------------


def test_full_feedback_loop(tmp_path):
    """The canonical story: recurring errors become a SOFT rule
    that blocks matching actions and writes a BLOCK audit."""
    store = _store_with_audit(tmp_path)
    synth = ReflectionSynthesizer(
        policy_store=store,
        min_occurrences=3,
        min_confidence=0.75,
    )

    # --- Step 1: seed 5 matching error records -----------------
    # Order ids differ but the normalised signature collapses
    # them so the synthesizer groups them into one pattern.
    errors = [
        _error_record("payment gateway timeout on order 12345"),
        _error_record("payment gateway timeout on order 67890"),
        _error_record("payment gateway timeout on order 11111"),
        _error_record("payment gateway timeout on order 22222"),
        _error_record("payment gateway timeout on order 33333"),
    ]

    # --- Step 2: synthesizer mines + promotes ------------------
    report = synth.run(errors)
    assert report.patterns_total == 1
    assert report.patterns_promoted == 1
    assert len(report.rule_ids) == 1
    promoted_rule_id = report.rule_ids[0]
    assert promoted_rule_id.startswith("learned::")

    # --- Step 3: rule is now in the SOFT tier ------------------
    soft_rules = store.list_rules(tier=PolicyTier.SOFT)
    assert len(soft_rules) == 1
    assert soft_rules[0].rule_id == promoted_rule_id
    assert soft_rules[0].source == "learned"

    # --- Step 4: matching action gets blocked ------------------
    decision = store.evaluate_tiered(
        {
            "kind":        "failure:payment_gateway",
            "action_type": "policy_probe",  # not in HARD batch list
            "message":     "payment gateway timeout on order 99999",
        },
    )
    assert decision.verdict == PolicyVerdict.BLOCK
    assert decision.final_tier == PolicyTier.SOFT
    assert decision.final_rule_id == promoted_rule_id
    assert decision.hard_passed is True

    # --- Step 5: audit log captured both the block and any
    # earlier HARD-only evaluations ------------------------------
    audit = _read_audit(store)
    assert audit, "audit log must contain at least one entry"
    # The most-recent entry is the block we just triggered
    last = audit[-1]
    assert last["verdict"] == PolicyVerdict.BLOCK.value
    assert last["final_rule_id"] == promoted_rule_id
    assert last["final_tier"] == PolicyTier.SOFT.value
    # Trace includes both the HARD batch and the SOFT rule match
    trace_tiers = [t.get("tier") for t in last["trace"]]
    assert PolicyTier.HARD.value in trace_tiers
    assert PolicyTier.SOFT.value in trace_tiers


# ---------------------------------------------------------------------------
# Idempotency — running twice doesn't re-promote
# ---------------------------------------------------------------------------


def test_feedback_loop_is_idempotent(tmp_path):
    store = _store_with_audit(tmp_path)
    synth = ReflectionSynthesizer(
        policy_store=store,
        min_occurrences=3,
    )
    errors = [
        _error_record(f"db connection refused on shard {i}")
        for i in range(4)
    ]
    r1 = synth.run(errors)
    r2 = synth.run(errors)
    assert r1.patterns_promoted == 1
    assert r2.patterns_promoted == 0  # ledger blocks re-promotion
    # Store only has one rule, not two
    assert len(store.list_rules(tier=PolicyTier.SOFT)) == 1
    assert len(synth.promoted_signatures) == 1


def test_forget_allows_re_promotion(tmp_path):
    store = _store_with_audit(tmp_path)
    synth = ReflectionSynthesizer(
        policy_store=store, min_occurrences=3,
    )
    errors = [_error_record(f"cache miss key{i}") for i in range(3)]
    synth.run(errors)
    assert synth.promoted_signatures  # one entry
    synth.forget()
    r = synth.run(errors)
    assert r.patterns_promoted == 1  # fresh promotion


# ---------------------------------------------------------------------------
# Control cases — actions outside the learned pattern stay unaffected
# ---------------------------------------------------------------------------


def test_non_matching_action_still_allowed_after_promotion(tmp_path):
    store = _store_with_audit(tmp_path)
    synth = ReflectionSynthesizer(policy_store=store, min_occurrences=3)
    errors = [
        _error_record(f"payment gateway timeout on order {i}")
        for i in range(3)
    ]
    synth.run(errors)

    # Completely different action: unrelated kind + message
    decision = store.evaluate_tiered({
        "kind":        "inventory_check",
        "action_type": "policy_probe",
        "message":     "stock level OK for sku HAT-001",
    })
    assert decision.verdict == PolicyVerdict.ALLOW
    assert decision.final_rule_id is None
    assert decision.final_tier is None


def test_matching_message_but_wrong_kind_still_allowed(tmp_path):
    store = _store_with_audit(tmp_path)
    synth = ReflectionSynthesizer(policy_store=store, min_occurrences=3)
    errors = [
        _error_record("checkout gateway errored on order 1"),
        _error_record("checkout gateway errored on order 2"),
        _error_record("checkout gateway errored on order 3"),
    ]
    synth.run(errors)
    # Same text but the action has a different kind
    decision = store.evaluate_tiered({
        "kind":        "different_kind",
        "action_type": "policy_probe",
        "message":     "checkout gateway errored on order 4",
    })
    assert decision.verdict == PolicyVerdict.ALLOW


def test_matching_action_before_promotion_allowed(tmp_path):
    """Sanity check: the probe action is only blocked because of
    the learned rule, not because of some HARD default."""
    store = _store_with_audit(tmp_path)
    # Don't run the synthesizer — no SOFT rule exists yet
    decision = store.evaluate_tiered({
        "kind":        "failure:payment_gateway",
        "action_type": "policy_probe",
        "message":     "payment gateway timeout on order 99999",
    })
    assert decision.verdict == PolicyVerdict.ALLOW


# ---------------------------------------------------------------------------
# Threshold semantics — below-threshold patterns are mined but not promoted
# ---------------------------------------------------------------------------


def test_sub_threshold_pattern_is_mined_but_not_promoted(tmp_path):
    store = _store_with_audit(tmp_path)
    synth = ReflectionSynthesizer(
        policy_store=store, min_occurrences=3,
    )
    errors = [
        _error_record("ssl handshake failed on host api1.example.com"),
        _error_record("ssl handshake failed on host api2.example.com"),
    ]  # only 2 — below the 3-occurrence floor
    report = synth.run(errors)
    assert report.patterns_total == 1
    assert report.patterns_promoted == 0
    assert report.rule_ids == []
    assert len(store.list_rules(tier=PolicyTier.SOFT)) == 0


def test_confidence_threshold_respected(tmp_path):
    """Even at 3 occurrences, bumping min_confidence to 0.85 with
    default smoothing=1 (conf = 3/4 = 0.75) should fail the check
    and leave the pattern un-promoted."""
    store = _store_with_audit(tmp_path)
    synth = ReflectionSynthesizer(
        policy_store=store,
        min_occurrences=3,
        min_confidence=0.85,
    )
    errors = [_error_record(f"rate limit hit on endpoint /v{i}") for i in range(3)]
    report = synth.run(errors)
    assert report.patterns_promoted == 0
    # At 5 occurrences confidence = 5/6 ≈ 0.833, still below 0.85
    errors = [_error_record(f"rate limit hit on endpoint /v{i}") for i in range(5)]
    report = synth.run(errors)
    assert report.patterns_promoted == 0
    # At 6 occurrences confidence = 6/7 ≈ 0.857, now above
    errors = [_error_record(f"rate limit hit on endpoint /v{i}") for i in range(6)]
    report = synth.run(errors)
    assert report.patterns_promoted == 1


# ---------------------------------------------------------------------------
# Multi-pattern discrimination
# ---------------------------------------------------------------------------


def test_multiple_distinct_patterns_promoted_independently(tmp_path):
    store = _store_with_audit(tmp_path)
    synth = ReflectionSynthesizer(
        policy_store=store, min_occurrences=3,
    )
    # Two totally different signatures
    errors = [
        _error_record("payment gateway timeout on order 1"),
        _error_record("payment gateway timeout on order 2"),
        _error_record("payment gateway timeout on order 3"),
        _error_record(
            "inventory desync between warehouse and shopify", kind="failure:sync",
        ),
        _error_record(
            "inventory desync between warehouse and shopify", kind="failure:sync",
        ),
        _error_record(
            "inventory desync between warehouse and shopify", kind="failure:sync",
        ),
    ]
    report = synth.run(errors)
    assert report.patterns_total == 2
    assert report.patterns_promoted == 2
    assert len(set(report.rule_ids)) == 2
    assert len(store.list_rules(tier=PolicyTier.SOFT)) == 2


# ---------------------------------------------------------------------------
# Learning persists across independent evaluate calls
# ---------------------------------------------------------------------------


def test_learned_rule_blocks_repeated_matching_actions(tmp_path):
    store = _store_with_audit(tmp_path)
    synth = ReflectionSynthesizer(policy_store=store, min_occurrences=3)
    errors = [
        _error_record(f"webhook delivery failed to partner id {i}")
        for i in range(3)
    ]
    synth.run(errors)

    # Three independent actions, each with a different number
    # but the same normalised pattern — all should block
    for order_id in (77, 88, 99):
        decision = store.evaluate_tiered({
            "kind":        "failure:payment_gateway",
            "action_type": "policy_probe",
            "message":     f"webhook delivery failed to partner id {order_id}",
        })
        assert decision.verdict == PolicyVerdict.BLOCK
        assert decision.final_tier == PolicyTier.SOFT


# ---------------------------------------------------------------------------
# Audit trail correlation — inputs_hash lets operators dedupe
# ---------------------------------------------------------------------------


def test_audit_entries_have_stable_inputs_hash(tmp_path):
    store = _store_with_audit(tmp_path)
    action = {
        "kind":        "probe",
        "action_type": "policy_probe",
        "message":     "hello",
    }
    store.evaluate_tiered(action)
    store.evaluate_tiered(action)
    audit = _read_audit(store)
    assert len(audit) == 2
    # Same action → same inputs_hash
    assert audit[0]["inputs_hash"] == audit[1]["inputs_hash"]


def test_audit_entries_have_distinct_entry_ids(tmp_path):
    store = _store_with_audit(tmp_path)
    for i in range(3):
        store.evaluate_tiered({
            "kind":        "probe",
            "action_type": "policy_probe",
            "i":           i,
        })
    audit = _read_audit(store)
    entry_ids = [e["entry_id"] for e in audit]
    assert len(entry_ids) == 3
    assert len(set(entry_ids)) == 3  # all unique
