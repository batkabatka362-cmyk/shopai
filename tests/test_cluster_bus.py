"""Tests for engines._cluster_bus."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from engines._cluster_bus import (
    ClusterEvent,
    emit_event,
    subscribe_events,
    cross_cluster_signals,
    clear_bus,
)


@pytest.fixture
def isolated_bus(monkeypatch, tmp_path):
    """Each test gets a fresh bus in a temp directory."""
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    yield tmp_path


class TestEmitAndSubscribe:

    def test_emit_then_subscribe(self, isolated_bus):
        emit_event(
            "meta_ads", "high_roas_product",
            payload={"product_id": "X", "roas": 5.0},
        )
        events = subscribe_events()
        assert len(events) == 1
        assert events[0].topic == "high_roas_product"
        assert events[0].emitter_cluster == "meta_ads"
        assert events[0].payload["roas"] == 5.0

    def test_filter_by_topic(self, isolated_bus):
        emit_event("meta_ads", "high_roas_product")
        emit_event("retention", "churn_risk_detected")
        roas = subscribe_events(topic="high_roas_product")
        assert len(roas) == 1
        assert roas[0].topic == "high_roas_product"

    def test_filter_by_emitter(self, isolated_bus):
        emit_event("meta_ads", "high_roas_product")
        emit_event("shopify", "high_roas_product")
        meta = subscribe_events(emitter_cluster="meta_ads")
        assert len(meta) == 1
        assert meta[0].emitter_cluster == "meta_ads"

    def test_filter_by_store(self, isolated_bus):
        emit_event(
            "meta_ads", "high_roas_product", store_id="A",
        )
        emit_event(
            "meta_ads", "high_roas_product", store_id="B",
        )
        a_events = subscribe_events(store_id="A")
        assert len(a_events) == 1
        assert a_events[0].store_id == "A"


class TestCrossClusterSignals:

    def test_topic_to_signal_mapping(self, isolated_bus):
        emit_event("meta_ads", "high_roas_product")
        emit_event("meta_ads", "high_roas_product")
        emit_event("retention", "churn_risk_detected")

        signals = cross_cluster_signals()
        # 2 high_roas events -> merchandising.high_roas_product_count = 2
        assert signals["merchandising"][
            "high_roas_product_count"
        ] == 2
        # 1 churn_risk -> retention.at_risk_count = 1
        assert signals["retention"]["at_risk_count"] == 1

    def test_unknown_topic_ignored(self, isolated_bus):
        emit_event("custom", "some_random_topic")
        signals = cross_cluster_signals()
        # No mapping -> nothing added
        assert signals == {}

    def test_per_store_signals(self, isolated_bus):
        emit_event(
            "meta_ads", "high_roas_product", store_id="A",
        )
        emit_event(
            "meta_ads", "high_roas_product", store_id="B",
        )
        a_signals = cross_cluster_signals(store_id="A")
        assert a_signals["merchandising"][
            "high_roas_product_count"
        ] == 1


class TestPersistence:

    def test_clear_bus(self, isolated_bus):
        emit_event("meta_ads", "test")
        assert len(subscribe_events()) == 1
        clear_bus()
        assert subscribe_events() == []

    def test_events_persist_across_calls(self, isolated_bus):
        emit_event("meta_ads", "test1")
        emit_event("retention", "test2")
        # Re-subscribe pulls fresh from disk
        events = subscribe_events()
        assert len(events) == 2
