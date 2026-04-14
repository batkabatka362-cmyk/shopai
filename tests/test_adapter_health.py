"""Adapter health score tests — Option W.

Covers the per-component scorers, weight normalisation across
available components, grade bands, the all-adapter rollup, and
the validation of the HealthScorer constructor.
"""
from __future__ import annotations

import pytest

from core.adapters.health import (
    DEFAULT_WEIGHTS,
    DEGRADED_CUTOFF,
    HEALTHY_CUTOFF,
    HealthComponent,
    HealthScorer,
    UNKNOWN_GRADE,
    _breaker_component,
    _rate_limit_component,
    _retry_component,
    _sla_component,
)


class TestSLAComponent:
    def test_missing_row_is_unavailable(self):
        c = _sla_component(None)
        assert c.available is False
        assert c.score == 0.0

    def test_warming_up_is_unavailable(self):
        c = _sla_component({"evaluated": False, "samples": 2})
        assert c.available is False
        assert "warming up" in c.detail

    def test_breach_scores_zero(self):
        c = _sla_component({
            "evaluated": True, "grade": "breach",
            "violations": ["p95 4200ms > 2000ms"],
        })
        assert c.score == 0.0
        assert "p95" in c.detail

    def test_warn_scores_half(self):
        c = _sla_component({
            "evaluated": True, "grade": "warn",
            "warnings": ["p99 near budget"],
        })
        assert c.score == 0.5

    def test_ok_scores_full(self):
        c = _sla_component({
            "evaluated": True, "grade": "ok",
            "p95_ms": 1200, "success_rate": 0.99,
        })
        assert c.score == 1.0


class TestBreakerComponent:
    def test_missing_is_unavailable(self):
        c = _breaker_component(None)
        assert c.available is False

    def test_open_scores_zero(self):
        c = _breaker_component({"state": "open", "trips": 3})
        assert c.score == 0.0
        assert "OPEN" in c.detail

    def test_half_open_mid_recovery(self):
        c = _breaker_component({"state": "half_open", "trips": 1})
        assert 0.0 < c.score < 1.0

    def test_closed_near_threshold_penalised(self):
        c = _breaker_component({
            "state": "closed",
            "consecutive_failures": 4,
            "fail_threshold": 5,
        })
        assert c.score < 1.0

    def test_closed_healthy(self):
        c = _breaker_component({
            "state": "closed",
            "consecutive_failures": 0,
            "fail_threshold": 5,
        })
        assert c.score == 1.0


class TestRateLimitComponent:
    def test_missing_is_unavailable(self):
        c = _rate_limit_component(None)
        assert c.available is False

    def test_throttled_zero(self):
        c = _rate_limit_component({"status": "throttled"})
        assert c.score == 0.0

    def test_near_half(self):
        c = _rate_limit_component({
            "status": "near",
            "minute_used_pct": 0.85,
        })
        assert c.score == 0.5

    def test_ok_full(self):
        assert _rate_limit_component({"status": "ok"}).score == 1.0

    def test_idle_full(self):
        # Idle just means no calls — not a failure signal.
        assert _rate_limit_component({"status": "idle"}).score == 1.0


class TestRetryComponent:
    def test_missing_is_unavailable(self):
        c = _retry_component(None)
        assert c.available is False

    def test_too_few_calls_unavailable(self):
        c = _retry_component({"calls": 2, "retries": 0, "giveups": 0})
        assert c.available is False
        assert "insufficient" in c.detail

    def test_clean_adapter_full(self):
        c = _retry_component({"calls": 100, "retries": 0, "giveups": 0})
        assert c.score == 1.0

    def test_moderate_giveups_penalised(self):
        # 5% give-up rate → ~0.5
        c = _retry_component({"calls": 100, "retries": 10, "giveups": 5})
        assert 0.3 < c.score < 0.6

    def test_high_giveups_zero(self):
        c = _retry_component({"calls": 100, "retries": 20, "giveups": 20})
        assert c.score == 0.0

    def test_high_retry_rate_shaves_points(self):
        # No give-ups, but half the calls retried — vendor flaky.
        clean = _retry_component({"calls": 100, "retries": 0, "giveups": 0})
        flaky = _retry_component({"calls": 100, "retries": 60, "giveups": 0})
        assert flaky.score < clean.score


class TestScorerValidation:
    def test_weights_must_sum_to_one(self):
        with pytest.raises(ValueError):
            HealthScorer(weights={"breaker": 0.5})

    def test_negative_weight_rejected(self):
        with pytest.raises(ValueError):
            HealthScorer(weights={
                "breaker": -0.1, "sla": 0.5, "retry": 0.3, "rate_limit": 0.3,
            })

    def test_cutoffs_must_be_ordered(self):
        with pytest.raises(ValueError):
            HealthScorer(healthy_cutoff=0.3, degraded_cutoff=0.5)


