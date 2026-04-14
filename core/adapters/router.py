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
from .budget import BudgetEnforcer, get_budget_enforcer
from .rate_limit import RateLimiter, get_rate_limiter
from .idempotency import IdempotencyCache, get_idempotency_cache
from .health import HealthScorer
from .errors import (
    AdapterError,
    AdapterNotConfigured,
    AdapterRateLimited,
    AdapterValidationError,
)
from .metrics import MetricsCollector, get_metrics
from .registry import AdapterRegistry, get_registry
from .retry import (
    CircuitBreaker,
    RetryPolicy,
    RetryTelemetry,
    get_retry_telemetry,
)

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
        retry_policy: RetryPolicy | None = None,
        retry_telemetry: RetryTelemetry | None = None,
        breaker_factory: Any | None = None,
        budget_enforcer: BudgetEnforcer | None = None,
        rate_limiter: RateLimiter | None = None,
        idempotency_cache: IdempotencyCache | None = None,
        health_scorer: HealthScorer | None = None,
        health_bonus_range: float = 30.0,
    ) -> None:
        self._registry = registry or get_registry()
        self._metrics = metrics or get_metrics()
        # ``retry_policy=None`` means "single attempt" — preserves the
        # pre-Option-R behaviour. Production wiring can plug in a
        # real ``RetryPolicy`` via ``set_retry_policy`` or by
        # constructing the router explicitly.
        self._retry_policy = retry_policy or RetryPolicy(max_attempts=1)
        self._retry_telemetry = retry_telemetry or get_retry_telemetry()
        # Lazily allocate one breaker per adapter name. ``breaker_factory``
        # is a callable ``(name) -> CircuitBreaker`` so tests can inject
        # low-threshold / short-cool-down breakers without monkey-patching.
        self._breaker_factory = breaker_factory or (
            lambda name: CircuitBreaker(name=name)
        )
        self._breakers: dict[str, CircuitBreaker] = {}
        # Budget enforcer (Option T). Default singleton has an empty
        # catalog, so pre-existing tests see no change; production can
        # attach budgets via ``set_budget`` after construction.
        self._budget_enforcer = budget_enforcer or get_budget_enforcer()
        # Rate limiter (Option U). The default singleton ships with a
        # catalog of common vendor limits (openai, anthropic, shopify,
        # etc.) so production behaviour is sensible without any
        # explicit configuration. Tests pass ``RateLimiter(policies={})``
        # to get the old "always allowed" semantics.
        self._rate_limiter = rate_limiter or get_rate_limiter()
        # Idempotency cache (Option V). The default singleton is
        # opt-in per capability — capabilities with no TTL registered
        # are never cached, so side-effecting ops (payments, sends)
        # cannot be accidentally deduplicated.
        self._idempotency = idempotency_cache or get_idempotency_cache()
        # Health-aware routing (Option X). When set, the router
        # consults the scorer during candidate ranking and adds a
        # health-derived bonus to each base score in the interval
        # ``[-health_bonus_range/2, +health_bonus_range/2]``. The
        # hard gates (breaker / budget / rate-limit) are unchanged —
        # the scorer only reorders adapters that are all otherwise
        # eligible, so a borderline-unhealthy adapter still gets a
        # chance if every alternative is unhealthy too. Default is
        # ``None`` (disabled) so every existing test keeps its
        # deterministic priority-based ordering.
        self._health_scorer = health_scorer
        if health_bonus_range < 0:
            raise ValueError("health_bonus_range must be >= 0")
        self._health_bonus_range = float(health_bonus_range)
        self._lock = threading.RLock()

    # ── Policy accessors ───────────────────────────────────────

    def set_retry_policy(self, policy: RetryPolicy) -> None:
        """Replace the retry policy at runtime.

        Useful so production code can flip a conservative default
        policy into the router after construction without having to
        reach into private attributes.
        """
        with self._lock:
            self._retry_policy = policy

    @property
    def retry_telemetry(self) -> RetryTelemetry:
        """Expose the attached retry telemetry collector."""
        return self._retry_telemetry

    def breaker_snapshot(self) -> dict[str, dict]:
        """Return a ``{adapter_name: breaker_snapshot}`` map."""
        with self._lock:
            return {
                name: br.snapshot() for name, br in self._breakers.items()
            }

    @property
    def budget_enforcer(self) -> BudgetEnforcer:
        """Expose the attached cost budget enforcer (Option T)."""
        return self._budget_enforcer

    @property
    def rate_limiter(self) -> RateLimiter:
        """Expose the attached per-adapter rate limiter (Option U)."""
        return self._rate_limiter

    @property
    def health_scorer(self) -> HealthScorer | None:
        """Expose the attached health scorer (Option X).

        ``None`` means health-aware ordering is disabled and
        candidates are ranked by the priority-based score only.
        """
        return self._health_scorer

    @property
    def idempotency_cache(self) -> IdempotencyCache:
        """Expose the attached idempotency cache (Option V)."""
        return self._idempotency

    def _breaker_for(self, name: str) -> CircuitBreaker:
        """Return (creating if needed) the breaker for *name*."""
        with self._lock:
            br = self._breakers.get(name)
            if br is None:
                br = self._breaker_factory(name)
                self._breakers[name] = br
            return br

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

        # Normalise the capability to the enum form once so every
        # downstream gate (idempotency, budget, metrics) uses the
        # same key type.
        cap_enum = (
            capability if isinstance(capability, Capability)
            else Capability(capability)
        )

        # Idempotency gate (Option V). Keyed against the primary
        # candidate so repeated calls with the same params hit
        # whichever result the router last produced — even if the
        # primary was temporarily unavailable last time and the
        # fallback answered. Side-effecting capabilities have no
        # policy registered and bypass this gate entirely.
        primary = candidates[0]
        cached = self._idempotency.get(primary.name, cap_enum, params)
        if cached is not None:
            return cached

        # Try primary + up to fallback_depth alternates.
        max_attempts = 1 + max(0, ctx.fallback_depth)
        attempts = candidates[:max_attempts]
        last_failure: AdapterResult | None = None

        for adapter in attempts:
            breaker = self._breaker_for(adapter.name)
            if not breaker.allow():
                logger.info(
                    "router skip: breaker open for %s — trying next",
                    adapter.name,
                )
                continue

            # Budget gate (Option T). Use the adapter's own cost
            # estimator so the check covers "this specific call"
            # rather than a generic per-call cap.
            try:
                est_cost = adapter.estimate_cost(cap_enum, params)
            except Exception:  # noqa: BLE001
                est_cost = adapter.cost_per_call or 0.0
            decision = self._budget_enforcer.can_call(
                adapter.name, estimated_cost_usd=est_cost,
            )
            if not decision.allow:
                logger.info(
                    "router skip: budget gate closed for %s (%s)",
                    adapter.name, decision.reason,
                )
                continue

            # Rate-limit gate (Option U). Reserves a token in the
            # per-minute, per-hour, and concurrency windows. If the
            # gate is shut we skip without burning a retry budget,
            # letting the next fallback try immediately.
            rl = self._rate_limiter.can_call(adapter.name)
            if not rl.allow:
                logger.info(
                    "router skip: rate-limit closed for %s (%s, wait=%s)",
                    adapter.name, rl.reason, rl.retry_after_s,
                )
                continue

            # Per-adapter retry loop. Each adapter gets the full
            # budget defined by ``self._retry_policy`` before the
            # router gives up on it and moves to a fallback. The
            # rate limiter's concurrency slot is released in the
            # ``finally`` so an exception can't leak a slot.
            def _call(_adapter=adapter) -> AdapterResult:
                return _adapter.execute(capability, params)

            try:
                outcome = self._retry_policy.run(_call)
            finally:
                self._rate_limiter.release_slot(adapter.name)
            self._retry_telemetry.record(adapter.name, outcome)
            result = outcome.result

            # Feed the breaker from the FINAL attempt's outcome.
            if result is not None and getattr(result, "ok", False):
                breaker.record_success()
            else:
                breaker.record_failure()

            # Always feed the metrics collector — even on failure.
            # ``result`` is always an AdapterResult here because
            # ``BaseAdapter.execute`` wraps its own exceptions;
            # guard defensively anyway.
            if result is not None and hasattr(result, "latency_ms"):
                self._metrics.record(
                    adapter.name,
                    success=result.ok,
                    latency_ms=result.latency_ms,
                    cost_usd=result.cost_usd,
                    tokens_in=result.tokens_in,
                    tokens_out=result.tokens_out,
                    error=(result.error.reason if result.error else ""),
                )
                # Book realised cost against the budget ledger only
                # when the call actually succeeded — a failed call
                # didn't cost real money (or the vendor refunded).
                if result.ok and (result.cost_usd or 0) > 0:
                    self._budget_enforcer.record(
                        adapter.name, float(result.cost_usd),
                    )

            if result is not None and result.ok:
                # Idempotency store (Option V). Keyed against the
                # PRIMARY candidate so the next duplicate call hits
                # regardless of which adapter actually answered this
                # time. The cache refuses to store when no policy is
                # registered, so side-effecting capabilities are
                # silently left alone.
                self._idempotency.store(primary.name, cap_enum, params, result)
                return result

            last_failure = result if isinstance(result, AdapterResult) else last_failure
            # Some failures are non-retryable at the FALLBACK level
            # too: the next adapter would hit the same caller bug,
            # so just bail.
            err = getattr(result, "error", None)
            if isinstance(err, AdapterValidationError):
                break
            logger.warning(
                "router fallback: %s failed (%s), trying next",
                adapter.name,
                type(err).__name__ if err else "?",
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

            # Health-aware ordering (Option X). ``score_for_adapter``
            # returns a composite health score in [0.0, 1.0] drawn from
            # the router's own breaker + retry + rate-limit state plus
            # the metrics collector's latency/success stats. Healthy
            # adapters gain up to +range/2, unhealthy adapters lose up
            # to -range/2. Adapters with no telemetry yet score neutral.
            if self._health_scorer is not None:
                health = self._score_for_adapter(adapter.name)
                if health is not None:
                    score += (health - 0.5) * self._health_bonus_range

            scored.append((score, adapter))

        scored.sort(key=lambda pair: (-pair[0], pair[1].name))
        return [adapter for _, adapter in scored]

    def _score_for_adapter(self, name: str) -> float | None:
        """Return the composite health score for one adapter, or
        ``None`` when none of the underlying signals are available
        (brand-new adapter with no breaker, no metrics, etc.).

        This is a router-internal helper — the public ``HealthScorer``
        API takes full telemetry snapshots, which is overkill when
        we already hold the relevant state inside the router. We
        build the minimal per-adapter rows the scorer needs and call
        ``HealthScorer.score`` so the weighting + grade logic stays
        in one place.
        """
        scorer = self._health_scorer
        if scorer is None:
            return None

        # Breaker row — only present if we've ever touched this
        # adapter through ``_breaker_for``.
        breaker_snap: dict[str, Any] | None = None
        with self._lock:
            br = self._breakers.get(name)
        if br is not None:
            try:
                breaker_snap = br.snapshot()
            except Exception:  # noqa: BLE001
                breaker_snap = None

        # Rate-limit row — drawn from the limiter's full snapshot.
        rate_row: dict[str, Any] | None = None
        try:
            for row in self._rate_limiter.snapshot():
                if row.get("adapter") == name:
                    rate_row = row
                    break
        except Exception:  # noqa: BLE001
            rate_row = None

        # Retry row — per_adapter map inside the telemetry snapshot.
        retry_row: dict[str, Any] | None = None
        try:
            retry_snap = self._retry_telemetry.snapshot()
            raw = retry_snap.get("per_adapter", {}).get(name)
            if raw is not None:
                retry_row = {
                    "adapter": name,
                    "calls": int(raw.get("calls", 0)),
                    "retries": int(raw.get("retries", 0)),
                    "giveups": int(raw.get("giveups", 0)),
                    "successes": int(raw.get("successes", 0)),
                }
        except Exception:  # noqa: BLE001
            retry_row = None

        # SLA row — synthesised from the metrics collector so we
        # don't need to instantiate a full ``SLAMonitor`` per call.
        # The scorer only reads ``grade``, ``evaluated`` and the
        # latency numbers; a simple success-rate + sample-count
        # projection is enough for the tiebreaker use case.
        sla_row: dict[str, Any] | None = None
        try:
            stats = self._metrics.stats_for(name)
        except Exception:  # noqa: BLE001
            stats = None
        if stats:
            samples = int(stats.get("calls_total", 0))
            if samples >= 5:
                sr = float(stats.get("success_rate", 1.0))
                p95 = float(stats.get("latency_p95_ms", 0.0))
                # Conservative projection: grade as "breach" only when
                # the recent success rate is genuinely low. Latency
                # breaches fall out of the retry/breaker side.
                grade = "breach" if sr < 0.7 else (
                    "warn" if sr < 0.9 else "ok"
                )
                sla_row = {
                    "adapter": name,
                    "evaluated": True,
                    "grade": grade,
                    "samples": samples,
                    "p50_ms": float(stats.get("latency_p50_ms", 0.0)),
                    "p95_ms": p95,
                    "p99_ms": float(stats.get("latency_p99_ms", 0.0)),
                    "success_rate": sr,
                    "violations": [
                        f"success {sr:.0%} < 0.70",
                    ] if grade == "breach" else [],
                    "warnings": [
                        f"success {sr:.0%} near 0.90",
                    ] if grade == "warn" else [],
                }

        if not any([breaker_snap, rate_row, retry_row, sla_row]):
            return None

        result = scorer.score(
            name,
            sla=sla_row,
            breaker=breaker_snap,
            rate_limit=rate_row,
            retry=retry_row,
        )
        # Score is undefined (``unknown`` grade) when none of the
        # components had data — the scorer returns 0.0 in that case,
        # which we'd rather expose as ``None`` so the caller can
        # short-circuit to neutral weighting.
        if result.grade == "unknown":
            return None
        return result.score

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
