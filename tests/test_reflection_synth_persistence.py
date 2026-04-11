"""Wave 6 #6: ReflectionSynthesizer promoted-ledger persistence.

Wave 6 #1 added cross-cycle error accumulation in the reflection
hook, but the synthesizer itself still kept its ``_promoted``
ledger purely in-memory — and the policy store it writes to had
no persistence for non-HARD rules either. Net effect: every
restart wiped all learned SOFT rules and the gate started over.

Wave 6 #6 fixes both halves by adding an optional
``persist_path`` to :class:`ReflectionSynthesizer`. On every
successful promotion the pattern is appended to a JSONL ledger;
on startup the ledger is replayed so the synthesizer:

1. Re-registers each learned rule on the (also-restarted)
   policy store, restoring gate behaviour
2. Re-populates ``_promoted`` so the next reflection run won't
   emit a duplicate promotion for an already-known signature

These tests drive the persistence directly.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from core.memory.quality_engine import MemoryRecord
from core.reflection.synthesizer import (
    ReflectionSynthesizer,
    get_default_synthesizer,
    reset_default_synthesizer,
    set_default_synthesizer,
)
from engines.meta_governance.policy_store import PolicyStore, PolicyTier


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> PolicyStore:
    """Fresh isolated policy store per test — audit goes to tmp."""
    return PolicyStore(audit_path=str(tmp_path / "audit.jsonl"))


def _error(message: str, now: float | None = None) -> MemoryRecord:
    return MemoryRecord(
        kind="error",
        quality=0.6,
        confidence=0.7,
        success_rate=0.0,
        usage=1,
        created_at=now or time.time(),
        payload={"message": message},
    )


def _run_three(synth: ReflectionSynthesizer, base: str) -> None:
    """Feed three matching errors so min_occurrences=3 triggers."""
    synth.run([
        _error(f"{base} instance 1"),
        _error(f"{base} instance 2"),
        _error(f"{base} instance 3"),
    ])


# ---------------------------------------------------------------------------
# Bring-up
# ---------------------------------------------------------------------------


def test_no_persist_path_stays_memory_only(tmp_path: Path, store):
    synth = ReflectionSynthesizer(policy_store=store)
    _run_three(synth, "db connection refused on shard")
    assert list(tmp_path.iterdir()) == []  # no ledger file
    assert synth.persist_path is None


def test_first_promotion_creates_ledger(tmp_path: Path, store):
    ledger = tmp_path / "ledger.jsonl"
    synth = ReflectionSynthesizer(
        policy_store=store, persist_path=ledger,
    )
    assert not ledger.exists()
    _run_three(synth, "payment gateway timeout on order")
    assert ledger.exists()
    lines = ledger.read_text().strip().split("\n")
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["kind"] == "error"
    assert row["occurrences"] >= 3
    assert "signature" in row


def test_persist_path_creates_parent_dirs(tmp_path: Path, store):
    ledger = tmp_path / "nested" / "a" / "b" / "ledger.jsonl"
    synth = ReflectionSynthesizer(
        policy_store=store, persist_path=ledger,
    )
    _run_three(synth, "ssl handshake failed for host")
    assert ledger.exists()


# ---------------------------------------------------------------------------
# Rehydration
# ---------------------------------------------------------------------------


def test_rehydration_restores_promoted_ledger(tmp_path: Path):
    """A fresh synthesizer + fresh policy store + existing
    ledger should end up with the promoted signature marked."""
    ledger = tmp_path / "ledger.jsonl"
    store1 = PolicyStore(audit_path=str(tmp_path / "a1.jsonl"))
    s1 = ReflectionSynthesizer(
        policy_store=store1, persist_path=ledger,
    )
    _run_three(s1, "cache miss on key")
    promoted_before = s1.promoted_signatures
    assert len(promoted_before) == 1

    # Restart: brand new policy store and synthesizer, same ledger
    store2 = PolicyStore(audit_path=str(tmp_path / "a2.jsonl"))
    s2 = ReflectionSynthesizer(
        policy_store=store2, persist_path=ledger,
    )
    # Promoted ledger is restored
    assert s2.promoted_signatures == promoted_before
    # And the policy store has the same SOFT rule
    soft = store2.list_rules(tier=PolicyTier.SOFT)
    assert len(soft) == 1
    assert soft[0].rule_id.startswith("learned::")
    assert soft[0].source == "learned"


def test_rehydration_is_idempotent_across_runs(tmp_path: Path):
    """Running the same sequence of errors against a restarted
    synthesizer must NOT re-promote the same signature."""
    ledger = tmp_path / "ledger.jsonl"
    store1 = PolicyStore(audit_path=str(tmp_path / "a1.jsonl"))
    s1 = ReflectionSynthesizer(
        policy_store=store1, persist_path=ledger,
    )
    # Numbers get normalised out of the signature, so these three
    # share a signature that will be rehydrated into s2 below.
    s1.run([
        _error("redis timeout on key 1"),
        _error("redis timeout on key 2"),
        _error("redis timeout on key 3"),
    ])

    # Restart and feed the same normalised pattern again (different
    # numbers, same normalised form → same signature).
    store2 = PolicyStore(audit_path=str(tmp_path / "a2.jsonl"))
    s2 = ReflectionSynthesizer(
        policy_store=store2, persist_path=ledger,
    )
    report = s2.run([
        _error("redis timeout on key 4"),
        _error("redis timeout on key 5"),
        _error("redis timeout on key 6"),
    ])
    # Already promoted — must not re-emit
    assert report.patterns_promoted == 0
    # Ledger file still holds exactly one line
    lines = ledger.read_text().strip().split("\n")
    assert len(lines) == 1


def test_multiple_promotions_append_multiple_lines(tmp_path: Path, store):
    ledger = tmp_path / "ledger.jsonl"
    synth = ReflectionSynthesizer(
        policy_store=store, persist_path=ledger,
    )
    _run_three(synth, "db connection refused on shard")
    _run_three(synth, "inventory desync on sku")
    lines = ledger.read_text().strip().split("\n")
    assert len(lines) == 2


# ---------------------------------------------------------------------------
# Degraded / corrupt ledgers
# ---------------------------------------------------------------------------


def test_missing_ledger_loads_empty(tmp_path: Path, store):
    ledger = tmp_path / "not_there.jsonl"
    synth = ReflectionSynthesizer(
        policy_store=store, persist_path=ledger,
    )
    assert synth.promoted_signatures == []


def test_malformed_line_skipped_but_others_load(tmp_path: Path):
    ledger = tmp_path / "ledger.jsonl"
    # Write one valid row, one garbage line, another valid row
    good1 = {
        "signature":   "error:abc123",
        "kind":        "error",
        "sample_text": "known pattern one",
        "occurrences": 4,
        "first_seen":  1.0,
        "last_seen":   2.0,
        "confidence":  0.9,
    }
    good2 = {
        "signature":   "error:def456",
        "kind":        "error",
        "sample_text": "known pattern two",
        "occurrences": 3,
        "first_seen":  3.0,
        "last_seen":   4.0,
        "confidence":  0.8,
    }
    ledger.write_text(
        json.dumps(good1) + "\n"
        + "not-a-json-line\n"
        + "null\n"
        + json.dumps(good2) + "\n"
    )
    store = PolicyStore(audit_path=str(tmp_path / "a.jsonl"))
    synth = ReflectionSynthesizer(
        policy_store=store, persist_path=ledger,
    )
    # Both good rows replayed
    assert len(synth.promoted_signatures) == 2
    soft = store.list_rules(tier=PolicyTier.SOFT)
    assert len(soft) == 2


def test_partial_bad_row_missing_fields_skipped(tmp_path: Path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        json.dumps({"signature": "x", "kind": "error"}) + "\n"  # missing sample_text etc
        + json.dumps({
            "signature":   "error:okay",
            "kind":        "error",
            "sample_text": "valid pattern",
            "occurrences": 5,
            "confidence":  0.9,
        }) + "\n"
    )
    store = PolicyStore(audit_path=str(tmp_path / "a.jsonl"))
    synth = ReflectionSynthesizer(
        policy_store=store, persist_path=ledger,
    )
    assert synth.promoted_signatures == ["error:okay"]


def test_empty_lines_in_ledger_are_skipped(tmp_path: Path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("\n\n   \n")
    store = PolicyStore(audit_path=str(tmp_path / "a.jsonl"))
    synth = ReflectionSynthesizer(
        policy_store=store, persist_path=ledger,
    )
    assert synth.promoted_signatures == []


def test_unreadable_ledger_falls_back_to_empty(tmp_path: Path, monkeypatch):
    """If open() raises, the synthesizer should start fresh."""
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({
        "signature": "error:x", "kind": "error",
        "sample_text": "t", "occurrences": 3, "confidence": 0.8,
    }) + "\n")

    real_open = open

    def _boom(path, *args, **kwargs):
        if str(path) == str(ledger) and "r" in (args[0] if args else kwargs.get("mode", "r")):
            raise OSError("disk error")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", _boom)
    store = PolicyStore(audit_path=str(tmp_path / "a.jsonl"))
    synth = ReflectionSynthesizer(
        policy_store=store, persist_path=ledger,
    )
    assert synth.promoted_signatures == []


# ---------------------------------------------------------------------------
# Default singleton
# ---------------------------------------------------------------------------


def test_default_synthesizer_returns_same_instance():
    a = get_default_synthesizer()
    b = get_default_synthesizer()
    assert a is b


def test_default_synthesizer_respects_env_var(tmp_path: Path, monkeypatch):
    reset_default_synthesizer()
    ledger = tmp_path / "env.jsonl"
    monkeypatch.setenv("SHOPAI_REFLECTION_PATH", str(ledger))
    synth = get_default_synthesizer()
    assert synth.persist_path == ledger


def test_set_default_synthesizer_overrides_env(tmp_path: Path, store):
    reset_default_synthesizer()
    custom = ReflectionSynthesizer(policy_store=store)
    set_default_synthesizer(custom)
    assert get_default_synthesizer() is custom


# ---------------------------------------------------------------------------
# End-to-end restart simulation via the same ledger path
# ---------------------------------------------------------------------------


def test_learned_rule_survives_full_restart_cycle(tmp_path: Path):
    """Simulate: app runs, learns a pattern, crashes, restarts.

    After restart the SOFT rule must be back in the fresh policy
    store and the synthesizer must not re-promote it.
    """
    ledger = tmp_path / "ledger.jsonl"

    # Session 1: run three matching errors, get a promotion
    store1 = PolicyStore(audit_path=str(tmp_path / "a1.jsonl"))
    s1 = ReflectionSynthesizer(
        policy_store=store1, persist_path=ledger,
    )
    r1 = s1.run([
        _error("db connection refused on shard 1"),
        _error("db connection refused on shard 2"),
        _error("db connection refused on shard 3"),
    ])
    assert r1.patterns_promoted == 1
    first_rule_id = r1.rule_ids[0]

    # Session 2: totally fresh state, same ledger file
    store2 = PolicyStore(audit_path=str(tmp_path / "a2.jsonl"))
    s2 = ReflectionSynthesizer(
        policy_store=store2, persist_path=ledger,
    )
    soft = store2.list_rules(tier=PolicyTier.SOFT)
    assert len(soft) == 1
    assert soft[0].rule_id == first_rule_id

    # And feeding the same pattern again does nothing new
    r2 = s2.run([
        _error("db connection refused on shard 4"),
        _error("db connection refused on shard 5"),
        _error("db connection refused on shard 6"),
    ])
    assert r2.patterns_promoted == 0
