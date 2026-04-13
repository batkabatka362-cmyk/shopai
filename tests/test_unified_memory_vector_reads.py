"""Wave 4 #2: UnifiedMemory.retrieve augments legacy result with a
satellite vector lookup.

Wave 3 #3 wired every legacy *write* path (ingest / record_decision
/ record_mistake / record_failure) into the satellite vector layer,
but the *read* side — ``UnifiedMemory.retrieve`` — still only
called the brain backend, so semantically-similar records stored
in the vector layer were invisible to decision code.

Wave 4 #2 adds ``result["vector_matches"]`` to ``retrieve()``, a
list of ``{record_id, score, payload}`` tuples derived from a
cosine-similarity query built from the category + context. The
augmentation is additive (legacy fields untouched) and fails soft
(missing / broken satellites return ``[]``).
"""
from __future__ import annotations

from typing import Any

import pytest

from core.memory.satellite_layers import SatelliteRouter, VectorLayer
from core.memory.unified_memory import UnifiedMemory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seeded_memory(records: list[tuple[str, str, dict[str, Any]]]) -> UnifiedMemory:
    """Return a UnifiedMemory whose satellite vector layer contains
    hand-seeded records. Bypasses the classifier by writing directly
    to router.vector so we don't have to spin up a full route_record
    pipeline for a read-side test.
    """
    mem = UnifiedMemory()
    router = mem.get_satellites()
    assert isinstance(router, SatelliteRouter)
    assert router.vector.enabled  # no optional dep required
    for rid, content, payload in records:
        router.vector.add(rid, content, payload=payload)
    return mem


# ---------------------------------------------------------------------------
# Additive behavior
# ---------------------------------------------------------------------------


def test_retrieve_adds_vector_matches_key():
    mem = UnifiedMemory()
    result = mem.retrieve("pricing", {"product_id": "p1"})
    assert "vector_matches" in result
    assert isinstance(result["vector_matches"], list)


def test_retrieve_preserves_legacy_fields_when_no_brain():
    mem = UnifiedMemory()
    # No brain backend wired in unit test env — should still return
    # the canonical empty legacy shape alongside vector_matches
    result = mem.retrieve("marketing", {})
    for key in ("best_cases", "failures", "rules", "patterns"):
        assert key in result
    assert "total_memories" in result
    assert "vector_matches" in result


# ---------------------------------------------------------------------------
# Semantic hits
# ---------------------------------------------------------------------------


def test_retrieve_surfaces_seeded_vector_records():
    mem = _seeded_memory([
        ("r1", "pricing strategy margin floor check",
         {"kind": "decision", "action": "raise 10%"}),
        ("r2", "inventory stockout reorder",
         {"kind": "decision", "action": "reorder"}),
        ("r3", "pricing margin analysis comp data",
         {"kind": "decision", "action": "raise 5%"}),
    ])
    result = mem.retrieve("pricing", {"focus": "margin"})
    hits = result["vector_matches"]
    # Pricing records should win over the inventory one
    assert len(hits) >= 2
    ids = [h["record_id"] for h in hits]
    assert "r1" in ids
    assert "r3" in ids
    # Top hit has a positive score
    assert hits[0]["score"] > 0.0


def test_retrieve_ranks_by_cosine_similarity_descending():
    mem = _seeded_memory([
        ("a", "alpha alpha alpha", {}),
        ("b", "beta beta beta", {}),
        ("c", "alpha beta", {}),
    ])
    result = mem.retrieve("alpha", {})
    hits = result["vector_matches"]
    # Scores should be monotonically non-increasing
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True)
    # Top hit is "a" (all tokens match)
    assert hits[0]["record_id"] == "a"


# ---------------------------------------------------------------------------
# Fail-safe paths
# ---------------------------------------------------------------------------


def test_retrieve_returns_empty_vector_matches_when_router_missing():
    mem = UnifiedMemory()
    mem._satellites = None  # type: ignore[assignment]
    result = mem.retrieve("anything", {})
    assert result["vector_matches"] == []


def test_retrieve_absorbs_vector_search_crash():
    mem = UnifiedMemory()

    class _BoomVector:
        enabled = True
        def search(self, *a, **kw):
            raise RuntimeError("vector down")

    mem._satellites.vector = _BoomVector()  # type: ignore[assignment]
    result = mem.retrieve("x", {"k": 1})
    assert result["vector_matches"] == []


def test_retrieve_skips_disabled_vector_backend():
    mem = UnifiedMemory()

    class _DisabledVector:
        enabled = False
        def search(self, *a, **kw):  # should never be called
            raise AssertionError("search called on disabled backend")

    mem._satellites.vector = _DisabledVector()  # type: ignore[assignment]
    result = mem.retrieve("x", {})
    assert result["vector_matches"] == []


# ---------------------------------------------------------------------------
# Query construction
# ---------------------------------------------------------------------------


def test_build_vector_query_flattens_scalar_and_list_context():
    q = UnifiedMemory._build_vector_query(
        "pricing",
        {"sku": "HAT-1", "units": 3, "tags": ["win", "margin"]},
    )
    assert "pricing" in q
    assert "sku HAT-1" in q
    assert "units 3" in q
    assert "tags win margin" in q


def test_build_vector_query_ignores_none_values():
    q = UnifiedMemory._build_vector_query(
        "x", {"keep": "yes", "drop": None},
    )
    assert "keep yes" in q
    assert "drop" not in q


def test_build_vector_query_returns_empty_when_nothing_to_say():
    assert UnifiedMemory._build_vector_query("", {}) == ""
    assert UnifiedMemory._build_vector_query("", {"a": None}) == ""


# ---------------------------------------------------------------------------
# End-to-end: legacy write path feeds vector → retrieve finds it
# ---------------------------------------------------------------------------


def test_record_decision_then_retrieve_sees_it_via_vector():
    mem = UnifiedMemory()
    for i in range(4):
        mem.record_decision(
            "pricing",
            {"sku": f"HAT-{i}"},
            action=f"raise margin floor step {i}",
            result={"ok": True},
            score=4.5,
        )
    result = mem.retrieve("pricing", {"focus": "margin"})
    hits = result["vector_matches"]
    assert len(hits) >= 1
    # At least one hit should have decision kind in its payload
    assert any(h["payload"].get("kind") == "decision" for h in hits)
