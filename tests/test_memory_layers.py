"""Tests for core.memory.satellite_layers (Wave 2 #4).

Covers the three satellite layers (VectorLayer, GraphLayer,
SignalLayer), the SatelliteRouter that wires them together,
and the UnifiedMemory.ingest_quality entry point that feeds
records in after quality-engine classification.

Tests run against the pure-Python fallback implementations
so no optional deps (sqlite-vec / networkx / duckdb) are
required to exercise the behaviour.
"""
from __future__ import annotations

import pytest

from core.memory.quality_engine import MemoryClass, MemoryRecord
from core.memory.satellite_layers import (
    GraphLayer,
    SatelliteRouter,
    SignalLayer,
    VectorLayer,
)
from core.memory.unified_memory import UnifiedMemory


# ---------------------------------------------------------------------------
# VectorLayer
# ---------------------------------------------------------------------------


def test_vector_layer_empty_search_returns_empty():
    v = VectorLayer()
    assert v.search("anything") == []


def test_vector_layer_add_and_search_ranks_relevant_first():
    v = VectorLayer()
    v.add("r1", "Shopify price changes affect conversion rates")
    v.add("r2", "Instagram ads for jewellery store")
    v.add("r3", "Conversion rate optimisation on landing page")
    results = v.search("conversion rate", k=3)
    assert results, "expected at least one result"
    top_ids = [rid for rid, _, _ in results]
    # r1 and r3 both mention "conversion rate"; r2 does not
    assert "r1" in top_ids[:2]
    assert "r3" in top_ids[:2]
    assert "r2" not in top_ids[:2]


def test_vector_layer_search_scores_descending():
    v = VectorLayer()
    v.add("a", "alpha beta gamma")
    v.add("b", "alpha beta")
    v.add("c", "alpha")
    results = v.search("alpha beta gamma", k=3)
    scores = [s for _, s, _ in results]
    assert scores == sorted(scores, reverse=True)
    assert results[0][0] == "a"  # perfect match


def test_vector_layer_handles_dict_content():
    v = VectorLayer()
    v.add("r1", {"title": "Email campaign", "body": "Welcome new customers"})
    results = v.search("welcome customers", k=1)
    assert results and results[0][0] == "r1"


def test_vector_layer_disabled_is_noop():
    v = VectorLayer(enabled=False)
    v.add("r1", "anything")
    assert v.search("anything") == []
    assert v.stats()["enabled"] is False
    assert v.stats()["total"] == 0


def test_vector_layer_remove():
    v = VectorLayer()
    v.add("r1", "hello world")
    assert v.remove("r1") is True
    assert v.remove("r1") is False
    assert v.search("hello") == []


def test_vector_layer_min_score_filters():
    v = VectorLayer()
    v.add("a", "alpha")
    v.add("b", "beta")
    # Query "alpha" against "beta" → cosine 0 → filtered
    results = v.search("alpha", k=5, min_score=0.01)
    ids = [rid for rid, _, _ in results]
    assert "a" in ids
    assert "b" not in ids


def test_vector_layer_empty_content_skipped():
    v = VectorLayer()
    v.add("r1", "")
    v.add("r2", None)
    v.add("r3", "real content here")
    results = v.search("content", k=3)
    assert [r for r, _, _ in results] == ["r3"]


# ---------------------------------------------------------------------------
# GraphLayer
# ---------------------------------------------------------------------------


def test_graph_layer_add_entities_and_neighbours():
    g = GraphLayer()
    g.add_entity("prod-1", kind="product")
    g.add_entity("camp-1", kind="campaign")
    g.add_relation("camp-1", "prod-1", rel_type="promotes")
    assert g.neighbors("camp-1", direction="out") == ["prod-1"]
    assert g.neighbors("prod-1", direction="in") == ["camp-1"]
    assert g.neighbors("camp-1", direction="both") == ["prod-1"]


def test_graph_layer_auto_creates_endpoints():
    g = GraphLayer()
    g.add_relation("a", "b", rel_type="linked")
    assert g.get_entity("a") is not None
    assert g.get_entity("b") is not None
    rel = g.get_relation("a", "b")
    assert rel and rel["rel_type"] == "linked"


def test_graph_layer_shortest_path():
    g = GraphLayer()
    for a, b in [("a", "b"), ("b", "c"), ("c", "d"), ("a", "x")]:
        g.add_relation(a, b, rel_type="next")
    path = g.shortest_path("a", "d")
    assert path == ["a", "b", "c", "d"]


def test_graph_layer_shortest_path_none_when_disconnected():
    g = GraphLayer()
    g.add_relation("a", "b")
    g.add_entity("z")
    assert g.shortest_path("a", "z") is None


