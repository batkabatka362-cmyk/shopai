"""Wave 2 #1 tests — Policy Engine tiering, audit, versioning, and promotion.

Covers the ``engines/meta_governance/policy_store`` module end-to-end:
- PolicyTier / PolicyVerdict enums
- PolicyRule dataclass serialisation
- PolicyStore registration, removal, version bumping
- Tiered evaluation (HARD → MEDIUM → SOFT) with ALLOW / MODIFY / BLOCK
- JSONL audit log (per-decision + lifecycle events)
- Rule activation stats
- MEDIUM rule ledger persistence and rehydration
- promote_soft_rule() flow
- Thread-safe concurrent evaluation
- Module-level convenience wrapper
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

import pytest

from engines.meta_governance.policy_store import (
    PolicyDecision,
    PolicyRule,
    PolicyStore,
    PolicyTier,
    PolicyVerdict,
    _hash_inputs,
    evaluate_tiered,
    get_default_store,
    reset_default_store,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_audit(tmp_path: Path) -> str:
    """Return a temp path for the audit JSONL file."""
    return str(tmp_path / "audit" / "policy_audit.jsonl")


@pytest.fixture()
def tmp_ledger(tmp_path: Path) -> str:
    """Return a temp path for the MEDIUM rules ledger."""
    return str(tmp_path / "ledger" / "medium_rules.jsonl")


@pytest.fixture()
def store(tmp_audit: str) -> PolicyStore:
    """Fresh PolicyStore writing to a temp audit file."""
    return PolicyStore(audit_path=tmp_audit)


def _make_rule(
    rule_id: str = "TEST-001",
    name: str = "test rule",
    tier: PolicyTier = PolicyTier.MEDIUM,
    source: str = "operator",
    verdict: PolicyVerdict = PolicyVerdict.BLOCK,
    matcher: Any = None,
    modify_fn: Any = None,
    match_field: str | None = None,
    match_pattern: str | None = None,
) -> PolicyRule:
    """Helper to build a PolicyRule with sensible defaults."""
    return PolicyRule(
        rule_id=rule_id,
        name=name,
        tier=tier,
        source=source,
        description=f"Test rule {rule_id}",
        matcher=matcher or (lambda action, ctx: True),
        verdict=verdict,
        modify_fn=modify_fn,
        match_field=match_field,
        match_pattern=match_pattern,
    )


# A safe action that passes all HARD checks (no ad, no budget, no discount,
# no blocked keywords, not high-impact).
_SAFE_ACTION: dict[str, Any] = {"action_type": "read_data", "title": "hello"}
_SAFE_CONTEXT: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TestPolicyTier:
    def test_values(self):
        assert PolicyTier.HARD.value == "hard"
        assert PolicyTier.MEDIUM.value == "medium"
        assert PolicyTier.SOFT.value == "soft"

    def test_all_tiers_present(self):
        names = {t.name for t in PolicyTier}
        assert names == {"HARD", "MEDIUM", "SOFT"}


class TestPolicyVerdict:
    def test_values(self):
        assert PolicyVerdict.ALLOW.value == "allow"
        assert PolicyVerdict.MODIFY.value == "modify"
        assert PolicyVerdict.BLOCK.value == "block"


# ---------------------------------------------------------------------------
# PolicyRule
# ---------------------------------------------------------------------------


class TestPolicyRule:
    def test_to_audit_dict_contains_required_fields(self):
        rule = _make_rule()
        d = rule.to_audit_dict()
        assert d["rule_id"] == "TEST-001"
        assert d["tier"] == "medium"
        assert d["version"] == 1
        assert d["source"] == "operator"
        assert d["verdict"] == "block"
        assert "created_at" in d

    def test_to_audit_dict_includes_match_spec_when_set(self):
        rule = _make_rule(match_field="action_type", match_pattern="^deploy")
        d = rule.to_audit_dict()
        assert d["match_field"] == "action_type"
        assert d["match_pattern"] == "^deploy"

    def test_to_audit_dict_omits_match_spec_when_none(self):
        rule = _make_rule()
        d = rule.to_audit_dict()
        assert "match_field" not in d
        assert "match_pattern" not in d

    def test_default_version_is_one(self):
        rule = _make_rule()
        assert rule.version == 1


# ---------------------------------------------------------------------------
# PolicyStore — registration
# ---------------------------------------------------------------------------


class TestPolicyStoreRegistration:
    def test_register_medium_rule(self, store: PolicyStore):
        rule = _make_rule(tier=PolicyTier.MEDIUM)
        rid = store.register(rule)
        assert rid == "TEST-001"
        assert len(store.list_rules(PolicyTier.MEDIUM)) == 1

    def test_register_soft_rule(self, store: PolicyStore):
        rule = _make_rule(rule_id="SOFT-001", tier=PolicyTier.SOFT, source="learned")
        store.register(rule)
        assert len(store.list_rules(PolicyTier.SOFT)) == 1

    def test_register_hard_raises(self, store: PolicyStore):
        rule = _make_rule(tier=PolicyTier.HARD)
        with pytest.raises(ValueError, match="HARD rules are immutable"):
            store.register(rule)

    def test_re_register_bumps_version(self, store: PolicyStore):
        rule1 = _make_rule()
        store.register(rule1)

        rule2 = _make_rule()  # same rule_id
        store.register(rule2)

        rules = store.list_rules(PolicyTier.MEDIUM)
        assert len(rules) == 1
        assert rules[0].version == 2

    def test_list_all_rules(self, store: PolicyStore):
        store.register(_make_rule(rule_id="M1", tier=PolicyTier.MEDIUM))
        store.register(_make_rule(rule_id="S1", tier=PolicyTier.SOFT, source="learned"))
        all_rules = store.list_rules()
        ids = {r.rule_id for r in all_rules}
        assert "M1" in ids
        assert "S1" in ids


class TestPolicyStoreRemoval:
    def test_remove_existing_rule(self, store: PolicyStore):
        store.register(_make_rule(rule_id="DEL-001"))
        assert store.remove("DEL-001") is True
        assert len(store.list_rules(PolicyTier.MEDIUM)) == 0

    def test_remove_nonexistent_returns_false(self, store: PolicyStore):
        assert store.remove("NOPE") is False


class TestVersionBumping:
    def test_bump_version(self, store: PolicyStore):
        store.register(_make_rule(rule_id="V1"))
        new_ver = store.bump_version("V1")
        assert new_ver == 2

    def test_bump_nonexistent_returns_none(self, store: PolicyStore):
        assert store.bump_version("MISSING") is None


# ---------------------------------------------------------------------------
# PolicyStore — evaluate_tiered
# ---------------------------------------------------------------------------


class TestEvaluateTiered:
    def test_safe_action_passes_with_allow(self, store: PolicyStore):
        decision = store.evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT)
        assert isinstance(decision, PolicyDecision)
        assert decision.verdict == PolicyVerdict.ALLOW
        assert decision.hard_passed is True
        assert decision.failed_count == 0

    def test_hard_block_on_high_impact_without_approval(self, store: PolicyStore):
        action = {"action_type": "delete_product"}
        decision = store.evaluate_tiered(action, {})
        assert decision.verdict == PolicyVerdict.BLOCK
        assert decision.hard_passed is False
        assert decision.final_rule_id == "HARD:policy_checker"
        assert decision.final_tier == PolicyTier.HARD

    def test_hard_block_on_blocked_keyword(self, store: PolicyStore):
        action = {"action_type": "post", "title": "get rich quick"}
        decision = store.evaluate_tiered(action, {})
        assert decision.verdict == PolicyVerdict.BLOCK
        assert decision.hard_passed is False

    def test_medium_block_stops_evaluation(self, store: PolicyStore):
        store.register(_make_rule(
            rule_id="MED-BLOCK",
            tier=PolicyTier.MEDIUM,
            verdict=PolicyVerdict.BLOCK,
            matcher=lambda a, c: True,
        ))
        decision = store.evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT)
        assert decision.verdict == PolicyVerdict.BLOCK
        assert decision.final_rule_id == "MED-BLOCK"
        assert decision.final_tier == PolicyTier.MEDIUM
        assert decision.hard_passed is True

    def test_soft_block(self, store: PolicyStore):
        store.register(_make_rule(
            rule_id="SOFT-BLOCK",
            tier=PolicyTier.SOFT,
            source="learned",
            verdict=PolicyVerdict.BLOCK,
            matcher=lambda a, c: True,
        ))
        decision = store.evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT)
        assert decision.verdict == PolicyVerdict.BLOCK
        assert decision.final_rule_id == "SOFT-BLOCK"
        assert decision.final_tier == PolicyTier.SOFT

    def test_modify_patches_action(self, store: PolicyStore):
        store.register(_make_rule(
            rule_id="MOD-001",
            tier=PolicyTier.MEDIUM,
            verdict=PolicyVerdict.MODIFY,
            matcher=lambda a, c: True,
            modify_fn=lambda a, c: {"patched": True, "budget": 50},
        ))
        decision = store.evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT)
        assert decision.verdict == PolicyVerdict.MODIFY
        assert decision.action["patched"] is True
        assert decision.action["budget"] == 50
        assert decision.modifications == {"patched": True, "budget": 50}

    def test_modify_accumulates_patches(self, store: PolicyStore):
        store.register(_make_rule(
            rule_id="MOD-A",
            tier=PolicyTier.MEDIUM,
            verdict=PolicyVerdict.MODIFY,
            matcher=lambda a, c: True,
            modify_fn=lambda a, c: {"field_a": 1},
        ))
        store.register(_make_rule(
            rule_id="MOD-B",
            tier=PolicyTier.MEDIUM,
            verdict=PolicyVerdict.MODIFY,
            matcher=lambda a, c: True,
            modify_fn=lambda a, c: {"field_b": 2},
        ))
        decision = store.evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT)
        assert decision.modifications.get("field_a") == 1
        assert decision.modifications.get("field_b") == 2

    def test_allow_rule_does_not_change_verdict(self, store: PolicyStore):
        store.register(_make_rule(
            rule_id="ALLOW-1",
            tier=PolicyTier.MEDIUM,
            verdict=PolicyVerdict.ALLOW,
            matcher=lambda a, c: True,
        ))
        decision = store.evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT)
        assert decision.verdict == PolicyVerdict.ALLOW

    def test_non_matching_rules_are_skipped(self, store: PolicyStore):
        store.register(_make_rule(
            rule_id="NEVER",
            tier=PolicyTier.MEDIUM,
            verdict=PolicyVerdict.BLOCK,
            matcher=lambda a, c: False,  # never fires
        ))
        decision = store.evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT)
        assert decision.verdict == PolicyVerdict.ALLOW

    def test_matcher_exception_is_swallowed(self, store: PolicyStore):
        def bad_matcher(a, c):
            raise RuntimeError("boom")

        store.register(_make_rule(
            rule_id="BAD",
            tier=PolicyTier.MEDIUM,
            verdict=PolicyVerdict.BLOCK,
            matcher=bad_matcher,
        ))
        decision = store.evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT)
        # Rule should be skipped, not crash the pipeline
        assert decision.verdict == PolicyVerdict.ALLOW
        # Error should appear in trace
        bad_entries = [t for t in decision.trace if t.get("error")]
        assert len(bad_entries) == 1
        assert "boom" in bad_entries[0]["error"]

    def test_decision_to_dict(self, store: PolicyStore):
        decision = store.evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT)
        d = decision.to_dict()
        assert d["verdict"] == "allow"
        assert d["hard_passed"] is True
        assert isinstance(d["trace"], list)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


class TestAuditLog:
    def test_audit_file_created_on_evaluate(self, store: PolicyStore, tmp_audit: str):
        store.evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT)
        assert os.path.isfile(tmp_audit)

    def test_audit_entry_is_valid_jsonl(self, store: PolicyStore, tmp_audit: str):
        store.evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT)
        with open(tmp_audit) as fh:
            lines = [l.strip() for l in fh if l.strip()]
        assert len(lines) >= 1
        entry = json.loads(lines[-1])
        assert "verdict" in entry
        assert "entry_id" in entry
        assert "timestamp" in entry
        assert "inputs_hash" in entry

    def test_audit_records_block_verdict(self, store: PolicyStore, tmp_audit: str):
        store.register(_make_rule(
            rule_id="AUD-BLOCK",
            verdict=PolicyVerdict.BLOCK,
            matcher=lambda a, c: True,
        ))
        store.evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT)
        with open(tmp_audit) as fh:
            lines = [l.strip() for l in fh if l.strip()]
        # Find the evaluation entry (not lifecycle)
        eval_entries = [json.loads(l) for l in lines if "trace" in l]
        assert any(e["verdict"] == "block" for e in eval_entries)

    def test_lifecycle_audit_on_registration(self, store: PolicyStore, tmp_audit: str):
        store.register(_make_rule(rule_id="LC-001"))
        with open(tmp_audit) as fh:
            lines = [l.strip() for l in fh if l.strip()]
        entries = [json.loads(l) for l in lines]
        reg_events = [e for e in entries if e.get("event") == "REGISTRATION"]
        assert len(reg_events) == 1
        assert reg_events[0]["rule_id"] == "LC-001"

    def test_lifecycle_audit_on_promotion(self, store: PolicyStore, tmp_audit: str):
        rule = _make_rule(rule_id="PROM-001", tier=PolicyTier.SOFT)
        store.promote_soft_rule(rule)
        with open(tmp_audit) as fh:
            lines = [l.strip() for l in fh if l.strip()]
        entries = [json.loads(l) for l in lines]
        prom_events = [e for e in entries if e.get("event") == "PROMOTION"]
        assert len(prom_events) == 1

    def test_lifecycle_audit_on_retirement(self, store: PolicyStore, tmp_audit: str):
        store.register(_make_rule(rule_id="RET-001"))
        store.remove("RET-001")
        with open(tmp_audit) as fh:
            lines = [l.strip() for l in fh if l.strip()]
        entries = [json.loads(l) for l in lines]
        ret_events = [e for e in entries if e.get("event") == "RETIREMENT"]
        assert len(ret_events) == 1
        assert ret_events[0]["rule_id"] == "RET-001"

    def test_read_audit_returns_newest_first(self, store: PolicyStore):
        # Generate multiple audit entries
        for _ in range(5):
            store.evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT)
        entries = store.read_audit(limit=3)
        assert len(entries) <= 3
        assert all(isinstance(e, dict) for e in entries)

    def test_read_audit_empty_file(self, tmp_path: Path):
        audit_path = str(tmp_path / "empty_audit.jsonl")
        s = PolicyStore(audit_path=audit_path)
        assert s.read_audit() == []


# ---------------------------------------------------------------------------
# Rule activation stats
# ---------------------------------------------------------------------------


class TestRuleStats:
    def test_stats_recorded_on_match(self, store: PolicyStore):
        store.register(_make_rule(
            rule_id="STAT-001",
            verdict=PolicyVerdict.BLOCK,
            matcher=lambda a, c: True,
        ))
        store.evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT)
        stats = store.get_rule_stats("STAT-001")
        assert stats is not None
        assert stats["matches"] >= 1
        assert stats["blocks"] >= 1
        assert "last_matched_at" in stats

    def test_no_stats_for_non_matching_rule(self, store: PolicyStore):
        store.register(_make_rule(
            rule_id="NOFIRE",
            matcher=lambda a, c: False,
        ))
        store.evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT)
        assert store.get_rule_stats("NOFIRE") is None

    def test_get_all_rule_stats(self, store: PolicyStore):
        store.register(_make_rule(
            rule_id="S1",
            verdict=PolicyVerdict.BLOCK,
            matcher=lambda a, c: True,
        ))
        store.evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT)
        all_stats = store.get_all_rule_stats()
        assert len(all_stats) >= 1
        assert all_stats[0]["rule_id"] == "S1"

    def test_reset_rule_stats_single(self, store: PolicyStore):
        store.register(_make_rule(
            rule_id="RS1",
            verdict=PolicyVerdict.BLOCK,
            matcher=lambda a, c: True,
        ))
        store.evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT)
        store.reset_rule_stats("RS1")
        assert store.get_rule_stats("RS1") is None

    def test_reset_rule_stats_all(self, store: PolicyStore):
        store.register(_make_rule(
            rule_id="RA1",
            verdict=PolicyVerdict.BLOCK,
            matcher=lambda a, c: True,
        ))
        store.evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT)
        store.reset_rule_stats()
        assert store.get_all_rule_stats() == []


# ---------------------------------------------------------------------------
# promote_soft_rule
# ---------------------------------------------------------------------------


class TestPromoteSoftRule:
    def test_promotes_to_soft_tier(self, store: PolicyStore):
        rule = _make_rule(rule_id="LEARN-001", tier=PolicyTier.MEDIUM)
        rid = store.promote_soft_rule(rule)
        assert rid == "LEARN-001"
        soft_rules = store.list_rules(PolicyTier.SOFT)
        assert len(soft_rules) == 1
        assert soft_rules[0].source == "learned"
        assert soft_rules[0].tier == PolicyTier.SOFT

    def test_promoted_rule_fires_in_evaluation(self, store: PolicyStore):
        rule = _make_rule(
            rule_id="LEARN-FIRE",
            verdict=PolicyVerdict.BLOCK,
            matcher=lambda a, c: True,
        )
        store.promote_soft_rule(rule)
        decision = store.evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT)
        assert decision.verdict == PolicyVerdict.BLOCK
        assert decision.final_tier == PolicyTier.SOFT


# ---------------------------------------------------------------------------
# MEDIUM rule persistence (ledger)
# ---------------------------------------------------------------------------


class TestMediumLedgerPersistence:
    def test_persist_and_rehydrate(self, tmp_audit: str, tmp_ledger: str):
        # Register a serialisable MEDIUM rule
        store1 = PolicyStore(audit_path=tmp_audit, medium_ledger_path=tmp_ledger)
        rule = _make_rule(
            rule_id="PERSIST-001",
            tier=PolicyTier.MEDIUM,
            match_field="action_type",
            match_pattern="^deploy",
        )
        store1.register(rule)
        assert os.path.isfile(tmp_ledger)

        # Create a new store pointing to the same ledger
        store2 = PolicyStore(audit_path=tmp_audit, medium_ledger_path=tmp_ledger)
        rules = store2.list_rules(PolicyTier.MEDIUM)
        assert len(rules) == 1
        assert rules[0].rule_id == "PERSIST-001"
        assert rules[0].match_field == "action_type"

    def test_rehydrated_rule_matcher_works(self, tmp_audit: str, tmp_ledger: str):
        store1 = PolicyStore(audit_path=tmp_audit, medium_ledger_path=tmp_ledger)
        store1.register(_make_rule(
            rule_id="REHYD-001",
            tier=PolicyTier.MEDIUM,
            verdict=PolicyVerdict.BLOCK,
            match_field="action_type",
            match_pattern="^deploy",
        ))

        store2 = PolicyStore(audit_path=tmp_audit, medium_ledger_path=tmp_ledger)
        # Action matching the pattern
        decision = store2.evaluate_tiered(
            {"action_type": "deploy_campaign"}, {},
        )
        assert decision.verdict == PolicyVerdict.BLOCK

        # Action NOT matching the pattern
        decision2 = store2.evaluate_tiered(
            {"action_type": "read_data"}, {},
        )
        assert decision2.verdict == PolicyVerdict.ALLOW

    def test_non_serialisable_rules_not_persisted(self, tmp_audit: str, tmp_ledger: str):
        store1 = PolicyStore(audit_path=tmp_audit, medium_ledger_path=tmp_ledger)
        # No match_field / match_pattern → callable-only, not persisted
        store1.register(_make_rule(rule_id="CALLABLE-ONLY", tier=PolicyTier.MEDIUM))
        store2 = PolicyStore(audit_path=tmp_audit, medium_ledger_path=tmp_ledger)
        assert len(store2.list_rules(PolicyTier.MEDIUM)) == 0

    def test_removal_updates_ledger(self, tmp_audit: str, tmp_ledger: str):
        store1 = PolicyStore(audit_path=tmp_audit, medium_ledger_path=tmp_ledger)
        store1.register(_make_rule(
            rule_id="DEL-LED",
            tier=PolicyTier.MEDIUM,
            match_field="action_type",
            match_pattern="test",
        ))
        store1.remove("DEL-LED")

        store2 = PolicyStore(audit_path=tmp_audit, medium_ledger_path=tmp_ledger)
        assert len(store2.list_rules(PolicyTier.MEDIUM)) == 0


# ---------------------------------------------------------------------------
# Hash inputs
# ---------------------------------------------------------------------------


class TestHashInputs:
    def test_deterministic(self):
        h1 = _hash_inputs({"a": 1}, {"b": 2})
        h2 = _hash_inputs({"a": 1}, {"b": 2})
        assert h1 == h2

    def test_different_inputs_different_hash(self):
        h1 = _hash_inputs({"a": 1}, {})
        h2 = _hash_inputs({"a": 2}, {})
        assert h1 != h2

    def test_returns_short_hex_string(self):
        h = _hash_inputs({}, {})
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# Module-level convenience wrapper
# ---------------------------------------------------------------------------


class TestModuleLevelEvaluate:
    def test_uses_default_store(self):
        reset_default_store()
        decision = evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT)
        assert isinstance(decision, PolicyDecision)
        assert decision.verdict == PolicyVerdict.ALLOW
        reset_default_store()

    def test_custom_store_override(self, store: PolicyStore):
        store.register(_make_rule(
            rule_id="CUSTOM",
            verdict=PolicyVerdict.BLOCK,
            matcher=lambda a, c: True,
        ))
        decision = evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT, store=store)
        assert decision.verdict == PolicyVerdict.BLOCK


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_evaluate(self, store: PolicyStore):
        """Run evaluate_tiered from multiple threads to ensure no crash."""
        store.register(_make_rule(
            rule_id="CONC-001",
            verdict=PolicyVerdict.ALLOW,
            matcher=lambda a, c: True,
        ))

        errors: list[Exception] = []
        barrier = threading.Barrier(4)

        def worker():
            try:
                barrier.wait(timeout=5)
                for _ in range(10):
                    d = store.evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT)
                    assert d.hard_passed is True
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert not errors, f"Thread errors: {errors}"

    def test_concurrent_register_and_evaluate(self, store: PolicyStore):
        """Register rules while evaluating concurrently."""
        errors: list[Exception] = []

        def register_worker():
            try:
                for i in range(20):
                    store.register(_make_rule(
                        rule_id=f"REG-{i}",
                        verdict=PolicyVerdict.ALLOW,
                        matcher=lambda a, c: True,
                    ))
            except Exception as exc:
                errors.append(exc)

        def eval_worker():
            try:
                for _ in range(20):
                    store.evaluate_tiered(_SAFE_ACTION, _SAFE_CONTEXT)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=register_worker),
            threading.Thread(target=eval_worker),
            threading.Thread(target=eval_worker),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert not errors, f"Thread errors: {errors}"
