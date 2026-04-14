"""Router + retry + circuit breaker integration — Option R phase 2.

Validates that ``SmartRouter`` honours the injected ``RetryPolicy``
and ``CircuitBreaker`` semantics:

* retries a transient failure on the primary adapter before falling
  back to an alternate
* does NOT retry a permanent failure (validation bugs, auth, etc.)
* records outcomes into the attached ``RetryTelemetry``
* a tripped breaker causes the router to skip that adapter
* a recovered breaker (half-open → success) reopens traffic
"""
from __future__ import annotations

from core.adapters import (
    AdapterCategory,
    AdapterResult,
    AdapterUnavailable,
    AdapterValidationError,
    BaseAdapter,
    Capability,
    RouteContext,
    SmartRouter,
    get_registry,
    reset_registry,
)
from core.adapters.retry import (
    CircuitBreaker,
    RetryPolicy,
    RetryTelemetry,
)


# ── Helpers ─────────────────────────────────────────────────────


class _ScriptedAdapter(BaseAdapter):
    """Adapter whose per-call outcome is driven by a script list."""

    def __init__(
        self,
        *,
        name: str,
        script: list,
        priority: int = 50,
    ) -> None:
        self.name = name
        self.capabilities = {Capability.CHAT_COMPLETE}
        self.category = AdapterCategory.LLM
        self.priority = priority
        self.cost_per_call = 0.0
        super().__init__()
        self._script = list(script)
        self.calls = 0

    def is_configured(self) -> bool:
        return True

    def _execute(self, capability, params):
        self.calls += 1
        if not self._script:
            return AdapterResult.success(
                adapter=self.name, capability=capability.value,
                data={"text": "default"},
            )
        head = self._script.pop(0)
        if isinstance(head, Exception):
            raise head
        return AdapterResult.success(
            adapter=self.name, capability=capability.value, data=head,
        )


def _zero_delay_policy(max_attempts: int = 3) -> RetryPolicy:
    return RetryPolicy(
        max_attempts=max_attempts,
        base_s=0.0,
        multiplier=1.0,
        jitter_pct=0.0,
        max_backoff_s=0.0,
        giveup_after_s=60.0,
    )


# ── Tests ───────────────────────────────────────────────────────


class TestRouterRetriesTransient:
    def test_transient_error_retried_on_primary(self):
        reset_registry()
        primary = _ScriptedAdapter(
            name="primary",
            priority=99,
            script=[
                AdapterUnavailable("primary", "hiccup"),
                {"text": "recovered"},
            ],
        )
        fallback = _ScriptedAdapter(name="fallback", priority=50, script=[])
        reg = get_registry()
        reg.register(primary)
        reg.register(fallback)

        telemetry = RetryTelemetry()
        router = SmartRouter(
            registry=reg,
            retry_policy=_zero_delay_policy(max_attempts=3),
            retry_telemetry=telemetry,
        )
        result = router.execute(
            Capability.CHAT_COMPLETE, {"prompt": "x"},
        )

        assert result.ok
        assert result.adapter == "primary"
        assert primary.calls == 2
        assert fallback.calls == 0
        snap = telemetry.snapshot()
        assert snap["per_adapter"]["primary"]["retries"] >= 1

    def test_primary_exhausted_then_fallback(self):
        reset_registry()
        primary = _ScriptedAdapter(
            name="primary",
            priority=99,
            script=[
                AdapterUnavailable("primary", "down"),
                AdapterUnavailable("primary", "still down"),
                AdapterUnavailable("primary", "down again"),
            ],
        )
        fallback = _ScriptedAdapter(
            name="fallback",
            priority=50,
            script=[{"text": "fallback-ok"}],
        )
        reg = get_registry()
        reg.register(primary)
        reg.register(fallback)

        router = SmartRouter(
            registry=reg,
            retry_policy=_zero_delay_policy(max_attempts=3),
            retry_telemetry=RetryTelemetry(),
        )
        result = router.execute(
            Capability.CHAT_COMPLETE, {"prompt": "x"},
            RouteContext(fallback_depth=1),
        )
        assert result.ok
        assert result.adapter == "fallback"
        assert primary.calls == 3
        assert fallback.calls == 1

    def test_permanent_error_does_not_retry(self):
        reset_registry()
        primary = _ScriptedAdapter(
            name="primary",
            priority=99,
            script=[AdapterValidationError("primary", "bad input")],
        )
        fallback = _ScriptedAdapter(
            name="fallback",
            priority=50,
            script=[{"text": "not reached"}],
        )
        reg = get_registry()
        reg.register(primary)
        reg.register(fallback)

        router = SmartRouter(
            registry=reg,
            retry_policy=_zero_delay_policy(max_attempts=5),
            retry_telemetry=RetryTelemetry(),
        )
        result = router.execute(
            Capability.CHAT_COMPLETE, {"prompt": "x"},
        )
        assert not result.ok
        # Validation failure → no retry, no fallback (caller bug).
        assert primary.calls == 1
        assert fallback.calls == 0


