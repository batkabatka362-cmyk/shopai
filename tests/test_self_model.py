"""Tests for the introspective SelfModel.

Covers the three responsibilities of the module:

1. Recording assessments with weighted averaging + confidence growth
2. Ingesting real data (cycle results, memory rules) into assessments
3. Reading the rolled-up view (strengths, weaknesses, gaps, narrative)
"""
import math
import tempfile
import time

import pytest


def _fresh():
    """Return a SelfModel backed by a temp SQLite file — no shared state."""
    from core.cognitive.self_model import SelfModel
    return SelfModel(db_path=tempfile.mktemp(suffix=".db"))


class TestAssess:
    def test_single_assessment_stores_capability(self):
        sm = _fresh()
        sm.assess("engine.product_research", 0.8, source="test")
        cap = sm.get_capability("engine.product_research")
        assert cap is not None
        assert cap["score"] == pytest.approx(0.8)
        assert cap["evidence_count"] == 1
        assert 0.0 < cap["confidence"] < 0.2

    def test_weighted_average_of_two_assessments(self):
        sm = _fresh()
        sm.assess("x", 1.0, evidence_count=1)
        sm.assess("x", 0.0, evidence_count=1)
        cap = sm.get_capability("x")
        # Equal weights → mean 0.5
        assert cap["score"] == pytest.approx(0.5)
        assert cap["evidence_count"] == 2

    def test_weighted_by_evidence_count(self):
        sm = _fresh()
        sm.assess("x", 1.0, evidence_count=9)   # weight 9
        sm.assess("x", 0.0, evidence_count=1)   # weight 1
        cap = sm.get_capability("x")
        # (1.0*9 + 0.0*1) / 10 = 0.9
        assert cap["score"] == pytest.approx(0.9)
        assert cap["evidence_count"] == 10

    def test_score_clamped_to_0_1(self):
        sm = _fresh()
        sm.assess("x", 1.5)
        sm.assess("y", -0.5)
        assert sm.get_capability("x")["score"] == pytest.approx(1.0)
        assert sm.get_capability("y")["score"] == pytest.approx(0.0)

    def test_empty_name_ignored(self):
        sm = _fresh()
        sm.assess("", 0.5)
        assert sm.capabilities() == []

    def test_confidence_grows_with_evidence(self):
        sm = _fresh()
        sm.assess("slow", 0.5, evidence_count=1)
        c1 = sm.get_capability("slow")["confidence"]
        for _ in range(30):
            sm.assess("slow", 0.5, evidence_count=1)
        c2 = sm.get_capability("slow")["confidence"]
        assert c2 > c1
        # Should be near-saturated but never exactly 1.0
        assert 0.9 < c2 < 1.0

    def test_assessment_audit_log(self):
        sm = _fresh()
        sm.assess("x", 0.2, source="first")
        sm.assess("x", 0.8, source="second")
        log = sm.assessment_log("x")
        assert len(log) == 2
        # Most recent first
        assert log[0]["source"] == "second"
        assert log[1]["source"] == "first"

    def test_audit_log_unfiltered(self):
        sm = _fresh()
        sm.assess("a", 0.5)
        sm.assess("b", 0.5)
        log = sm.assessment_log(limit=10)
        caps = {e["capability"] for e in log}
        assert caps == {"a", "b"}


