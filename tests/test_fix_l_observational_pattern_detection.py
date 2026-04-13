"""Regression tests for Fix L: observational ingest
triggers pattern detection.

Pre-fix, ``IntelligentMemory.ingest()`` stored raw data
into L1/L2 but never called ``_detect_patterns()``. That
only ran from ``record_decision()`` (the L3 path). So
observational data flowing through the think() cycle
(products, orders, customers) never graduated to L4
patterns or L5 rules — the pattern→rule feedback loop
was broken for non-decision observations.

Core audit re-scan flagged this as the #5 HIGH weakness.
Fix L calls ``_detect_patterns`` at the end of ``ingest()``
for high-quality data (score >= 3, which is the L2 tier).
This closes the observational loop:

    data → ingest → L2 features → L4 patterns (per ingest)
    → L5 rules (at frequency=3) → DecisionEngine boost

Critical invariant: ``record_decision()`` behaviour must
NOT change. It already called ``_detect_patterns`` once.
Fix L only adds a second call site inside ``ingest``.
"""
from __future__ import annotations

import tempfile

import pytest


@pytest.fixture
def fresh_memory(tmp_path, monkeypatch):
    """Give each test a private IntelligentMemory backed by
    a disposable SQLite file so patterns don't carry over
    from other tests or from production state."""
    from core.brain.memory import IntelligentMemory
    db_path = tmp_path / "fix_l_memory.db"
    mem = IntelligentMemory(db_path=str(db_path))
    return mem


class TestIngestTriggersPatternDetection:
    def test_ingest_creates_pattern_row(self, fresh_memory):
        """Three ingests of similar high-quality data must
        produce a pattern row with frequency >= 3."""
        mem = fresh_memory
        for _ in range(3):
            mem.ingest("product", {
                "id": "widget", "name": "Widget",
                "price": 99.99, "cost": 30.0,
                "inventory_quantity": 50,
                "status": "active",
                "vendor": "ACME",
                "tags": ["hot"],
            }, source="test_cycle")

        conn = mem._conn()
        row = conn.execute(
            "SELECT COUNT(*) as c FROM patterns WHERE category = ?",
            ("product",),
        ).fetchone()
        assert row["c"] >= 1, (
            "expected at least one pattern row from 3 similar "
            "ingests; observational pattern detection did not fire"
        )

    def test_ingest_pattern_frequency_increments(self, fresh_memory):
        mem = fresh_memory
        # Ingest 4 identical rows — frequency should be 4
        # for the resulting pattern
        payload = {
            "id": "x", "name": "X", "price": 50.0, "cost": 20.0,
            "inventory_quantity": 10, "status": "active",
        }
        for _ in range(4):
            mem.ingest("product", payload, source="t")
        conn = mem._conn()
        row = conn.execute(
            "SELECT MAX(frequency) as f FROM patterns WHERE category = ?",
            ("product",),
        ).fetchone()
        assert (row["f"] or 0) >= 3, (
            f"expected max frequency >= 3 from 4 ingests, got {row['f']}"
        )

    def test_ingest_graduates_to_rule_at_frequency_3(self, fresh_memory):
        """The L4 → L5 promotion path must fire: three
        matching observations should produce at least one
        rule row."""
        mem = fresh_memory
        payload = {
            "id": "g", "name": "Gadget", "price": 80.0, "cost": 30.0,
            "inventory_quantity": 20, "status": "active",
            "vendor": "SuperCo",
        }
        for _ in range(3):
            mem.ingest("product", payload, source="t")
        conn = mem._conn()
        row = conn.execute(
            "SELECT COUNT(*) as c FROM rules WHERE category = ?",
            ("product",),
        ).fetchone()
        assert row["c"] >= 1, (
            "L5 rule generation did not fire after 3 matching "
            "ingests — observational graduation broken"
        )

    def test_low_quality_ingest_skips_pattern_detection(self, fresh_memory):
        """Ingests with quality score < 3 should NOT trigger
        pattern detection — we only want high-signal
        observations graduating."""
        mem = fresh_memory
        # Tiny payload → score < 3
        for _ in range(3):
            mem.ingest("product", {"id": "low"}, source="t")
        conn = mem._conn()
        row = conn.execute(
            "SELECT COUNT(*) as c FROM patterns WHERE category = ?",
            ("product",),
        ).fetchone()
        # We allow 0 or any; the point is that low-quality
        # data shouldn't flood the pattern table. This test
        # pins the "only high-quality graduates" invariant.
        # Strictly speaking the pre-fix path wrote 0, so
        # we assert 0 here.
        assert row["c"] == 0, (
            "low-quality ingest (score < 3) should not "
            "create pattern rows"
        )

    def test_ingest_still_returns_memory_id(self, fresh_memory):
        """Sanity: pattern-detection side effect must not
        change the existing return contract of ``ingest``."""
        mem = fresh_memory
        mid = mem.ingest("product", {
            "id": "p1", "name": "W", "price": 50, "cost": 20,
            "status": "active", "inventory_quantity": 5,
        }, source="t")
        assert isinstance(mid, int)
        assert mid > 0


class TestRecordDecisionStillTriggersPatterns:
    """Regression guard: Fix L must not break the existing
    L3 → L4 path from ``record_decision``."""

    def test_record_decision_still_detects_patterns(self, fresh_memory):
        mem = fresh_memory
        for _ in range(3):
            mem.record_decision(
                "pricing",
                {"price": 100, "cost": 40, "margin": 0.6},
                action="raise_10pct",
                result={"new_price": 110},
                score=4.5,
            )
        conn = mem._conn()
        row = conn.execute(
            "SELECT COUNT(*) as c FROM patterns WHERE category = ?",
            ("pricing",),
        ).fetchone()
        assert row["c"] >= 1


class TestEndToEndObservationalLoop:
    """Integration: full brain cycle ingests data and should
    populate patterns from observation alone."""

    def test_brain_think_populates_patterns_from_ingest(self, tmp_path, monkeypatch):
        """Run brain.think() with a small data set repeatedly
        and assert that the underlying memory sees patterns
        from the ingest path — not just from record_decision."""
        from core.brain.memory import IntelligentMemory
        # Inject a fresh memory into the unified memory so
        # the brain picks it up
        db = tmp_path / "loop.db"
        mem = IntelligentMemory(db_path=str(db))

        from core.memory import unified_memory as um
        # Reset unified memory singleton and force it to use
        # our fresh backend. We directly set the internal
        # brain backend after initialization.
        um._instance = None
        unified = um.get_unified_memory()
        unified._ensure_init()
        unified._brain = mem

        from core.brain.decision_brain import DecisionBrain
        brain = DecisionBrain()
        brain._init_components()
        # Force the brain's memory to our isolated backend
        brain._brain_memory = mem

        data = {
            "products": [{
                "id": "p1", "name": "Widget",
                "price": 50.0, "cost": 20.0,
                "inventory_quantity": 10,
                "status": "active", "vendor": "ACME",
            }],
            "orders": [{"id": "o1", "total": 50.0,
                        "financial_status": "paid"}],
            "customers": [],
        }
        # Three cycles — each ingests products + orders
        brain.think(dict(data, store_id="s1"))
        brain._last_ingest = None  # force re-ingest
        brain.think(dict(data, store_id="s2"))
        brain._last_ingest = None
        brain.think(dict(data, store_id="s3"))

        conn = mem._conn()
        row = conn.execute(
            "SELECT COUNT(*) as c FROM patterns",
        ).fetchone()
        assert row["c"] >= 1, (
            "observational ingest through brain.think did not "
            "produce any pattern rows — Fix L wiring broken"
        )
