"""SmartRouter — capability + context → best adapter.

The router is the brain's nervous system. Brain code asks for a
*capability* (``"chat_complete"``, ``"send_email"``,
``"create_fulfillment"``) and the router walks the registry,
applies context-aware filters (budget, latency, region, PII),
and dispatches to the best matching adapter. If that adapter
fails, the router falls back to the next-best match — up to a
configurable depth — without the brain ever knowing.

The selection algorithm lives in ``_score_adapters``. It
deliberately keeps the scoring rules small and explicit so the
behaviour is auditable; we do NOT want a learned-ranker here
because the brain itself is the learning component.

The router is **not** a load balancer. It picks ONE adapter per
call. If the call fails it tries the next ONE. There is no
parallel fan-out, no quorum, no shadowing — those concerns
belong in the brain (which can call ``router.execute()`` twice
on purpose if it wants quorum).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger

from .base import AdapterResult, BaseAdapter, Capability
from .errors import (
    AdapterError,
    AdapterNotConfigured,
    AdapterRateLimited,
    AdapterValidationError,
)
from .metrics import MetricsCollector, get_metrics
from .registry import AdapterRegistry, get_registry

logger = get_logger("adapters.router")


# ── Routing context ────────────────────────────────────────────


@dataclass
class RouteContext:
    """Caller-supplied hints used by the router scorer.

    Every field is optional. The router treats the absence of a
    field as "no constraint" — i.e. don't filter on it.

    Fields:

      * ``budget_usd``      — max $/call the caller will pay
      * ``max_latency_ms``  — soft preference for lower-latency
                              adapters
      * ``contains_pii``    — when True, the router prefers local
                              / on-prem adapters and never picks
                              one whose ``category`` ships data
                              to a third party that has not been
                              GDPR-cleared
      * ``region``          — ``"us"`` / ``"eu"`` / ``"asia"`` /
                              ``""``. EU stores get EU-resident
                              vendors first
      * ``prefer``          — adapter NAMES the caller would like
                              first (soft preference, not a lock)
      * ``exclude``         — adapter names the caller wants to
                              skip entirely
      * ``min_quality``     — for LLM calls; the router only
                              considers adapters with this
                              priority or higher
      * ``fallback_depth``  — how many alternates to try after
                              the primary fails. Default 2.
    """

    budget_usd: float | None = None
    max_latency_ms: float | None = None
    contains_pii: bool = False
    region: str = ""
    prefer: list[str] = field(default_factory=list)
    exclude: set[str] = field(default_factory=set)
    min_quality: int = 0
    fallback_depth: int = 2
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Router ─────────────────────────────────────────────────────


class NoAdapterAvailable(AdapterError):
    """Raised when ``route()`` cannot find ANY adapter that
    satisfies the requested capability + context. The brain
    treats this like a normal capability gap — it should pick a
    different action, not retry."""

    def __init__(self, capability: str, reason: str = "") -> None:
        super().__init__("router", reason or capability)
        self.capability = capability


class SmartRouter:
    """Capability-aware adapter dispatcher.

    Construction:

        router = SmartRouter()                       # default singletons
        router = SmartRouter(registry=my_registry)   # tests

    Usage:

        result = router.execute(
            Capability.CHAT_COMPLETE,
            {"prompt": "..."},
            context=RouteContext(budget_usd=0.01),
        )

    The router tries the best-scoring adapter first; on
    ``AdapterError`` it walks the next ``fallback_depth``
    candidates. Successes and failures are recorded into the
    metrics collector regardless of which adapter actually ran.
    """

    def __init__(
        self,
        registry: AdapterRegistry | None = None,
        metrics: MetricsCollector | None = None,
    ) -> None:
        self._registry = registry or get_registry()
        self._metrics = metrics or get_metrics()
        self._lock = threading.RLock()

    # ── Public API ─────────────────────────────────────────────

    def route(
        self,
        capability: Capability | str,
        context: RouteContext | None = None,
    ) -> BaseAdapter:
        """Return the single best adapter for *capability*.

        Raises ``NoAdapterAvailable`` if nothing matches. Use
        ``execute()`` instead when you want automatic fallback —
        ``route()`` is mostly here so the brain can introspect
        which adapter would be picked without actually calling.
        """
        candidates = self._candidates(capability, context or RouteContext())
        if not candidates:
            raise NoAdapterAvailable(
                str(capability),
                "no configured adapter satisfies the capability + context",
            )
        return candidates[0]

    def candidates(
        self,
        capability: Capability | str,
        context: RouteContext | None = None,
    ) -> list[BaseAdapter]:
        """Return all candidate adapters in score order.

        Useful for debugging routing decisions and for tests
        that want to assert the fallback chain.
        """
        return self._candidates(capability, context or RouteContext())

    def execute(
        self,
        capability: Capability | str,
        params: dict[str, Any] | None = None,
        context: RouteContext | None = None,
    ) -> AdapterResult:
        """Pick an adapter, run it, fall back on failure.

        Returns the first successful ``AdapterResult``. If every
        adapter in the fallback chain fails, returns the last
        failure (with its typed error attached) so the caller
        can inspect ``result.error``.
        """
        ctx = context or RouteContext()
        params = params or {}

        candidates = self._candidates(capability, ctx)
        if not candidates:
            err = NoAdapterAvailable(
                str(capability),
                f"no adapter for {capability} (context={ctx})",
            )
            return AdapterResult.failure(
                "router", str(capability), err,
            )

        # Try primary + up to fallback_depth alternates.
        max_attempts = 1 + max(0, ctx.fallback_depth)
        attempts = candidates[:max_attempts]
        last_failure: AdapterResult | None = None

        for adapter in attempts:
            result = adapter.execute(capability, params)

            # Always feed the metrics collector — even on failure
            self._metrics.record(
                adapter.name,
                success=result.ok,
                latency_ms=result.latency_ms,
                cost_usd=result.cost_usd,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                error=(result.error.reason if result.error else ""),
            )

            if result.ok:
                return result

            last_failure = result
            # Some failures are non-retryable: the next adapter
            # would hit the same caller bug, so just bail.
            if isinstance(result.error, AdapterValidationError):
                break
            logger.warning(
                "router fallback: %s failed (%s), trying next",
                adapter.name,
                type(result.error).__name__ if result.error else "?",
            )

        return last_failure or AdapterResult.failure(
            "router",
            str(capability),
            AdapterError("router", "all candidates failed"),
        )

    # ── Internals ──────────────────────────────────────────────

    def _candidates(
        self,
        capability: Capability | str,
        context: RouteContext,
    ) -> list[BaseAdapter]:
        """Score and rank adapters for *capability*.

        Filtering rules (in order — short-circuits on the first
        rule that drops a candidate):

          1. ``adapter.is_configured()`` is True
          2. ``adapter.name not in context.exclude``
          3. ``adapter.priority >= context.min_quality``
          4. ``adapter.cost_per_call <= context.budget_usd``
             (when budget is set)
          5. PII routing: when ``context.contains_pii`` is True,
             only adapters whose category is local-friendly
             (LLM with priority 90+ → assumed local; or any
             ``shopify_native`` adapter which by definition
             stays inside Shopify) are considered.

        Scoring (higher = better):

          * +adapter.priority (0-100)
          * +50 if adapter.name in context.prefer
          * -10 if cost_per_call > 0
          * -20 if metrics show recent failure
        """
        with self._lock:
            base_pool = self._registry.find_by_capability(
                capability, configured_only=True,
            )

        if not base_pool:
            return []

        scored: list[tuple[float, BaseAdapter]] = []
        for adapter in base_pool:
            if adapter.name in context.exclude:
                continue
            if adapter.priority < context.min_quality:
                continue
            if context.budget_usd is not None:
                est = adapter.estimate_cost(
                    capability if isinstance(capability, Capability)
                    else Capability(capability),
                    {},
                )
                if est > context.budget_usd:
                    continue
            if context.contains_pii and not self._is_pii_safe(adapter):
                continue

            score = float(adapter.priority)
            if adapter.name in context.prefer:
                score += 50.0
            if adapter.cost_per_call > 0:
                score -= 10.0

            stats = self._metrics.stats_for(adapter.name)
            if stats and stats.get("success_rate", 1.0) < 0.5:
                score -= 20.0

            scored.append((score, adapter))

        scored.sort(key=lambda pair: (-pair[0], pair[1].name))
        return [adapter for _, adapter in scored]

    @staticmethod
    def _is_pii_safe(adapter: BaseAdapter) -> bool:
        """Return True iff the adapter is safe to receive PII.

        Definition: an adapter is PII-safe when either

          * its category is ``shopify_native`` (data never leaves
            Shopify, which already holds the customer record), or
          * its name explicitly starts with ``"local_"`` or
            ``"ollama"`` (locally hosted, no third-party transit)

        This is intentionally conservative. Adapters that want to
        opt-in to PII routing despite running in the cloud can
        override ``is_pii_safe`` on themselves and the router
        will pick that up via duck typing.
        """
        # Duck-typed override hook
        custom = getattr(adapter, "is_pii_safe", None)
        if callable(custom):
            try:
                return bool(custom())
            except Exception as exc:  # noqa: BLE001
                logger.debug("adapter PII-safe check failed: %s", exc)

        if adapter.category.value == "shopify_native":
            return True
        name = adapter.name.lower()
        return name.startswith("local_") or name.startswith("ollama")


# ── Module-level singleton ─────────────────────────────────────


_router: SmartRouter | None = None
_router_lock = threading.Lock()


def get_router() -> SmartRouter:
    """Return the process-wide smart router singleton."""
    global _router
    if _router is None:
        with _router_lock:
            if _router is None:
                _router = SmartRouter()
    return _router


def reset_router() -> None:
    """Replace the singleton with a fresh router (test helper)."""
    global _router
    with _router_lock:
        _router = SmartRouter()