def test_graph_layer_shortest_path_unknown_node():
    g = GraphLayer()
    g.add_relation("a", "b")
    assert g.shortest_path("a", "missing") is None


def test_graph_layer_shortest_path_self():
    g = GraphLayer()
    g.add_entity("a")
    assert g.shortest_path("a", "a") == ["a"]


def test_graph_layer_neighbors_unknown_direction_raises():
    g = GraphLayer()
    g.add_entity("a")
    with pytest.raises(ValueError):
        g.neighbors("a", direction="sideways")


def test_graph_layer_disabled_is_noop():
    g = GraphLayer(enabled=False)
    g.add_entity("a")
    g.add_relation("a", "b")
    assert g.get_entity("a") is None
    assert g.neighbors("a") == []
    assert g.stats()["nodes"] == 0


def test_graph_layer_stats_report_backend():
    g = GraphLayer()
    s = g.stats()
    assert s["backend"] in ("networkx", "memory")
    assert s["nodes"] == 0
    assert s["edges"] == 0


# ---------------------------------------------------------------------------
# SignalLayer
# ---------------------------------------------------------------------------


def test_signal_layer_record_and_query():
    s = SignalLayer()
    s.record("latency_ms", 120.0, ts=100.0)
    s.record("latency_ms", 140.0, ts=200.0)
    s.record("other", 1.0, ts=150.0)
    pts = s.query("latency_ms")
    assert [p.value for p in pts] == [120.0, 140.0]


def test_signal_layer_query_since():
    s = SignalLayer()
    s.record("m", 1.0, ts=10.0)
    s.record("m", 2.0, ts=20.0)
    s.record("m", 3.0, ts=30.0)
    pts = s.query("m", since=15.0)
    assert [p.value for p in pts] == [2.0, 3.0]


def test_signal_layer_query_tags():
    s = SignalLayer()
    s.record("m", 1.0, tags={"store": "A"}, ts=10.0)
    s.record("m", 2.0, tags={"store": "B"}, ts=20.0)
    s.record("m", 3.0, tags={"store": "A"}, ts=30.0)
    pts = s.query("m", tags={"store": "A"})
    assert [p.value for p in pts] == [1.0, 3.0]


def test_signal_layer_aggregate():
    s = SignalLayer()
    for v, t in [(1.0, 1), (3.0, 2), (5.0, 3)]:
        s.record("m", v, ts=float(t))
    agg = s.aggregate("m")
    assert agg["count"] == 3.0
    assert agg["sum"] == 9.0
    assert agg["min"] == 1.0
    assert agg["max"] == 5.0
    assert agg["mean"] == 3.0


def test_signal_layer_aggregate_empty():
    s = SignalLayer()
    agg = s.aggregate("never_recorded")
    assert agg["count"] == 0
    assert agg["mean"] == 0.0


def test_signal_layer_disabled_is_noop():
    s = SignalLayer(enabled=False)
    s.record("m", 1.0)
    assert s.query("m") == []
    assert s.aggregate("m")["count"] == 0


def test_signal_layer_max_points_cap():
    s = SignalLayer(max_points=3)
    for v in range(10):
        s.record("m", float(v), ts=float(v))
    pts = s.query("m")
    # Only the last 3 fit
    assert [p.value for p in pts] == [7.0, 8.0, 9.0]


# ---------------------------------------------------------------------------
# SatelliteRouter — quality-class dispatch
# ---------------------------------------------------------------------------


def test_router_knowledge_goes_to_vector_and_graph():
    router = SatelliteRouter()
    rec = MemoryRecord(kind="rule", quality=0.9, confidence=0.9)
    report = router.route_record(
        rec,
        memory_class=MemoryClass.KNOWLEDGE,
        content="raise price when stock is low",
        entities=["product-42", "price-strategy"],
    )
    assert set(report["routed_to"]) == {"vector", "graph"}
    # Record id defaults to "<kind>:<created_at>"
    rid = report["record_id"]
    assert rid.startswith("rule:")
    # Vector got it
    results = router.vector.search("raise price")
    assert any(r == rid for r, _, _ in results)
    # Graph linked the entities
    assert "product-42" in router.graph.neighbors(rid, direction="out")
    assert "price-strategy" in router.graph.neighbors(rid, direction="out")
    # Chained co_mentioned edge between the two entities
    assert "price-strategy" in router.graph.neighbors(
        "product-42", direction="out",
    )


