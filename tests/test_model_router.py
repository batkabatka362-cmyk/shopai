"""Tests for the cost-aware model router
(``core.model_router``).

AGI roadmap Phase 2 layer 3. Verifies:

  - Token estimation
  - Complexity classification (keyword, length, structure)
  - Routing policy (local vs cloud) with hint overrides
  - Budget tracking + cap-based downgrade
  - Usage recording
"""
from __future__ import annotations

from core.model_router import (
    ModelHint,
    ModelRouter,
    ModelTier,
)
from core.model_router.router import (
    _combine_complexity,
    _complexity_components,
    _estimate_tokens,
)


# ─── Pure helpers ────────────────────────────────────────────


class TestTokenEstimate:

    def test_short_prompt(self):
        assert _estimate_tokens("hello world") in range(2, 4)

    def test_long_prompt(self):
        words = " ".join(["word"] * 500)
        # 500 words * 1.4 = 700 tokens
        assert _estimate_tokens(words) == 700

    def test_empty(self):
        assert _estimate_tokens("") == 0

    def test_non_string_returns_zero(self):
        assert _estimate_tokens(None) == 0  # type: ignore[arg-type]


class TestComplexityComponents:

    def test_keyword_hit_increments(self):
        comp = _complexity_components(
            "Please explain the trade-off and analyze it."
        )
        # 3 strategy keywords: explain, trade-off, analyze
        assert comp["keyword_hits"] >= 3

    def test_no_keywords(self):
        comp = _complexity_components("fetch the latest order")
        assert comp["keyword_hits"] == 0

    def test_structured_ratio(self):
        # JSON-style payload heavy in structure chars
        comp = _complexity_components('{"a": 1, "b": [2, 3]}')
        assert comp["structured_ratio"] > 0.2


class TestCombineComplexity:

    def test_zero_for_short_plain(self):
        comp = _complexity_components("ok")
        score = _combine_complexity(comp)
        assert score == 0.0

    def test_high_for_keyword_heavy(self):
        comp = _complexity_components(
            "Analyze, explain, evaluate, and synthesize this."
        )
        score = _combine_complexity(comp)
        # 4 keyword hits -> 1.0 keyword score
        assert score >= 0.9

    def test_long_prose_boosts(self):
        prompt = " ".join(["word"] * 850)  # > 800 words
        comp = _complexity_components(prompt)
        score = _combine_complexity(comp)
        assert score >= 0.4


# ─── Routing policy ──────────────────────────────────────────


class TestRoutingPolicy:

    def test_short_simple_prompt_local(self, tmp_path):
        router = ModelRouter(db_path=tmp_path / "mr.db")
        d = router.classify("fetch product 42")
        assert d.tier == ModelTier.LOCAL
        assert d.downgraded is False

    def test_long_prompt_routes_cloud(self, tmp_path):
        router = ModelRouter(
            db_path=tmp_path / "mr.db",
            local_max_tokens=100,
        )
        long_prompt = " ".join(["word"] * 200)  # ~280 tokens > 100
        d = router.classify(long_prompt)
        assert d.tier == ModelTier.CLOUD
        assert "long prompt" in d.reason

    def test_strategy_keywords_route_cloud(self, tmp_path):
        router = ModelRouter(db_path=tmp_path / "mr.db")
        prompt = (
            "Explain the trade-off between two strategies and "
            "analyze how each would affect quarterly revenue."
        )
        d = router.classify(prompt)
        assert d.tier == ModelTier.CLOUD
        assert "strategy" in d.reason or "reasoning" in d.reason

    def test_hint_local_only_overrides_long_prompt(self, tmp_path):
        router = ModelRouter(
            db_path=tmp_path / "mr.db",
            local_max_tokens=10,
        )
        long_prompt = " ".join(["word"] * 200)
        d = router.classify(long_prompt, hint=ModelHint.LOCAL_ONLY)
        assert d.tier == ModelTier.LOCAL
        assert "LOCAL_ONLY" in d.reason

    def test_hint_cloud_required_overrides_simple(self, tmp_path):
        router = ModelRouter(db_path=tmp_path / "mr.db")
        d = router.classify(
            "x", hint=ModelHint.CLOUD_REQUIRED,
        )
        assert d.tier == ModelTier.CLOUD
        assert "CLOUD_REQUIRED" in d.reason


