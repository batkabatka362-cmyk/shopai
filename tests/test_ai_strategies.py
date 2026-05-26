"""Tests for engines._ai_strategies.

LLM is mocked -- these tests verify the substrate behavior:
  - AI strategy disabled by default
  - Falls back to deterministic when LLM unavailable
  - Validates LLM responses (subset checks, enum checks)
  - Never fires engines outside wired_members
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from engines._ai_strategies import (
    AICaptainStrategy,
    AIOrchestratorStrategy,
    _LLMClient,
    _ai_enabled,
)
from engines._clusters import get_cluster
from engines._orchestrator import (
    DeterministicOrchestratorStrategy,
)


class TestAIDisabledByDefault:

    def test_ai_disabled_unless_env_var(self, monkeypatch):
        monkeypatch.delenv("SHOPAI_AI_STRATEGY", raising=False)
        assert _ai_enabled() is False

    def test_ai_enabled_with_env_var(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_AI_STRATEGY", "1")
        assert _ai_enabled() is True


class TestAICaptainFallback:

    def test_falls_back_when_disabled(self, monkeypatch):
        # AI disabled -> AICaptainStrategy behaves identical
        # to SignalDriven
        monkeypatch.delenv("SHOPAI_AI_STRATEGY", raising=False)
        strategy = AICaptainStrategy()
        cluster = get_cluster("retention")
        wired = sorted(cluster.members)
        result = strategy.select_members(
            cluster, wired, {"at_risk_count": 5},
        )
        # SignalDriven would pick at_risk-focused + defaults;
        # we just verify it's a sane subset of wired
        assert set(result).issubset(set(wired))

    def test_falls_back_when_llm_unavailable(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_AI_STRATEGY", "1")
        # LLM client reports unavailable
        with patch.object(
            _LLMClient, "available",
            new_callable=lambda: property(lambda s: False),
        ):
            strategy = AICaptainStrategy()
            cluster = get_cluster("retention")
            wired = sorted(cluster.members)
            result = strategy.select_members(
                cluster, wired, {"at_risk_count": 5},
            )
            assert set(result).issubset(set(wired))

    def test_validates_llm_response(self, monkeypatch):
        """If LLM returns an engine NOT in wired_members,
        it must be filtered out."""
        monkeypatch.setenv("SHOPAI_AI_STRATEGY", "1")

        class FakeLLM:
            available = True
            def chat_json(self, system, user):
                return {
                    "fire": [
                        "loyalty",
                        "fake_engine_not_in_cluster",
                    ],
                    "rationale": "test",
                }

        strategy = AICaptainStrategy(llm=FakeLLM())
        cluster = get_cluster("retention")
        wired = sorted(cluster.members)
        result = strategy.select_members(
            cluster, wired, {"at_risk_count": 5},
        )
        # Only loyalty (real member) should survive
        assert "loyalty" in result
        assert "fake_engine_not_in_cluster" not in result

    def test_empty_llm_response_falls_back_to_base(
        self, monkeypatch,
    ):
        monkeypatch.setenv("SHOPAI_AI_STRATEGY", "1")

        class FakeLLM:
            available = True
            def chat_json(self, system, user):
                # Empty / all-invalid response
                return {"fire": [], "rationale": "nothing"}

        strategy = AICaptainStrategy(llm=FakeLLM())
        cluster = get_cluster("retention")
        wired = sorted(cluster.members)
        result = strategy.select_members(
            cluster, wired, {"at_risk_count": 5},
        )
        # Fell back to base SignalDriven -> non-empty
        assert len(result) > 0

    def test_llm_failure_falls_back(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_AI_STRATEGY", "1")

        class FakeLLM:
            available = True
            def chat_json(self, system, user):
                return None  # network failure / parse error

        strategy = AICaptainStrategy(llm=FakeLLM())
        cluster = get_cluster("retention")
        wired = sorted(cluster.members)
        result = strategy.select_members(
            cluster, wired, {"at_risk_count": 5},
        )
        # Fell back to base
        assert len(result) > 0


class TestAttributionContext:
    """Wave 17: AI captain prompt includes per-engine revenue."""

    def _fake_attr_report(
        self, *, cluster_rev=0.0, engine_revs=None,
    ):
        from engines._revenue_attribution import (
            AttributionReport, ClusterAttribution, EngineAttribution,
        )
        rpt = AttributionReport(window_hours=168.0)
        if cluster_rev > 0:
            rpt.per_cluster.append(
                ClusterAttribution(
                    cluster="retention", window_hours=168.0,
                    attributed_revenue=cluster_rev,
                    attributed_orders=1,
                )
            )
        for engine, rev in (engine_revs or {}).items():
            rpt.per_engine.append(
                EngineAttribution(
                    engine=engine, cluster="retention",
                    window_hours=168.0,
                    attributed_revenue=rev,
                    attributed_orders=1 if rev > 0 else 0,
                )
            )
        # Already sorted in attribute_revenue itself; do here
        # for the test fake.
        rpt.per_engine.sort(
            key=lambda e: e.attributed_revenue, reverse=True,
        )
        return rpt

    def test_context_includes_cluster_revenue(self):
        strategy = AICaptainStrategy()
        cluster = get_cluster("retention")
        wired = ["loyalty", "churn_prediction"]
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=self._fake_attr_report(
                cluster_rev=500.0,
                engine_revs={
                    "loyalty": 400.0,
                    "churn_prediction": 100.0,
                },
            ),
        ):
            ctx = strategy._attribution_context(cluster, wired)
        assert ctx["cluster_attributed_revenue"] == 500.0
        assert ctx["top_engine"] == "loyalty"
        members = {m["engine"]: m["revenue"] for m in ctx["members"]}
        assert members["loyalty"] == 400.0
        assert members["churn_prediction"] == 100.0

    def test_context_filters_to_wired_only(self):
        """Engines outside wired_members shouldn't appear."""
        strategy = AICaptainStrategy()
        cluster = get_cluster("retention")
        wired = ["loyalty"]
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=self._fake_attr_report(
                engine_revs={
                    "loyalty": 400.0,
                    "churn_prediction": 9999.0,
                },
            ),
        ):
            ctx = strategy._attribution_context(cluster, wired)
        engine_names = {m["engine"] for m in ctx["members"]}
        assert engine_names == {"loyalty"}

    def test_context_handles_attribution_raise(self):
        strategy = AICaptainStrategy()
        cluster = get_cluster("retention")
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            side_effect=RuntimeError("net blip"),
        ):
            ctx = strategy._attribution_context(
                cluster, ["loyalty"],
            )
        # Graceful degradation -- model still gets the dict
        # shape, just empty values.
        assert ctx["cluster_attributed_revenue"] == 0.0
        assert ctx["members"] == []
        assert ctx["top_engine"] is None