def test_router_error_also_indexed_in_vector_and_graph():
    router = SatelliteRouter()
    rec = MemoryRecord(kind="error")
    report = router.route_record(
        rec,
        memory_class=MemoryClass.ERROR,
        content="timeout calling shopify api",
        entities=["shopify_api"],
    )
    assert set(report["routed_to"]) == {"vector", "graph"}
    results = router.vector.search("timeout")
    assert results


def test_router_signal_goes_to_signal_layer():
    router = SatelliteRouter()
    rec = MemoryRecord(kind="metric", created_at=1_000.0)
    report = router.route_record(
        rec,
        memory_class=MemoryClass.SIGNAL,
        content=None,
        signal_name="checkout_latency_ms",
        signal_value=123.0,
    )
    assert report["routed_to"] == ["signal"]
    pts = router.signal.query("checkout_latency_ms")
    assert len(pts) == 1
    assert pts[0].value == 123.0
    assert pts[0].tags["kind"] == "metric"
    assert pts[0].tags["class"] == "signal"


def test_router_signal_missing_name_skips_silently():
    router = SatelliteRouter()
    rec = MemoryRecord(kind="metric")
    report = router.route_record(
        rec,
        memory_class=MemoryClass.SIGNAL,
        content=None,
        signal_name=None,  # missing
        signal_value=None,
    )
    # Signal couldn't be recorded, so nothing is routed
    assert report["routed_to"] == []


def test_router_noise_routes_to_nothing():
    router = SatelliteRouter()
    rec = MemoryRecord(kind="debug", quality=0.1, confidence=0.1)
    report = router.route_record(
        rec,
        memory_class=MemoryClass.NOISE,
        content="debug trace line",
    )
    assert report["routed_to"] == []
    # Satellites remain empty
    assert router.vector.stats()["total"] == 0
    assert router.graph.stats()["nodes"] == 0
    assert router.signal.stats()["points"] == 0


def test_router_explicit_record_id():
    router = SatelliteRouter()
    rec = MemoryRecord(kind="rule")
    report = router.route_record(
        rec,
        record_id="custom-id",
        memory_class=MemoryClass.KNOWLEDGE,
        content="hello",
    )
    assert report["record_id"] == "custom-id"


def test_router_stats_aggregates_layers():
    router = SatelliteRouter()
    stats = router.stats()
    assert set(stats.keys()) == {"vector", "graph", "signal"}
    assert stats["vector"]["total"] == 0


# ---------------------------------------------------------------------------
# UnifiedMemory.ingest_quality integration
# ---------------------------------------------------------------------------


def test_unified_memory_exposes_satellites():
    um = UnifiedMemory()
    router = um.get_satellites()
    assert isinstance(router, SatelliteRouter)


def test_unified_memory_ingest_quality_knowledge():
    um = UnifiedMemory()
    report = um.ingest_quality(
        kind="rule",
        content="always confirm order before fulfilment",
        quality=0.9,
        confidence=0.9,
    )
    assert report["class"] == "knowledge"
    assert "vector" in report["routed_to"]
    assert "graph" in report["routed_to"]
    # The record now shows up in vector search
    results = um.get_satellites().vector.search("confirm order")
    assert results


def test_unified_memory_ingest_quality_signal():
    um = UnifiedMemory()
    report = um.ingest_quality(
        kind="metric",
        content=None,
        signal_name="api_latency_ms",
        signal_value=42.0,
    )
    assert report["class"] == "signal"
    assert "signal" in report["routed_to"]
    pts = um.get_satellites().signal.query("api_latency_ms")
    assert len(pts) == 1


def test_unified_memory_ingest_quality_noise_dropped():
    um = UnifiedMemory()
    report = um.ingest_quality(
        kind="debug", content="noisy line", quality=0.1, confidence=0.1,
    )
    assert report["class"] == "noise"
    assert report["routed_to"] == []


def test_unified_memory_set_satellites_allows_injection():
    um = UnifiedMemory()
    custom = SatelliteRouter(
        vector=VectorLayer(enabled=False),
        graph=GraphLayer(enabled=False),
        signal=SignalLayer(enabled=False),
    )
    um.set_satellites(custom)
    report = um.ingest_quality(kind="rule", content="x", quality=1.0, confidence=1.0)
    # All satellites disabled → nothing actually stored
    assert report["class"] == "knowledge"
    assert um.get_satellites().vector.stats()["total"] == 0


def test_unified_memory_get_stats_includes_satellites():
    um = UnifiedMemory()
    um.ingest_quality(kind="rule", content="hello", quality=0.9, confidence=0.9)
    stats = um.get_stats()
    assert "satellites" in stats
    assert stats["satellites"]["vector"]["total"] >= 1