class TestIngestCycleResult:
    def _cycle(self, phases=None, executions=None, status="success"):
        return {
            "status": status,
            "phases": phases or {},
            "executions": executions or [],
        }

    def test_phase_duration_mapped_to_score(self):
        sm = _fresh()
        cycle = self._cycle(phases={
            "data":    {"duration_s": 2.0},   # boundary → 1.0
            "analyze": {"duration_s": 11.0},  # midpoint → 0.5
            "decide":  {"duration_s": 20.0},  # upper bound → 0.0
        })
        sm.ingest_cycle_result(cycle)
        assert sm.get_capability("phase.data")["score"] == pytest.approx(1.0)
        assert sm.get_capability("phase.analyze")["score"] == pytest.approx(0.5)
        assert sm.get_capability("phase.decide")["score"] == pytest.approx(0.0)

    def test_execution_success_rate_per_engine(self):
        sm = _fresh()
        cycle = self._cycle(executions=[
            {"engine": "a", "status": "success"},
            {"engine": "a", "status": "success"},
            {"engine": "a", "status": "error"},
            {"engine": "b", "status": "success"},
        ])
        sm.ingest_cycle_result(cycle)
        # engine.a: 2/3 ≈ 0.667
        assert sm.get_capability("engine.a")["score"] == pytest.approx(2 / 3)
        assert sm.get_capability("engine.a")["evidence_count"] == 3
        # engine.b: 1/1
        assert sm.get_capability("engine.b")["score"] == pytest.approx(1.0)

    def test_cycle_completion_success(self):
        sm = _fresh()
        sm.ingest_cycle_result(self._cycle(status="success"))
        cap = sm.get_capability("autonomy.cycle_completion")
        assert cap["score"] == pytest.approx(1.0)

    def test_cycle_completion_failure(self):
        sm = _fresh()
        sm.ingest_cycle_result(self._cycle(status="error"))
        cap = sm.get_capability("autonomy.cycle_completion")
        assert cap["score"] == pytest.approx(0.0)

    def test_non_dict_cycle_result_is_noop(self):
        sm = _fresh()
        assert sm.ingest_cycle_result("not a dict") == 0  # type: ignore
        assert sm.capabilities() == []

    def test_unparseable_duration_skipped(self):
        sm = _fresh()
        sm.ingest_cycle_result(self._cycle(
            phases={"weird": {"duration_s": "not a number"}},
        ))
        assert sm.get_capability("phase.weird") is None

    def test_engine_key_fallback_to_name(self):
        sm = _fresh()
        sm.ingest_cycle_result(self._cycle(executions=[
            {"name": "fallback_engine", "status": "success"},
        ]))
        assert sm.get_capability("engine.fallback_engine") is not None

    def test_returns_count_of_assessments_written(self):
        sm = _fresh()
        n = sm.ingest_cycle_result(self._cycle(
            phases={"p1": {"duration_s": 1.0}, "p2": {"duration_s": 1.0}},
            executions=[{"engine": "e1", "status": "success"}],
            status="success",
        ))
        # 2 phases + 1 engine + 1 completion = 4
        assert n == 4


class TestIngestMemoryStats:
    class _FakeMemory:
        def __init__(self, rules):
            self._rules = rules

        def get_rules(self):
            return self._rules

    def test_extracts_per_category_knowledge(self):
        sm = _fresh()
        mem = self._FakeMemory([
            {"category": "pricing", "confidence": 0.9},
            {"category": "pricing", "confidence": 0.85},
            {"category": "marketing", "confidence": 0.3},
        ])
        n = sm.ingest_memory_stats(mem)
        assert n == 2
        pricing = sm.get_capability("knowledge.pricing")
        assert pricing["score"] == pytest.approx((0.9 + 0.85) / 2)
        assert pricing["evidence_count"] == 2
        marketing = sm.get_capability("knowledge.marketing")
        assert marketing["score"] == pytest.approx(0.3)

    def test_none_memory_is_safe(self):
        sm = _fresh()
        assert sm.ingest_memory_stats(None) == 0

    def test_get_rules_failure_is_safe(self):
        sm = _fresh()

        class Broken:
            def get_rules(self):
                raise RuntimeError("db down")

        assert sm.ingest_memory_stats(Broken()) == 0


