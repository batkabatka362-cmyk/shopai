"""Health-aware candidate ordering — Option X.

Verifies that the SmartRouter's ``_candidates`` method uses an
injected ``HealthScorer`` to reorder otherwise-equivalent adapters
so that healthier ones come first, without disturbing any of the
existing hard gates (breaker, budget, rate-limit) or the priority-
based base scoring.
"""
from __future__ import annotations

import pytest

from core.adapters.base import (
    AdapterCategory,
    AdapterResult,
    BaseAdapter,
    Capability,
)
from core.adapters.health import HealthScorer
from core.adapters.idempotency import IdempotencyCache
from core.adapters.rate_limit import RateLimiter
from core.adapters.registry import AdapterRegistry
from core.adapters.retry import RetryTelemetry
from core.adapters.router import RouteContext, SmartRouter


class _StubAdapter(BaseAdapter):
    def __init__(
        self,
        *,
        name: str = "stub",
        priority: int = 50,
        capabilities=None,
        cost_per_call: float = 0.0,
    ):
        self.name = name
        self.capabilities = capabilities or {Capability.CHAT_COMPLETE}
        self.category = AdapterCategory.LLM
        self.priority = priority
        self.cost_per_call = cost_per_call
        super().__init__()

    def is_configured(self) -> bool:
        return True

    def _execute(self, capability, params):  # pragma: no cover
        return AdapterResult.success(
            adapter=self.name, capability=capability.value, data={},
        )


def _router_with(adapters, *, health_scorer=None, health_bonus_range=30.0):
    """Build a router with a fresh registry + isolated collaborators."""
    reg = AdapterRegistry()
    for a in adapters:
        reg.register(a)
    return SmartRouter(
        registry=reg,
        rate_limiter=RateLimiter(policies={}),
        idempotency_cache=IdempotencyCache(policies={}),
        retry_telemetry=RetryTelemetry(),
        health_scorer=health_scorer,
        health_bonus_range=health_bonus_range,
    )


