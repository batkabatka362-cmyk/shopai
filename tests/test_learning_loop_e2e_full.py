"""Wave 6 #19e: end-to-end learning-loop integration test.

Exercises the complete path through the Wave 6 learning
feedback loop in a single controlled scenario:

    error records
      → synthesizer.run()
        → SOFT rule promoted (policy store + audit)
          → evaluate_tiered() fires the learned rule
            → rule stats accumulate
              → decay_stale_rules() retires the idle rule
                → audit trail has PROMOTION + verdict + RETIREMENT

Every subsystem is real — no mocks except time. The test
verifies that the loop closes cleanly and the audit log
contains a coherent narrative an operator could read end-to-end.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

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


def _error(message: str, ts: float | None = None) -> MemoryRecord:
    return MemoryRecord(
        kind="error",
        quality=0.6,
        confidence=0.7,
        success_rate=0.0,
        usage=1,
        created_at=ts or time.time(),
        payload={"message": message},
    )


def _read_audit(path: str) -> list[dict]:
    """Read all JSONL rows from the audit file."""
    lines = Path(path).read_text().strip().split("\n")
    rows = []
    for line in lines:
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# Full-loop E2E
# ---------------------------------------------------------------------------


class TestLearningLoopE2E:
    """End-to-end test: error → promote → evaluate → decay → retire → audit."""

    def test_complete_learning_loop(self, tmp_path: Path):
        """Walk through every stage of the learning feedback loop
        with real subsystems and verify the audit trail is complete."""

        audit_path = str(tmp_path / "audit.jsonl")
        ledger_path = tmp_path / "ledger.jsonl"
        store = PolicyStore(audit_path=audit_path)
        synth = ReflectionSynthesizer(
            policy_store=store,
            min_occurrences=3,
            min_confidence=0.70,
            persist_path=ledger_path,
        )

        # -- Stage 1: Feed error records → trigger promotion --------

        now = time.time()
        records = [
            _error("db connection refused on shard 1", ts=now - 300),
            _error("db connection refused on shard 2", ts=now - 200),
            _error("db connection refused on shard 3", ts=now - 100),
        ]
        report = synth.run(records)

        assert report.patterns_promoted == 1, (
            "Expected exactly one pattern to be promoted"
        )
        assert len(report.rule_ids) == 1
        rule_id = report.rule_ids[0]
        assert rule_id.startswith("learned::")

        # SOFT rule should be in the store
        soft_rules = store.list_rules(tier=PolicyTier.SOFT)
        assert len(soft_rules) == 1
        assert soft_rules[0].rule_id == rule_id
        assert soft_rules[0].source == "learned"

        # Ledger file should record the promotion
        assert ledger_path.exists()
        ledger_rows = ledger_path.read_text().strip().split("\n")
        assert len(ledger_rows) == 1

        # -- Stage 2: evaluate_tiered() fires the learned rule ------

        # Build an action that matches the promoted pattern.
        # The default rule builder matches on kind + normalised text.
        action = {
            "kind": "error",
            "message": "db connection refused on shard 99",
            "action_type": "test_action",
        }
        decision = store.evaluate_tiered(action, {"source_engine": "test"})

        # The learned rule should have BLOCKed
        assert decision.verdict == PolicyVerdict.BLOCK, (
            f"Expected BLOCK from learned rule, got {decision.verdict}"
        )
        assert decision.final_rule_id == rule_id

        # Stats should reflect the match
        stats = store.get_rule_stats(rule_id)
        assert stats is not None
        assert stats["matches"] >= 1
        assert stats["blocks"] >= 1
        assert stats["last_matched_at"] is not None

        # -- Stage 3: Decay retires the stale rule ------------------

        # The pattern's last_seen is ~100s ago (now - 100), and
        # last_matched_at was just set by evaluate_tiered. To make
        # it stale, we decay with a 0-second idle window — anything
        # older than "right now" is stale.
        retired = synth.decay_stale_rules(max_idle_seconds=0.0, now=now + 1000)

        assert len(retired) == 1, (
            f"Expected exactly one retired signature, got {len(retired)}"
        )

        # Rule should be gone from the store
        soft_after = store.list_rules(tier=PolicyTier.SOFT)
        assert len(soft_after) == 0

        # Synthesizer should have forgotten it
        assert synth.promoted_signatures == []

        # Ledger should be rewritten to empty (surviving patterns = 0)
        ledger_text = ledger_path.read_text().strip()
        assert ledger_text == "", (
            "Ledger should be empty after all patterns were decayed"
        )

        # -- Stage 4: Verify audit trail completeness ---------------

        audit_rows = _read_audit(audit_path)
        assert len(audit_rows) >= 3, (
            f"Expected at least 3 audit entries (promotion + verdict + "
            f"retirement), got {len(audit_rows)}"
        )

        # Collect events by type
        promotions = [
            r for r in audit_rows if r.get("event") == "PROMOTION"
        ]
        verdicts = [
            r for r in audit_rows if "verdict" in r and "event" not in r
        ]
        retirements = [
            r for r in audit_rows if r.get("event") == "RETIREMENT"
        ]

        assert len(promotions) == 1, "Expected exactly one PROMOTION"
        assert promotions[0]["rule_id"] == rule_id
        assert promotions[0]["source"] == "learned"
        assert promotions[0]["tier"] == "soft"

        assert len(verdicts) >= 1, "Expected at least one verdict entry"
        # The verdict that BLOCKed should reference our rule
        block_verdicts = [
            v for v in verdicts
            if v.get("final_rule_id") == rule_id
            and v.get("verdict") == "block"
        ]
        assert len(block_verdicts) == 1, (
            "Expected exactly one BLOCK verdict from the learned rule"
        )

        assert len(retirements) == 1, "Expected exactly one RETIREMENT"
        assert retirements[0]["rule_id"] == rule_id
        # Retirement should carry stats from the rule's lifetime
        retirement_extra = retirements[0].get("extra", {})
        assert retirement_extra.get("matches", 0) >= 1
        assert retirement_extra.get("blocks", 0) >= 1

        # Verify chronological ordering: PROMOTION < verdict < RETIREMENT
        promo_idx = audit_rows.index(promotions[0])
        verdict_idx = audit_rows.index(block_verdicts[0])
        retire_idx = audit_rows.index(retirements[0])
        assert promo_idx < verdict_idx < retire_idx, (
            f"Expected PROMOTION({promo_idx}) < verdict({verdict_idx}) "
            f"< RETIREMENT({retire_idx})"
        )

    def test_re_learning_after_retirement(self, tmp_path: Path):
        """After a rule is retired, the same pattern can be re-learned
        from fresh errors — the forget-on-decay allows re-promotion."""

        audit_path = str(tmp_path / "audit.jsonl")
        ledger_path = tmp_path / "ledger.jsonl"
        store = PolicyStore(audit_path=audit_path)
        synth = ReflectionSynthesizer(
            policy_store=store,
            min_occurrences=3,
            persist_path=ledger_path,
        )

        now = time.time()

        # Session 1: promote + decay
        r1 = synth.run([
            _error("timeout on api call 1", ts=now),
            _error("timeout on api call 2", ts=now),
            _error("timeout on api call 3", ts=now),
        ])
        assert r1.patterns_promoted == 1
        first_rule_id = r1.rule_ids[0]

        synth.decay_stale_rules(max_idle_seconds=0.0, now=now + 10000)
        assert synth.promoted_signatures == []
        assert store.list_rules(tier=PolicyTier.SOFT) == []

        # Session 2: same pattern, fresh errors → re-promoted
        r2 = synth.run([
            _error("timeout on api call 4", ts=now + 20000),
            _error("timeout on api call 5", ts=now + 20000),
            _error("timeout on api call 6", ts=now + 20000),
        ])
        assert r2.patterns_promoted == 1
        # Same rule_id (deterministic from signature)
        assert r2.rule_ids[0] == first_rule_id
        assert len(store.list_rules(tier=PolicyTier.SOFT)) == 1

    def test_pending_patterns_visible_before_promotion(self, tmp_path: Path):
        """Patterns that clear one gate but not both surface as
        pending in the synthesis report."""

        store = PolicyStore(audit_path=str(tmp_path / "audit.jsonl"))
        synth = ReflectionSynthesizer(
            policy_store=store,
            min_occurrences=3,
            min_confidence=0.75,
        )

        # Two occurrences → Laplace smoothed confidence = 2/(2+1) = 0.667
        # Doesn't meet min_occurrences=3 but DOES have occurrences ≥ 1
        # Actually: meets neither since occ < 3 and conf < 0.75
        # Need a case where exactly one gate is met.
        # With min_occurrences=3, min_confidence=0.75:
        #   4 occurrences → conf = 4/5 = 0.80 ≥ 0.75 ✓, occ=4 ≥ 3 ✓ → promoted
        #   2 occurrences → conf = 2/3 = 0.667 < 0.75, occ=2 < 3 → neither
        # We need smoothing to help: with smoothing=4, 3 occ → conf = 3/7 = 0.43
        synth2 = ReflectionSynthesizer(
            policy_store=store,
            min_occurrences=3,
            min_confidence=0.75,
            smoothing=4.0,  # higher smoothing makes confidence climb slower
        )

        # 3 occurrences: occ ≥ 3 ✓, conf = 3/(3+4) = 0.43 < 0.75 → pending
        # Use numeric suffixes so the normaliser collapses them to one signature.
        report = synth2.run([
            _error("rate limit exceeded on endpoint 1"),
            _error("rate limit exceeded on endpoint 2"),
            _error("rate limit exceeded on endpoint 3"),
        ])
        assert report.patterns_promoted == 0
        assert len(report.pending_patterns) == 1
        assert report.pending_patterns[0].occurrences == 3

        # Verify last_report cache
        cached = synth2.last_report
        assert cached is not None
        assert cached.pending_patterns == report.pending_patterns

    def test_rehydration_preserves_full_loop_state(self, tmp_path: Path):
        """A promoted rule persisted to the ledger survives a full
        restart and continues to function in the policy store."""

        ledger = tmp_path / "ledger.jsonl"
        audit1 = str(tmp_path / "a1.jsonl")
        audit2 = str(tmp_path / "a2.jsonl")

        # Session 1: promote a pattern
        store1 = PolicyStore(audit_path=audit1)
        s1 = ReflectionSynthesizer(
            policy_store=store1, persist_path=ledger, min_occurrences=3,
        )
        r1 = s1.run([
            _error("ssl cert expired for host 1"),
            _error("ssl cert expired for host 2"),
            _error("ssl cert expired for host 3"),
        ])
        assert r1.patterns_promoted == 1
        rule_id = r1.rule_ids[0]

        # Session 2: fresh store + synth, same ledger
        store2 = PolicyStore(audit_path=audit2)
        s2 = ReflectionSynthesizer(
            policy_store=store2, persist_path=ledger, min_occurrences=3,
        )

        # Rule should be live in the new store
        soft = store2.list_rules(tier=PolicyTier.SOFT)
        assert len(soft) == 1
        assert soft[0].rule_id == rule_id

        # And it should fire on matching actions
        decision = store2.evaluate_tiered(
            {"kind": "error", "message": "ssl cert expired for host 99",
             "action_type": "test"},
            {"source_engine": "test"},
        )
        assert decision.verdict == PolicyVerdict.BLOCK
        assert decision.final_rule_id == rule_id

        # Feeding the same pattern again should NOT re-promote
        r2 = s2.run([
            _error("ssl cert expired for host 4"),
            _error("ssl cert expired for host 5"),
            _error("ssl cert expired for host 6"),
        ])
        assert r2.patterns_promoted == 0
