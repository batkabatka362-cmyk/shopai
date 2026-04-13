"""Integration tests for UnifiedMemory → SatelliteRouter auto-routing
(Wave 3 #3).

The Wave 2 #4 commit added a SatelliteRouter on the UnifiedMemory
instance but none of the legacy write paths (``ingest``,
``record_decision``, ``record_mistake``, ``record_failure``) fed
it. Wave 3 #3 plumbs all four through a single
``_auto_route_to_satellites`` helper so a caller using the existing
API automatically populates the vector / graph / signal layers in
addition to whatever legacy backends the unified memory has.

These tests exercise the integration by swapping in a neutered
router (so we don't touch real backends at all) and asserting that
each legacy entry point produced the expected satellite dispatch.
"""
from __future__ import annotations

from typing import Any

import pytest

from core.memory.quality_engine import MemoryClass, MemoryRecord
from core.memory.satellite_layers import SatelliteRouter
from core.memory.unified_memory import UnifiedMemory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _RecordingRouter(SatelliteRouter):
    """SatelliteRouter that captures every route_record call."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, Any]] = []

    def route_record(
        self,
        record: MemoryRecord,
        *,
        record_id: str | None = None,
        memory_class: MemoryClass | None = None,
        content: Any = None,
        entities: list[str] | None = None,
        signal_name: str | None = None,
        signal_value: float | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "kind": record.kind,
                "record": record,
                "class": memory_class,
                "content": content,
                "entities": entities,
                "signal": (signal_name, signal_value),
            },
        )
        return super().route_record(
            record,
            record_id=record_id,
            memory_class=memory_class,
            content=content,
            entities=entities,
            signal_name=signal_name,
            signal_value=signal_value,
        )


def _memory() -> tuple[UnifiedMemory, _RecordingRouter]:
    mem = UnifiedMemory()
    router = _RecordingRouter()
    mem.set_satellites(router)
    return mem, router


# ---------------------------------------------------------------------------
# ingest()
# ---------------------------------------------------------------------------


def test_ingest_auto_routes_to_satellites():
    mem, router = _memory()
    mem.ingest(
        "product_update",
        {"sku": "HAT-001", "price": 29.99},
        source="shopify_webhook",
        store_id="store_42",
    )
    assert len(router.calls) == 1
    call = router.calls[0]
    assert call["kind"] == "product_update"
    # source + store_id merged into payload, not lost
    payload = call["record"].payload
    assert payload["sku"] == "HAT-001"
    assert payload["source"] == "shopify_webhook"
    assert payload["store_id"] == "store_42"
    assert isinstance(call["class"], MemoryClass)


def test_ingest_non_dict_data_wrapped_in_value_dict():
    mem, router = _memory()
    mem.ingest("metric", 42)
    call = router.calls[0]
    assert call["record"].payload == {"value": 42}


def test_ingest_does_not_add_empty_source_to_payload():
    mem, router = _memory()
    mem.ingest("event", {"type": "login"})
    payload = router.calls[0]["record"].payload
    assert "source" not in payload
    assert "store_id" not in payload


# ---------------------------------------------------------------------------
# record_decision()
# ---------------------------------------------------------------------------


def test_record_decision_auto_routes_with_score_quality():
    mem, router = _memory()
    mem.record_decision(
        category="pricing",
        input_data={"product_id": "p1"},
        action="raise 10%",
        result={"revenue_delta": 150},
        score=4.5,
        tags=["pricing", "win"],
        store_id="store_1",
    )
    assert len(router.calls) == 1
    rec = router.calls[0]["record"]
    assert rec.kind == "decision"
    assert rec.quality == pytest.approx(0.9)  # 4.5 / 5
    assert rec.confidence == pytest.approx(0.9)
    assert rec.success_rate == 1.0  # score >= 3.0
    assert set(rec.tags) == {"pricing", "win"}
    # Full decision body captured for vector indexing
    assert rec.payload["action"] == "raise 10%"
    assert rec.payload["category"] == "pricing"


def test_record_decision_low_score_marks_failure():
    mem, router = _memory()
    mem.record_decision(
        category="inventory",
        input_data={},
        action="reorder",
        result={"error": "stockout"},
        score=1.0,
    )
    rec = router.calls[0]["record"]
    assert rec.success_rate == 0.0
    assert rec.quality == pytest.approx(0.2)


def test_record_decision_clamps_out_of_range_scores():
    mem, router = _memory()
    mem.record_decision(
        "x", {}, "a", {}, score=10.0,
    )
    assert router.calls[0]["record"].quality == 1.0
    mem.record_decision(
        "x", {}, "a", {}, score=-3.0,
    )
    assert router.calls[1]["record"].quality == 0.0


# ---------------------------------------------------------------------------
# record_mistake()
# ---------------------------------------------------------------------------


def test_record_mistake_auto_routes_as_error_class():
    mem, router = _memory()
    mem.record_mistake(
        "pricing_undershoot",
        "dropped price below margin",
        cause="bad comp data",
        prevention="add margin floor check",
        store_id="s1",
    )
    assert len(router.calls) == 1
    call = router.calls[0]
    assert call["kind"] == "mistake:pricing_undershoot"
    assert call["class"] == MemoryClass.ERROR
    rec = call["record"]
    assert rec.payload["description"] == "dropped price below margin"
    assert rec.payload["cause"] == "bad comp data"
    assert rec.payload["store_id"] == "s1"


# ---------------------------------------------------------------------------
# record_failure()
# ---------------------------------------------------------------------------


def test_record_failure_auto_routes_as_error_class():
    mem, router = _memory()
    mem.record_failure(
        "checkout",
        {"message": "gateway timeout", "code": 504},
        root_cause="upstream rate limit",
        severity="high",
    )
    assert len(router.calls) == 1
    call = router.calls[0]
    assert call["kind"] == "failure:checkout"
    # high severity → ERROR class
    assert call["class"] == MemoryClass.ERROR


def test_record_failure_always_auto_routes_even_when_legacy_backend_returns():
    mem, router = _memory()
    # memory_intel may or may not be loaded depending on test
    # environment. Either way auto-routing must fire exactly once.
    mem.record_failure("x", {}, "r", "low")
    assert len(router.calls) == 1
    assert router.calls[0]["kind"] == "failure:x"


# ---------------------------------------------------------------------------
# Satellite auto-route failures are absorbed
# ---------------------------------------------------------------------------


class _BoomRouter(SatelliteRouter):
    def route_record(self, *args, **kwargs):  # type: ignore[override]
        raise RuntimeError("satellites down")


def test_satellite_failure_does_not_break_legacy_writes():
    mem = UnifiedMemory()
    mem.set_satellites(_BoomRouter())
    # None of these should raise, even though the router blows up.
    mem.ingest("x", {"a": 1})
    mem.record_decision("c", {}, "a", {}, 3.0)
    mem.record_mistake("m", "desc")
    # Return value from record_failure depends on whether
    # memory_intel is loaded; we only care that it doesn't raise.
    _ = mem.record_failure("c", {})


# ---------------------------------------------------------------------------
# Satellite stats reflect auto-routed records
# ---------------------------------------------------------------------------


def test_auto_routing_lands_decision_records_in_vector_layer():
    mem = UnifiedMemory()
    # Fresh real router (not recording stub) so we can check
    # satellite stats end-to-end
    for i in range(3):
        mem.record_decision(
            "pricing", {"i": i}, f"action-{i}", {"ok": True}, score=4.0,
        )
    stats = mem.get_satellites().stats()
    # Decisions with score=4.0 classify as KNOWLEDGE → vector layer
    assert stats["vector"]["total"] >= 3


def test_auto_routing_lands_errors_in_vector_layer():
    mem = UnifiedMemory()
    for i in range(5):
        mem.record_failure(
            "checkout", {"message": f"timeout {i}"}, severity="high",
        )
    stats = mem.get_satellites().stats()
    assert stats["vector"]["total"] >= 5