class TestRouterBreakerIntegration:
    def test_breaker_skips_open_adapter(self):
        reset_registry()
        primary = _ScriptedAdapter(
            name="primary",
            priority=99,
            script=[{"text": "would succeed"}],
        )
        fallback = _ScriptedAdapter(
            name="fallback",
            priority=50,
            script=[{"text": "from fallback"}],
        )
        reg = get_registry()
        reg.register(primary)
        reg.register(fallback)

        # Construct the router and pre-open the primary's breaker.
        router = SmartRouter(
            registry=reg,
            retry_policy=_zero_delay_policy(max_attempts=1),
            retry_telemetry=RetryTelemetry(),
            breaker_factory=lambda name: CircuitBreaker(
                name=name, fail_threshold=1, reset_after_s=60.0,
            ),
        )
        router._breaker_for("primary").record_failure()
        assert router._breaker_for("primary").state == "open"

        result = router.execute(
            Capability.CHAT_COMPLETE, {"prompt": "x"},
        )
        assert result.ok
        assert result.adapter == "fallback"
        assert primary.calls == 0

    def test_consecutive_failures_trip_breaker(self):
        reset_registry()
        primary = _ScriptedAdapter(
            name="primary",
            priority=99,
            script=[
                AdapterUnavailable("primary", "down"),
                AdapterUnavailable("primary", "down"),
            ],
        )
        fallback = _ScriptedAdapter(
            name="fallback",
            priority=50,
            script=[{"text": "ok"}, {"text": "ok-again"}],
        )
        reg = get_registry()
        reg.register(primary)
        reg.register(fallback)

        router = SmartRouter(
            registry=reg,
            retry_policy=_zero_delay_policy(max_attempts=1),
            retry_telemetry=RetryTelemetry(),
            breaker_factory=lambda name: CircuitBreaker(
                name=name, fail_threshold=2, reset_after_s=60.0,
            ),
        )
        # Two separate router.execute() calls should trip the breaker.
        router.execute(Capability.CHAT_COMPLETE, {"prompt": "a"})
        router.execute(Capability.CHAT_COMPLETE, {"prompt": "b"})
        assert router._breaker_for("primary").state == "open"

    def test_success_closes_breaker(self):
        reset_registry()
        primary = _ScriptedAdapter(
            name="primary",
            priority=99,
            script=[
                AdapterUnavailable("primary", "down"),
                {"text": "back up"},
            ],
        )
        reg = get_registry()
        reg.register(primary)

        router = SmartRouter(
            registry=reg,
            retry_policy=_zero_delay_policy(max_attempts=2),
            retry_telemetry=RetryTelemetry(),
            breaker_factory=lambda name: CircuitBreaker(
                name=name, fail_threshold=3, reset_after_s=60.0,
            ),
        )
        result = router.execute(
            Capability.CHAT_COMPLETE, {"prompt": "x"},
        )
        assert result.ok
        assert router._breaker_for("primary").state == "closed"


class TestRouterTelemetryExposed:
    def test_retry_telemetry_accessor(self):
        t = RetryTelemetry()
        router = SmartRouter(registry=get_registry(), retry_telemetry=t)
        assert router.retry_telemetry is t

    def test_breaker_snapshot_lists_seen_adapters(self):
        reset_registry()
        a = _ScriptedAdapter(name="a", priority=10, script=[{"text": "ok"}])
        reg = get_registry()
        reg.register(a)
        router = SmartRouter(
            registry=reg,
            retry_policy=_zero_delay_policy(max_attempts=1),
            retry_telemetry=RetryTelemetry(),
        )
        router.execute(Capability.CHAT_COMPLETE, {"prompt": "x"})
        snap = router.breaker_snapshot()
        assert "a" in snap
        assert snap["a"]["state"] == "closed"

    def test_set_retry_policy_swaps_policy(self):
        router = SmartRouter(registry=get_registry())
        new = _zero_delay_policy(max_attempts=7)
        router.set_retry_policy(new)
        assert router._retry_policy is new