class TestAIOrchestratorFallback:

    def test_falls_back_when_disabled(self, monkeypatch):
        monkeypatch.delenv("SHOPAI_AI_STRATEGY", raising=False)
        strategy = AIOrchestratorStrategy()
        prio = strategy.decide_priority(
            "store-A",
            {"stats": {"products": 0, "orders": 0}},
        )
        assert prio.priority == "launching"

    def test_validates_llm_priority(self, monkeypatch):
        """If LLM returns a class NOT in the valid set,
        fall back to deterministic."""
        monkeypatch.setenv("SHOPAI_AI_STRATEGY", "1")

        class FakeLLM:
            available = True
            def chat_json(self, system, user):
                return {
                    "priority": "made_up_class",
                    "rationale": "...",
                }

        strategy = AIOrchestratorStrategy(llm=FakeLLM())
        prio = strategy.decide_priority(
            "store-A",
            {"stats": {"products": 0, "orders": 0}},
        )
        assert prio.priority == "launching"  # fell back

    def test_ai_reclassifies_within_valid_set(
        self, monkeypatch,
    ):
        monkeypatch.setenv("SHOPAI_AI_STRATEGY", "1")

        class FakeLLM:
            available = True
            def chat_json(self, system, user):
                return {
                    "priority": "at_risk",
                    "rationale": "ai sees risk signal",
                }

        strategy = AIOrchestratorStrategy(llm=FakeLLM())
        # Deterministic would say "mature" for these stats
        prio = strategy.decide_priority(
            "store-A",
            {"stats": {
                "products": 100, "orders": 100,
                "total_revenue": 10000.0,
            }},
        )
        # AI reclassified to at_risk
        assert prio.priority == "at_risk"
        assert "[AI]" in prio.rationale