class TestReadAPI:
    def _populated(self):
        sm = _fresh()
        # Three strong capabilities (10 observations each, score ~0.9)
        for name in ("engine.alpha", "engine.beta", "engine.gamma"):
            sm.assess(name, 0.9, evidence_count=10)
        # Two weak capabilities
        sm.assess("engine.bad", 0.2, evidence_count=10)
        sm.assess("engine.worse", 0.1, evidence_count=10)
        # One knowledge gap: low evidence, mid score
        sm.assess("engine.unknown", 0.5, evidence_count=1)
        return sm

    def test_capabilities_ordered_by_score(self):
        sm = self._populated()
        caps = sm.capabilities()
        scores = [c["score"] for c in caps]
        assert scores == sorted(scores, reverse=True)

    def test_strengths_returns_only_high_score_high_confidence(self):
        sm = self._populated()
        strengths = sm.strengths(top_n=10)
        names = {c["name"] for c in strengths}
        assert {"engine.alpha", "engine.beta", "engine.gamma"} == names

    def test_weaknesses(self):
        sm = self._populated()
        weaknesses = sm.weaknesses(top_n=10)
        names = {c["name"] for c in weaknesses}
        assert {"engine.bad", "engine.worse"} == names

    def test_knowledge_gaps_are_low_confidence(self):
        sm = self._populated()
        gaps = sm.knowledge_gaps(top_n=10)
        names = {c["name"] for c in gaps}
        # engine.unknown has only 1 observation → confidence ≈ 0.10
        assert "engine.unknown" in names
        # Strong items have confidence ~0.76 → not gaps
        assert "engine.alpha" not in names

    def test_confidence_shortcut(self):
        sm = self._populated()
        assert sm.confidence("engine.alpha") > 0.5
        assert sm.confidence("nonexistent") == 0.0

    def test_get_capability_nonexistent(self):
        sm = _fresh()
        assert sm.get_capability("ghost") is None


class TestSnapshot:
    def test_snapshot_captures_current_state(self):
        sm = _fresh()
        sm.assess("engine.a", 0.9, evidence_count=20)
        sm.assess("engine.b", 0.2, evidence_count=20)
        snap = sm.snapshot()
        assert snap["capability_count"] == 2
        assert snap["avg_score"] == pytest.approx((0.9 + 0.2) / 2)
        assert any(s["name"] == "engine.a" for s in snap["strengths"])
        assert any(w["name"] == "engine.b" for w in snap["weaknesses"])

    def test_history_returns_past_snapshots(self):
        sm = _fresh()
        sm.assess("x", 0.8, evidence_count=10)
        sm.snapshot()
        time.sleep(0.01)
        sm.assess("y", 0.9, evidence_count=10)
        sm.snapshot()
        hist = sm.history()
        assert len(hist) == 2
        # Most recent first
        assert hist[0]["capability_count"] == 2
        assert hist[1]["capability_count"] == 1
        # Snapshots expose parsed lists, not *_json fields
        assert "strengths" in hist[0]
        assert isinstance(hist[0]["strengths"], list)

    def test_history_limit(self):
        sm = _fresh()
        for _ in range(5):
            sm.snapshot()
        hist = sm.history(limit=3)
        assert len(hist) == 3


class TestNarrative:
    def test_empty_narrative(self):
        sm = _fresh()
        narr = sm.narrative()
        assert "no data" in narr.lower()

    def test_narrative_mentions_strength(self):
        sm = _fresh()
        sm.assess("engine.shining", 0.9, evidence_count=20)
        narr = sm.narrative()
        assert "engine.shining" in narr
        assert "strength" in narr.lower()

    def test_narrative_mentions_weakness_and_gap(self):
        sm = _fresh()
        sm.assess("engine.broken", 0.1, evidence_count=20)
        sm.assess("engine.unknown", 0.5, evidence_count=1)
        narr = sm.narrative()
        assert "engine.broken" in narr
        assert "weakness" in narr.lower()
        assert "engine.unknown" in narr
        assert "uncertain" in narr.lower()


class TestConfidenceFormula:
    def test_zero_evidence_is_zero_confidence(self):
        from core.cognitive.self_model import SelfModel
        assert SelfModel._confidence_from_evidence(0) == 0.0

    def test_one_observation_is_low_confidence(self):
        from core.cognitive.self_model import SelfModel
        c = SelfModel._confidence_from_evidence(1)
        assert 0.05 < c < 0.15

    def test_thirty_observations_is_near_saturation(self):
        from core.cognitive.self_model import SelfModel
        c = SelfModel._confidence_from_evidence(30)
        assert 0.98 < c < 1.0

    def test_confidence_monotonic(self):
        from core.cognitive.self_model import SelfModel
        prev = -1
        for n in range(0, 50, 5):
            c = SelfModel._confidence_from_evidence(n)
            assert c > prev
            prev = c


class TestSingleton:
    def test_get_self_model_cached(self):
        from core.cognitive import self_model as mod
        mod._instance = None
        a = mod.get_self_model()
        b = mod.get_self_model()
        assert a is b