# ─── Budget cap + downgrade ──────────────────────────────────


class TestBudgetCap:

    def test_cloud_call_increments_usage(self, tmp_path):
        router = ModelRouter(
            db_path=tmp_path / "mr.db",
            cloud_tokens_per_24h=10_000,
        )
        # Explicit CLOUD_REQUIRED to make this test about budget
        # accounting, not classification.
        d = router.classify(
            "hello", hint=ModelHint.CLOUD_REQUIRED,
        )
        router.record_usage(d, actual_tokens=200)
        report = router.budget_report()
        cloud = report["by_tier"]["cloud"]
        assert cloud["calls"] == 1
        assert cloud["actual_tokens"] == 200

    def test_cap_exhaustion_downgrades_cloud_to_local(self, tmp_path):
        router = ModelRouter(
            db_path=tmp_path / "mr.db",
            cloud_tokens_per_24h=500,
        )
        # First call eats the entire budget
        prompt = "analyze and explain"
        first = router.classify(prompt)
        assert first.tier == ModelTier.CLOUD
        router.record_usage(first, actual_tokens=600)

        # Next call should downgrade
        second = router.classify(prompt)
        assert second.tier == ModelTier.LOCAL
        assert second.downgraded is True
        assert "exhausted" in second.reason.lower()

    def test_cap_downgrade_under_hint_cloud_required(self, tmp_path):
        """Even ``hint=CLOUD_REQUIRED`` respects the cap (caller
        can still override by ignoring the decision)."""
        router = ModelRouter(
            db_path=tmp_path / "mr.db",
            cloud_tokens_per_24h=100,
        )
        # Eat the budget
        d1 = router.classify("hello", hint=ModelHint.CLOUD_REQUIRED)
        router.record_usage(d1, actual_tokens=200)
        # Next CLOUD_REQUIRED should downgrade
        d2 = router.classify(
            "hello", hint=ModelHint.CLOUD_REQUIRED,
        )
        assert d2.tier == ModelTier.LOCAL
        assert d2.downgraded is True

    def test_budget_report_remaining_pct(self, tmp_path):
        router = ModelRouter(
            db_path=tmp_path / "mr.db",
            cloud_tokens_per_24h=1_000,
        )
        d = router.classify(
            "analyze this", hint=ModelHint.CLOUD_REQUIRED,
        )
        router.record_usage(d, actual_tokens=300)
        report = router.budget_report()
        # 300/1000 = 30% used -> 70% remaining
        assert 0.65 < report["cloud_remaining_estimate_pct"] < 0.75


# ─── Decision shape ──────────────────────────────────────────


class TestDecisionShape:

    def test_to_dict_round_trip(self, tmp_path):
        router = ModelRouter(db_path=tmp_path / "mr.db")
        d = router.classify("hi", hint=ModelHint.LOCAL_ONLY)
        out = d.to_dict()
        assert out["tier"] == "local"
        assert "reason" in out
        assert "estimated_tokens" in out
        assert "complexity_score" in out
        assert "downgraded" in out
        assert "components" in out

    def test_components_carry_per_factor_signals(self, tmp_path):
        router = ModelRouter(db_path=tmp_path / "mr.db")
        d = router.classify("explain and analyze")
        comps = d.components
        assert "keyword_hits" in comps
        assert "word_count" in comps
        assert comps["keyword_hits"] >= 2


# ─── Usage recording resilience ──────────────────────────────


class TestUsageRecording:

    def test_record_usage_doesnt_throw_on_bad_input(self, tmp_path):
        router = ModelRouter(db_path=tmp_path / "mr.db")
        d = router.classify("hi", hint=ModelHint.LOCAL_ONLY)
        # No actual_tokens / latency_ms supplied -- should still
        # store without raising
        router.record_usage(d)
        report = router.budget_report()
        assert report["by_tier"]["local"]["calls"] == 1

    def test_empty_budget_report_has_zeros(self, tmp_path):
        router = ModelRouter(db_path=tmp_path / "mr.db")
        report = router.budget_report()
        assert report["by_tier"]["local"]["calls"] == 0
        assert report["by_tier"]["cloud"]["calls"] == 0
        assert report["cloud_remaining_estimate_pct"] == 1.0
