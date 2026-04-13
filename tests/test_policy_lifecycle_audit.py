"""Wave 6 #13: lifecycle audit entries for rule promotion and
retirement inside :class:`engines.meta_governance.PolicyStore`.

Waves 6 #8 and #9 gave rules activation stats and a decay path,
but neither event left a trace in the JSONL audit log — so the
``/api/policy/audit`` endpoint (Wave 5 #B) only showed
evaluate_tiered verdicts, not the lifecycle events that explain
*why* the rule set changed. Wave 6 #13 adds lightweight audit
entries for PROMOTION, REGISTRATION, and RETIREMENT events so the
full rule lifecycle is visible to operators.

These tests verify:

1. ``register()`` emits PROMOTION for learned rules, REGISTRATION
   for operator rules
2. ``remove()`` emits a RETIREMENT entry with stats snapshot
3. RETIREMENT carries the correct tier, source, and stat counters
4. ``read_audit()`` surfaces lifecycle events mixed in with
   evaluate verdicts (newest first)
5. Audit write failure is swallowed (fail-soft)
6. End-to-end: promote → match → retire cycle appears in the log
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from engines.meta_governance.policy_store import (
    PolicyRule,
    PolicyStore,
    PolicyTier,
    PolicyVerdict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_soft_rule(
    name: str,
    source: str = "learned",
    block_keyword: str = "dangerous",
) -> PolicyRule:
    return PolicyRule(
        rule_id=f"learned::{name}",
        name=name,
        tier=PolicyTier.SOFT,
        source=source,
        description=f"Block actions containing '{block_keyword}'",
        matcher=lambda action, _ctx: block_keyword in str(action),
        verdict=PolicyVerdict.BLOCK,
    )


def _audit_lines(store: PolicyStore) -> list[dict[str, Any]]:
    """Return ALL audit lines (raw JSONL, newest last)."""
    path = store._audit_path
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]
    except FileNotFoundError:
        return []


# ---------------------------------------------------------------------------
# Registration / promotion audit
# ---------------------------------------------------------------------------


def test_register_learned_rule_emits_promotion_event(tmp_path: Path):
    store = PolicyStore(audit_path=str(tmp_path / "audit.jsonl"))
    rule = _make_soft_rule("error::stale_pattern", source="learned")
    store.register(rule)
    lines = _audit_lines(store)
    assert len(lines) == 1
    entry = lines[0]
    assert entry["event"] == "PROMOTION"
    assert entry["rule_id"] == "learned::error::stale_pattern"
    assert entry["source"] == "learned"
    assert entry["tier"] == "soft"
    assert "entry_id" in entry
    assert "timestamp" in entry


def test_register_operator_rule_emits_registration_event(tmp_path: Path):
    store = PolicyStore(audit_path=str(tmp_path / "audit.jsonl"))
    rule = PolicyRule(
        rule_id="op::safety_gate",
        name="safety_gate",
        tier=PolicyTier.MEDIUM,
        source="operator",
        description="Operator safety gate",
        matcher=lambda a, c: False,
        verdict=PolicyVerdict.BLOCK,
    )
    store.register(rule)
    lines = _audit_lines(store)
    assert len(lines) == 1
    assert lines[0]["event"] == "REGISTRATION"
    assert lines[0]["source"] == "operator"


def test_re_registration_bumps_version_in_audit(tmp_path: Path):
    store = PolicyStore(audit_path=str(tmp_path / "audit.jsonl"))
    rule = _make_soft_rule("error::dup_pattern")
    store.register(rule)
    store.register(rule)
    lines = _audit_lines(store)
    assert len(lines) == 2
    assert lines[0]["version"] == 1
    assert lines[1]["version"] == 2


# ---------------------------------------------------------------------------
# Retirement audit
# ---------------------------------------------------------------------------


def test_remove_emits_retirement_event(tmp_path: Path):
    store = PolicyStore(audit_path=str(tmp_path / "audit.jsonl"))
    rule = _make_soft_rule("error::old_pattern")
    store.register(rule)
    removed = store.remove("learned::error::old_pattern")
    assert removed is True
    lines = _audit_lines(store)
    # First line is PROMOTION, second is RETIREMENT.
    assert len(lines) == 2
    entry = lines[1]
    assert entry["event"] == "RETIREMENT"
    assert entry["rule_id"] == "learned::error::old_pattern"
    assert entry["tier"] == "soft"
    assert entry["source"] == "learned"


def test_retirement_carries_stats_snapshot(tmp_path: Path):
    store = PolicyStore(audit_path=str(tmp_path / "audit.jsonl"))
    rule = _make_soft_rule("error::stat_check", block_keyword="boom")
    store.register(rule)
    # Evaluate to accumulate stats.
    for _ in range(3):
        store.evaluate_tiered(
            {"action_type": "boom"}, {"source_engine": "test"},
        )
    store.remove("learned::error::stat_check")
    lines = _audit_lines(store)
    retirement = [l for l in lines if l.get("event") == "RETIREMENT"]
    assert len(retirement) == 1
    extra = retirement[0]["extra"]
    assert extra["matches"] == 3
    assert extra["blocks"] == 3


def test_retirement_no_stats_defaults_to_zero(tmp_path: Path):
    store = PolicyStore(audit_path=str(tmp_path / "audit.jsonl"))
    rule = _make_soft_rule("error::never_matched")
    store.register(rule)
    store.remove("learned::error::never_matched")
    lines = _audit_lines(store)
    retirement = [l for l in lines if l.get("event") == "RETIREMENT"]
    extra = retirement[0]["extra"]
    assert extra["matches"] == 0
    assert extra["blocks"] == 0
    assert extra["last_matched_at"] is None


def test_remove_nonexistent_rule_does_not_emit_audit(tmp_path: Path):
    store = PolicyStore(audit_path=str(tmp_path / "audit.jsonl"))
    removed = store.remove("nonexistent::rule")
    assert removed is False
    lines = _audit_lines(store)
    assert len(lines) == 0


# ---------------------------------------------------------------------------
# read_audit surfaces lifecycle events
# ---------------------------------------------------------------------------


def test_read_audit_returns_lifecycle_and_verdicts(tmp_path: Path):
    store = PolicyStore(audit_path=str(tmp_path / "audit.jsonl"))
    rule = _make_soft_rule("error::mixed", block_keyword="blocked")
    store.register(rule)
    # Trigger an evaluate that generates a verdict audit entry.
    store.evaluate_tiered(
        {"action_type": "blocked"}, {"source_engine": "test"},
    )
    store.remove("learned::error::mixed")
    # read_audit returns newest first.
    entries = store.read_audit(limit=10)
    events = [e.get("event") for e in entries if "event" in e]
    verdicts = [e.get("verdict") for e in entries if "verdict" in e and "event" not in e]
    assert "PROMOTION" in events
    assert "RETIREMENT" in events
    assert len(verdicts) >= 1


# ---------------------------------------------------------------------------
# Fail-soft
# ---------------------------------------------------------------------------


def test_lifecycle_audit_write_failure_is_swallowed(
    tmp_path: Path, monkeypatch,
):
    store = PolicyStore(audit_path=str(tmp_path / "audit.jsonl"))
    # Break the file open for lifecycle.
    import builtins
    real_open = builtins.open

    def _no_lifecycle(path, *a, **kw):
        # Let the first (registration) write succeed, then fail on
        # all subsequent appends so the retirement fails.
        if "audit.jsonl" in str(path) and (tmp_path / "audit.jsonl").exists():
            raise OSError("disk full")
        return real_open(path, *a, **kw)

    rule = _make_soft_rule("error::audit_crash")
    store.register(rule)  # this one succeeds

    monkeypatch.setattr("builtins.open", _no_lifecycle)
    # remove() must still return True even if audit write fails.
    removed = store.remove("learned::error::audit_crash")
    assert removed is True


# ---------------------------------------------------------------------------
# End-to-end: promote → match → retire cycle
# ---------------------------------------------------------------------------


def test_e2e_promote_match_retire_cycle(tmp_path: Path):
    """Full cycle: a learned rule is promoted, matches some actions,
    then gets retired. The audit log captures all three events."""
    store = PolicyStore(audit_path=str(tmp_path / "audit.jsonl"))

    # Promote via the dedicated helper (same as reflection synth).
    rule = PolicyRule(
        rule_id="learned::e2e_cycle",
        name="e2e_cycle",
        tier=PolicyTier.SOFT,
        source="learned",
        description="Block anything with 'danger'",
        matcher=lambda a, _: "danger" in str(a),
        verdict=PolicyVerdict.BLOCK,
    )
    store.promote_soft_rule(rule)

    # Match 5 times.
    for _ in range(5):
        store.evaluate_tiered(
            {"action_type": "danger"}, {"source_engine": "test"},
        )

    # Retire.
    store.remove("learned::e2e_cycle")

    # The audit log has: 1 PROMOTION + 5 verdicts + 1 RETIREMENT.
    lines = _audit_lines(store)
    assert len(lines) == 7
    assert lines[0]["event"] == "PROMOTION"
    assert lines[-1]["event"] == "RETIREMENT"
    assert lines[-1]["extra"]["matches"] == 5
    assert lines[-1]["extra"]["blocks"] == 5