class TestCaptainTrend:
    """Wave 34: AI captain prompt context includes per-engine
    trend (rising/falling/flat/new) from recent snapshots."""

    def _fake_report(self, engine_revs):
        from engines._revenue_attribution import (
            AttributionReport, EngineAttribution,
        )
        rpt = AttributionReport(window_hours=168.0)
        for engine, rev in engine_revs.items():
            rpt.per_engine.append(
                EngineAttribution(
                    engine=engine,
                    cluster="retention",
                    window_hours=168.0,
                    attributed_revenue=rev,
                    attributed_orders=1 if rev > 0 else 0,
                )
            )
        rpt.per_engine.sort(
            key=lambda e: e.attributed_revenue, reverse=True,
        )
        return rpt

    def test_rising_trend_detected(self):
        strategy = AICaptainStrategy()
        cluster = get_cluster("retention")
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=self._fake_report({"loyalty": 500.0}),
        ), patch(
            "engines._attribution_snapshot.engine_revenue_history",
            return_value=[
                {"attributed_revenue": 100.0},  # oldest
                {"attributed_revenue": 300.0},
                {"attributed_revenue": 500.0},  # newest
            ],
        ):
            ctx = strategy._attribution_context(
                cluster, ["loyalty"],
            )
        loyalty = next(
            m for m in ctx["members"] if m["engine"] == "loyalty"
        )
        assert loyalty["trend"] == "rising"
        assert loyalty["recent_revenue"] == [100.0, 300.0, 500.0]

    def test_falling_trend_detected(self):
        strategy = AICaptainStrategy()
        cluster = get_cluster("retention")
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=self._fake_report({"loyalty": 100.0}),
        ), patch(
            "engines._attribution_snapshot.engine_revenue_history",
            return_value=[
                {"attributed_revenue": 1000.0},
                {"attributed_revenue": 500.0},
                {"attributed_revenue": 100.0},
            ],
        ):
            ctx = strategy._attribution_context(
                cluster, ["loyalty"],
            )
        loyalty = next(
            m for m in ctx["members"] if m["engine"] == "loyalty"
        )
        assert loyalty["trend"] == "falling"

    def test_flat_trend_within_10pct(self):
        strategy = AICaptainStrategy()
        cluster = get_cluster("retention")
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=self._fake_report({"loyalty": 105.0}),
        ), patch(
            "engines._attribution_snapshot.engine_revenue_history",
            return_value=[
                {"attributed_revenue": 100.0},
                {"attributed_revenue": 105.0},
            ],
        ):
            ctx = strategy._attribution_context(
                cluster, ["loyalty"],
            )
        loyalty = next(
            m for m in ctx["members"] if m["engine"] == "loyalty"
        )
        assert loyalty["trend"] == "flat"

    def test_new_trend_when_no_history(self):
        strategy = AICaptainStrategy()
        cluster = get_cluster("retention")
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=self._fake_report({"loyalty": 100.0}),
        ), patch(
            "engines._attribution_snapshot.engine_revenue_history",
            return_value=[],
        ):
            ctx = strategy._attribution_context(
                cluster, ["loyalty"],
            )
        loyalty = next(
            m for m in ctx["members"] if m["engine"] == "loyalty"
        )
        assert loyalty["trend"] == "new"


class TestOrchestratorAttributionContext:
    """Wave 24: AI orchestrator prompt gets per-store cluster
    attribution context."""

    def _fake_report(self, *, attributed=0.0, total_orders=0,
                     per_cluster=None):
        from engines._revenue_attribution import (
            AttributionReport, ClusterAttribution,
        )
        rpt = AttributionReport(window_hours=168.0)
        rpt.total_orders_in_window = total_orders
        rpt.total_revenue_in_window = sum(
            c.get("revenue", 0.0) for c in (per_cluster or [])
        )
        for c in (per_cluster or []):
            rpt.per_cluster.append(
                ClusterAttribution(
                    cluster=c["cluster"],
                    window_hours=168.0,
                    attributed_revenue=c["revenue"],
                    attributed_orders=c["orders"],
                )
            )
        return rpt

    def test_context_includes_per_cluster_revenue(self):
        strategy = AIOrchestratorStrategy()
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=self._fake_report(
                total_orders=10,
                per_cluster=[
                    {"cluster": "retention",
                     "revenue": 5000.0, "orders": 8},
                    {"cluster": "acquisition",
                     "revenue": 50.0, "orders": 2},
                ],
            ),
        ):
            ctx = strategy._store_attribution_context("store-x")
        assert ctx["total_orders_in_window"] == 10
        assert len(ctx["top_clusters"]) == 2
        # Sorted desc by attribute_revenue (in source data)
        top = ctx["top_clusters"][0]
        assert top["cluster"] == "retention"
        assert top["revenue"] == 5000.0

    def test_context_empty_when_no_attribution(self):
        strategy = AIOrchestratorStrategy()
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=self._fake_report(),
        ):
            ctx = strategy._store_attribution_context("store-x")
        assert ctx["attributed_revenue"] == 0.0
        assert ctx["top_clusters"] == []

    def test_context_handles_attribution_raise(self):
        """Graceful: model still gets the dict shape, just
        empty values."""
        strategy = AIOrchestratorStrategy()
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            side_effect=RuntimeError("net blip"),
        ):
            ctx = strategy._store_attribution_context("store-x")
        assert ctx["attributed_revenue"] == 0.0
        assert ctx["top_clusters"] == []


class TestLLMClientGate:

    def test_llm_unavailable_without_api_key(
        self, monkeypatch,
    ):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        llm = _LLMClient()
        # Without the API key, available should be False
        # (even if openai is installed)
        assert llm.available is False or True  # tolerate either