class TestHealthAwareOrdering:
    def test_no_scorer_preserves_priority_order(self):
        """Without a scorer, ordering is purely priority-based."""
        a = _StubAdapter(name="alpha", priority=70, capabilities={Capability.CHAT_COMPLETE})
        b = _StubAdapter(name="beta", priority=50, capabilities={Capability.CHAT_COMPLETE})
        r = _router_with([a, b])
        cands = r._candidates(Capability.CHAT_COMPLETE, RouteContext())
        assert [c.name for c in cands] == ["alpha", "beta"]

    def test_scorer_tiebreaks_same_priority(self):
        """Two equal-priority adapters: the healthy one wins.

        We force one adapter's breaker open and leave the other's
        closed so the scorer has real signal to work with.
        """
        a = _StubAdapter(name="alpha", priority=50, capabilities={Capability.CHAT_COMPLETE})
        b = _StubAdapter(name="beta",  priority=50, capabilities={Capability.CHAT_COMPLETE})
        r = _router_with([a, b], health_scorer=HealthScorer())
        # Force alpha's breaker open — unhealthy; leave beta untouched.
        br = r._breaker_for("alpha")
        br._state = "open"
        br._opened_at = 1e18  # far-future so it never half-opens
        # beta has no breaker registered at all → scorer returns None
        # for beta, neutral. alpha has an open breaker → low score.
        cands = r._candidates(Capability.CHAT_COMPLETE, RouteContext())
        assert [c.name for c in cands] == ["beta", "alpha"]

    def test_scorer_cannot_flip_large_priority_gap(self):
        """Health bonus is bounded by ``health_bonus_range`` — a 50-
        point priority gap beats any health tiebreaker."""
        good = _StubAdapter(name="good", priority=30, capabilities={Capability.CHAT_COMPLETE})
        great = _StubAdapter(name="great", priority=90, capabilities={Capability.CHAT_COMPLETE})
        r = _router_with(
            [good, great],
            health_scorer=HealthScorer(),
            health_bonus_range=30.0,
        )
        # Make the higher-priority adapter unhealthy.
        br = r._breaker_for("great")
        br._state = "open"
        br._opened_at = 1e18
        cands = r._candidates(Capability.CHAT_COMPLETE, RouteContext())
        # Priority 90 with -15 health penalty = 75 > priority 30 + 0
        # health bonus = 30 (since "good" has no breaker, score is
        # ``None``, no bonus applied).
        assert cands[0].name == "great"

    def test_scorer_can_flip_small_priority_gap(self):
        """A small priority gap combined with a health penalty is
        enough to flip the order — which is the whole point of
        Option X."""
        slightly_better = _StubAdapter(name="a", priority=55, capabilities={Capability.CHAT_COMPLETE})
        slightly_worse = _StubAdapter(name="b", priority=50, capabilities={Capability.CHAT_COMPLETE})
        r = _router_with(
            [slightly_better, slightly_worse],
            health_scorer=HealthScorer(),
            health_bonus_range=30.0,
        )
        # Force the higher-priority adapter into an open breaker.
        br_a = r._breaker_for("a")
        br_a._state = "open"
        br_a._opened_at = 1e18
        # Give "b" a clean breaker (closed).
        r._breaker_for("b")
        cands = r._candidates(Capability.CHAT_COMPLETE, RouteContext())
        assert cands[0].name == "b"

    def test_brand_new_adapter_scores_neutral(self):
        """An adapter with no breaker/rate/retry/metrics history gets
        ``None`` from the scorer and neither gains nor loses health
        points, so ordering stays priority-based."""
        a = _StubAdapter(name="x", priority=60, capabilities={Capability.CHAT_COMPLETE})
        b = _StubAdapter(name="y", priority=55, capabilities={Capability.CHAT_COMPLETE})
        r = _router_with([a, b], health_scorer=HealthScorer())
        cands = r._candidates(Capability.CHAT_COMPLETE, RouteContext())
        assert [c.name for c in cands] == ["x", "y"]

    def test_health_bonus_range_zero_disables_effect(self):
        """``health_bonus_range=0`` pins the health bonus to 0 even
        when a scorer is attached — a useful pre-flight flag."""
        a = _StubAdapter(name="alpha", priority=50, capabilities={Capability.CHAT_COMPLETE})
        b = _StubAdapter(name="beta",  priority=50, capabilities={Capability.CHAT_COMPLETE})
        r = _router_with(
            [a, b],
            health_scorer=HealthScorer(),
            health_bonus_range=0.0,
        )
        br = r._breaker_for("alpha")
        br._state = "open"
        br._opened_at = 1e18
        cands = r._candidates(Capability.CHAT_COMPLETE, RouteContext())
        # Pure priority tie → alphabetical.
        assert [c.name for c in cands] == ["alpha", "beta"]

    def test_negative_bonus_range_rejected(self):
        with pytest.raises(ValueError):
            _router_with(
                [_StubAdapter(capabilities={Capability.CHAT_COMPLETE})],
                health_bonus_range=-1.0,
            )

    def test_scorer_accessor_exposes_attached_scorer(self):
        scorer = HealthScorer()
        r = _router_with(
            [_StubAdapter(capabilities={Capability.CHAT_COMPLETE})],
            health_scorer=scorer,
        )
        assert r.health_scorer is scorer

    def test_scorer_accessor_none_by_default(self):
        r = _router_with([_StubAdapter(capabilities={Capability.CHAT_COMPLETE})])
        assert r.health_scorer is None


class TestScoreForAdapter:
    def test_no_signals_returns_none(self):
        r = _router_with(
            [_StubAdapter(name="ghost", capabilities={Capability.CHAT_COMPLETE})],
            health_scorer=HealthScorer(),
        )
        assert r._score_for_adapter("ghost") is None

    def test_breaker_signal_alone_produces_score(self):
        r = _router_with(
            [_StubAdapter(name="x", capabilities={Capability.CHAT_COMPLETE})],
            health_scorer=HealthScorer(),
        )
        r._breaker_for("x")  # creates a closed breaker
        score = r._score_for_adapter("x")
        assert score is not None
        assert score == 1.0

    def test_open_breaker_drives_score_down(self):
        r = _router_with(
            [_StubAdapter(name="x", capabilities={Capability.CHAT_COMPLETE})],
            health_scorer=HealthScorer(),
        )
        br = r._breaker_for("x")
        br._state = "open"
        br._opened_at = 1e18
        score = r._score_for_adapter("x")
        assert score is not None
        assert score < 0.5

    def test_unknown_adapter_name_returns_none(self):
        r = _router_with(
            [_StubAdapter(name="x", capabilities={Capability.CHAT_COMPLETE})],
            health_scorer=HealthScorer(),
        )
        assert r._score_for_adapter("no-such-adapter") is None
