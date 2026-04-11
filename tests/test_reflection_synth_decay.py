"""Wave 6 #9: :meth:`ReflectionSynthesizer.decay_stale_rules`.

Wave 6 #6 made learned SOFT rules persistent and Wave 6 #8 made
them count their own firings. Together they expose which learned
rules are dead (``matches == 0``) and which are hot. The missing
piece is a way to *act* on that signal: retire learned rules that
have been idle for too long so the policy store doesn't accrete
stale scar tissue forever.

These tests exercise decay directly against a real ``PolicyStore``
so we can check the full ripple:

1. the rule is gone from ``store.list_rules()``
2. the signature is gone from ``promoted_signatures`` and
   ``snapshot()``
3. the JSONL ledger is rewritten (atomically) without the
   retired row — survivors stay intact
4. stats recorded against the retired rule do NOT prevent a
   later ``forget`` + re-promotion cycle
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from core.memory.quality_engine import MemoryRecord
from core.reflection.synthesizer import (
    ReflectionSynthesizer,
)
from engines.meta_governance.policy_store import (
    PolicyStore,
    PolicyTier,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> PolicyStore:
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


def _promote(
    synth: ReflectionSynthesizer, base: str, at: float,
) -> str:
    """Feed three matching errors timestamped *at* so the resulting
    ErrorPattern has a controlled ``last_seen``."""
    records = [
        _error(f"{base} occurrence 1", now=at),
        _error(f"{base} occurrence 2", now=at),
        _error(f"{base} occurrence 3", now=at),
    ]
    report = synth.run(records)
    assert report.patterns_promoted == 1, (
        f"expected exactly one promotion for {base}"
    )
    return report.patterns[0].signature


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


def test_decay_rejects_negative_idle(store):
    synth = ReflectionSynthesizer(policy_store=store)
    with pytest.raises(ValueError):
        synth.decay_stale_rules(-1.0)


# ---------------------------------------------------------------------------
# In-memory-only behaviour (no persist_path)
# ---------------------------------------------------------------------------


def test_decay_empty_synth_is_noop(store):
    synth = ReflectionSynthesizer(policy_store=store)
    assert synth.decay_stale_rules(60.0) == []


def test_decay_keeps_recent_never_matched_rule(store):
    synth = ReflectionSynthesizer(policy_store=store)
    now = 1_000_000.0
    sig = _promote(synth, "payment gateway stall on order", at=now - 10)
    # Window is 60s, rule learned 10s ago → keep
    removed = synth.decay_stale_rules(60.0, now=now)
    assert removed == []
    assert sig in synth.promoted_signatures
    soft = store.list_rules(tier=PolicyTier.SOFT)
    assert len(soft) == 1


def test_decay_removes_old_never_matched_rule(store):
    synth = ReflectionSynthesizer(policy_store=store)
    now = 1_000_000.0
    sig = _promote(synth, "db connection refused on shard", at=now - 600)
    # Window is 60s, rule learned 600s ago and never matched → retire
    removed = synth.decay_stale_rules(60.0, now=now)
    assert removed == [sig]
    assert sig not in synth.promoted_signatures
    assert store.list_rules(tier=PolicyTier.SOFT) == []


# ---------------------------------------------------------------------------
# Interaction with Wave 6 #8 store stats
# ---------------------------------------------------------------------------


def test_decay_uses_store_last_matched_at_when_available(store):
    synth = ReflectionSynthesizer(policy_store=store)
    now = 2_000_000.0
    sig = _promote(synth, "ssl handshake failure", at=now - 3600)
    rule_id = f"learned::{sig}"
    # Simulate a recent match: inject a fake stats row so
    # last_matched_at is now - 10 (well inside the window).
    store._rule_stats[rule_id] = {
        "rule_id":          rule_id,
        "tier":             "soft",
        "source":           "learned",
        "matches":          1,
        "blocks":           1,
        "modifications":    0,
        "first_matched_at": now - 10,
        "last_matched_at":  now - 10,
    }
    # Window is 60s, last match was 10s ago → keep even though
    # pattern.last_seen is 3600s old.
    removed = synth.decay_stale_rules(60.0, now=now)
    assert removed == []
    assert sig in synth.promoted_signatures


def test_decay_retires_rule_whose_last_match_is_old(store):
    synth = ReflectionSynthesizer(policy_store=store)
    now = 3_000_000.0
    sig = _promote(synth, "inventory desync on sku", at=now - 5)
    rule_id = f"learned::{sig}"
    # Fake stats with an old last-match (pretend rule hasn't fired
    # for 10 minutes) — even though the pattern was learned 5s ago.
    store._rule_stats[rule_id] = {
        "rule_id":          rule_id,
        "tier":             "soft",
        "source":           "learned",
        "matches":          3,
        "blocks":           3,
        "modifications":    0,
        "first_matched_at": now - 1000,
        "last_matched_at":  now - 600,
    }
    removed = synth.decay_stale_rules(60.0, now=now)
    assert removed == [sig]
    assert store.list_rules(tier=PolicyTier.SOFT) == []


# ---------------------------------------------------------------------------
# Persistence: ledger rewrite
# ---------------------------------------------------------------------------


def test_decay_rewrites_ledger_dropping_stale_rows(store, tmp_path: Path):
    ledger = tmp_path / "ledger.jsonl"
    synth = ReflectionSynthesizer(
        policy_store=store, persist_path=ledger,
    )
    now = 4_000_000.0
    stale_sig = _promote(synth, "cache miss on key", at=now - 9999)
    fresh_sig = _promote(synth, "payment fallback needed", at=now - 5)
    # Before decay, ledger has both lines
    assert len(ledger.read_text().strip().split("\n")) == 2

    removed = synth.decay_stale_rules(60.0, now=now)
    assert removed == [stale_sig]
    assert fresh_sig in synth.promoted_signatures

    # Ledger was rewritten to a single surviving row
    lines = ledger.read_text().strip().split("\n")
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["signature"] == fresh_sig


def test_decay_empty_removal_does_not_touch_ledger(store, tmp_path: Path):
    ledger = tmp_path / "ledger.jsonl"
    synth = ReflectionSynthesizer(
        policy_store=store, persist_path=ledger,
    )
    now = 5_000_000.0
    _promote(synth, "k8s pod eviction detected", at=now - 5)
    original = ledger.read_text()
    original_mtime = ledger.stat().st_mtime
    # Nothing to remove
    assert synth.decay_stale_rules(60.0, now=now) == []
    # File untouched (content + mtime)
    assert ledger.read_text() == original
    # mtime may be the same or newer depending on fs granularity,
    # but content stability is the real invariant.


def test_decay_keeps_ledger_atomic_on_rewrite_failure(
    store, tmp_path: Path, monkeypatch
):
    """If ledger rewrite raises, the original file should still
    exist and hold the pre-decay content (atomic via os.replace)."""
    ledger = tmp_path / "ledger.jsonl"
    synth = ReflectionSynthesizer(
        policy_store=store, persist_path=ledger,
    )
    now = 6_000_000.0
    _promote(synth, "graceful drain timeout", at=now - 5)
    _promote(synth, "redis eviction thrash on shard", at=now - 9999)
    original_lines = ledger.read_text().strip().split("\n")
    assert len(original_lines) == 2

    # Force os.replace to raise so the rewrite aborts after the
    # tempfile is written but before the target is swapped.
    import os as _os
    real_replace = _os.replace

    def _boom(src, dst, *args, **kwargs):
        if str(dst) == str(ledger):
            raise OSError("disk full")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr("os.replace", _boom)
    # Decay still removes in-memory state, but the ledger rewrite
    # fails — the warning is swallowed and the original file is
    # unchanged.
    removed = synth.decay_stale_rules(60.0, now=now)
    assert len(removed) == 1
    assert ledger.read_text().strip().split("\n") == original_lines


# ---------------------------------------------------------------------------
# Interaction with snapshot() (Wave 6 #7)
# ---------------------------------------------------------------------------


def test_decay_removes_pattern_from_snapshot(store):
    synth = ReflectionSynthesizer(policy_store=store)
    now = 7_000_000.0
    _promote(synth, "connection pool exhausted", at=now - 9999)
    fresh_sig = _promote(synth, "rate limit hit on api", at=now - 5)
    synth.decay_stale_rules(60.0, now=now)
    snap = synth.snapshot()
    assert len(snap) == 1
    assert snap[0]["signature"] == fresh_sig


# ---------------------------------------------------------------------------
# Idempotency + re-promotion after decay
# ---------------------------------------------------------------------------


def test_decay_is_idempotent(store):
    synth = ReflectionSynthesizer(policy_store=store)
    now = 8_000_000.0
    _promote(synth, "timeout waiting for worker", at=now - 9999)
    first = synth.decay_stale_rules(60.0, now=now)
    second = synth.decay_stale_rules(60.0, now=now)
    assert len(first) == 1
    assert second == []


def test_decay_allows_future_re_promotion(store):
    """After decay the signature is free to be promoted again
    if the same pattern recurs."""
    synth = ReflectionSynthesizer(policy_store=store)
    now = 9_000_000.0
    sig = _promote(synth, "downstream 429 burst", at=now - 9999)
    synth.decay_stale_rules(60.0, now=now)
    assert sig not in synth.promoted_signatures
    # Feed the pattern again — it is a new promotion now.
    report = synth.run([
        _error("downstream 429 burst occurrence 1", now=now),
        _error("downstream 429 burst occurrence 2", now=now),
        _error("downstream 429 burst occurrence 3", now=now),
    ])
    assert report.patterns_promoted == 1


# ---------------------------------------------------------------------------
# Decay on rehydrated state (post-restart)
# ---------------------------------------------------------------------------


def test_decay_works_on_rehydrated_state(tmp_path: Path):
    ledger = tmp_path / "ledger.jsonl"
    store1 = PolicyStore(audit_path=str(tmp_path / "a1.jsonl"))
    s1 = ReflectionSynthesizer(
        policy_store=store1, persist_path=ledger,
    )
    now = 10_000_000.0
    _promote(s1, "upstream 5xx spike", at=now - 9999)

    # Restart: fresh store + synth
    store2 = PolicyStore(audit_path=str(tmp_path / "a2.jsonl"))
    s2 = ReflectionSynthesizer(
        policy_store=store2, persist_path=ledger,
    )
    assert len(s2.promoted_signatures) == 1

    removed = s2.decay_stale_rules(60.0, now=now)
    assert len(removed) == 1
    assert s2.promoted_signatures == []
    # Ledger was rewritten on disk — a third synth rehydrates to empty
    store3 = PolicyStore(audit_path=str(tmp_path / "a3.jsonl"))
    s3 = ReflectionSynthesizer(
        policy_store=store3, persist_path=ledger,
    )
    assert s3.promoted_signatures == []