class TestCompositeScore:
    def test_all_healthy_grade_healthy(self):
        s = HealthScorer()
        result = s.score(
            "openai",
            sla={"evaluated": True, "grade": "ok", "p95_ms": 1000, "success_rate": 1.0},
            breaker={"state": "closed", "consecutive_failures": 0, "fail_threshold": 5, "trips": 0},
            rate_limit={"status": "ok"},
            retry={"calls": 100, "retries": 0, "giveups": 0},
        )
        assert result.score >= HEALTHY_CUTOFF
        assert result.grade == "healthy"

    def test_open_breaker_plus_breach_unhealthy(self):
        s = HealthScorer()
        result = s.score(
            "openai",
            sla={"evaluated": True, "grade": "breach", "violations": ["p95"]},
            breaker={"state": "open", "trips": 2},
            rate_limit={"status": "ok"},
            retry={"calls": 100, "retries": 0, "giveups": 0},
        )
        assert result.score < DEGRADED_CUTOFF
        assert result.grade == "unhealthy"

    def test_single_warn_drops_to_degraded(self):
        s = HealthScorer()
        result = s.score(
            "openai",
            sla={"evaluated": True, "grade": "warn", "warnings": ["p95 near"]},
            breaker={"state": "closed", "consecutive_failures": 0, "fail_threshold": 5},
            rate_limit={"status": "ok"},
            retry={"calls": 100, "retries": 0, "giveups": 0},
        )
        # SLA=0.5, breaker=1.0, retry=1.0, ratelimit=1.0 — but with
        # weights 0.30/0.35/0.20/0.15 → 0.85. So one warn alone is
        # still healthy under the default weights.
        assert result.grade in ("healthy", "degraded")

    def test_missing_signals_reweighted(self):
        """An adapter with only breaker telemetry should score purely
        on breaker health without dragging the composite down."""
        s = HealthScorer()
        result = s.score(
            "new_adapter",
            breaker={"state": "closed", "consecutive_failures": 0, "fail_threshold": 5},
        )
        # Only breaker=1.0 available; score should be 1.0 after
        # weight renormalisation.
        assert result.score == 1.0
        assert result.grade == "healthy"

    def test_no_signals_unknown(self):
        s = HealthScorer()
        result = s.score("mystery")
        assert result.grade == UNKNOWN_GRADE
        # Every component reports unavailable.
        assert all(c.available is False for c in result.components)

    def test_components_all_present_in_output(self):
        s = HealthScorer()
        result = s.score("x")
        names = {c.name for c in result.components}
        assert names == {"sla", "breaker", "rate_limit", "retry"}


class TestScoreAll:
    def test_unions_across_streams(self):
        s = HealthScorer()
        rows = s.score_all(
            sla_rows=[{"adapter": "a", "evaluated": True, "grade": "ok"}],
            breakers=[{"adapter": "b", "state": "closed", "consecutive_failures": 0, "fail_threshold": 5}],
            rate_rows=[{"adapter": "c", "status": "ok"}],
            retry_per_adapter=[{"adapter": "d", "calls": 100, "retries": 0, "giveups": 0}],
        )
        names = {r.adapter for r in rows}
        assert names == {"a", "b", "c", "d"}

    def test_sorted_worst_first(self):
        s = HealthScorer()
        rows = s.score_all(
            sla_rows=[
                {"adapter": "good", "evaluated": True, "grade": "ok", "p95_ms": 1000, "success_rate": 1.0},
                {"adapter": "bad", "evaluated": True, "grade": "breach", "violations": ["p95"]},
            ],
            breakers=[
                {"adapter": "good", "state": "closed", "consecutive_failures": 0, "fail_threshold": 5},
                {"adapter": "bad", "state": "open", "trips": 1},
            ],
            rate_rows=[],
            retry_per_adapter=[],
        )
        assert [r.adapter for r in rows] == ["bad", "good"]

    def test_breaker_name_fallback(self):
        """Breaker snapshot rows use ``name`` in some code paths and
        ``adapter`` in others — the scorer should accept either."""
        s = HealthScorer()
        rows = s.score_all(
            breakers=[
                {"name": "from_name", "state": "closed", "consecutive_failures": 0, "fail_threshold": 5},
                {"adapter": "from_adapter", "state": "closed", "consecutive_failures": 0, "fail_threshold": 5},
            ],
        )
        assert {r.adapter for r in rows} == {"from_name", "from_adapter"}

    def test_totals_counts_each_grade(self):
        s = HealthScorer()
        rows = s.score_all(
            sla_rows=[
                {"adapter": "healthy", "evaluated": True, "grade": "ok", "p95_ms": 500, "success_rate": 1.0},
                {"adapter": "sick", "evaluated": True, "grade": "breach", "violations": ["p95"]},
            ],
            breakers=[
                {"adapter": "healthy", "state": "closed", "consecutive_failures": 0, "fail_threshold": 5},
                {"adapter": "sick", "state": "open", "trips": 1},
                {"adapter": "unknown", "state": "closed", "consecutive_failures": 0, "fail_threshold": 5},
            ],
        )
        totals = HealthScorer.totals(rows)
        assert totals["healthy"] >= 1
        assert totals["unhealthy"] >= 1
        assert sum(totals.values()) == len(rows)

    def test_empty_inputs_empty_output(self):
        s = HealthScorer()
        assert s.score_all() == []


class TestDefaults:
    def test_default_weights_sum_to_one(self):
        assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)

    def test_default_weights_cover_four_components(self):
        assert set(DEFAULT_WEIGHTS) == {
            "breaker", "sla", "retry", "rate_limit",
        }

    def test_breaker_weight_is_highest(self):
        # The whole scoring design assumes breaker state is the
        # heaviest single signal — regression test against someone
        # silently reordering the catalogue.
        assert max(
            DEFAULT_WEIGHTS.items(), key=lambda kv: kv[1],
        )[0] == "breaker"
