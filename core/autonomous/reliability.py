"""Reliability signal collector for the autonomous controller —
Option E.

Every autonomous cycle pays for its own adapter telemetry: the
router increments SLA counters, the circuit breakers open and
close, the dead-letter ledger records exhausted calls, the cost
ledger attributes spend to the controller's ``caller`` tag. Until
Option E, none of that signal fed back into the controller's own
decision loop — the dashboard saw it, but the reflection layer
never learned "adapter X is on fire, stop scheduling work that
depends on it."

This module bundles the adapter layer's four read-only snapshot
APIs (``HealthScorer``, ``DeadLetterLedger.snapshot``,
``CostLedger.snapshot``, ``get_breaker_stats``) into a single
``collect_reliability_signal()`` call that:

  * Returns a small JSON-safe dict the controller embeds on
    ``cycle_result["phases"]["reliability"]`` every tick.
  * Surfaces counts only — no raw params, no PII, no big
    structures. The Reliability dashboard has the details.
  * Computes a **delta** vs. the previous tick for dead-letter
    entries and total cost so the controller can see "what
    happened since my last look" without re-scanning ledgers.
  * Returns an ``alert`` dict when any signal crosses a
    threshold (unhealthy adapter, new dead-letter entry,
    budget burn rate spike). The controller maps this into a
    phase_error record so the reflection synthesizer mines it.

The design is deliberately additive and defensive:

* Every collector call is wrapped in a try/except with a
  WARNING log — the cycle never breaks because an optional
  telemetry stream raised.
* Every threshold has an env-var override so operators can
  tune sensitivity without code changes.
* The module carries its own tick-to-tick state so the
  controller stays stateless about reliability accounting.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger

logger = get_logger("autonomous.reliability")


# ── Thresholds (env-tunable) ───────────────────────────────

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


# How many unhealthy adapters can exist before we alert.
_UNHEALTHY_ALERT_AT = _env_int("SHOPAI_RELIABILITY_UNHEALTHY_AT", 1)
# How many *new* dead-letter entries (since last tick) we tolerate.
_NEW_DEADLETTER_ALERT_AT = _env_int("SHOPAI_RELIABILITY_DEADLETTER_AT", 1)
# Cost-spike threshold: $ spent in one cycle.
_COST_SPIKE_USD = _env_float("SHOPAI_RELIABILITY_COST_SPIKE_USD", 1.0)


# ── Per-cycle delta accounting ─────────────────────────────


@dataclass
class _ReliabilityState:
    """Cross-cycle bookkeeping kept inside the collector so the
    controller doesn't have to manage per-tick deltas by hand."""
    last_deadletter_total: int = 0
    last_cost_total_usd: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


_STATE = _ReliabilityState()


def reset_reliability_state() -> None:
    """Reset the cross-cycle delta baseline.

    Tests wipe this between cycles so they can assert exact
    per-tick deltas. Production code never calls this — the
    process-lifetime accumulator is exactly right there.
    """
    with _STATE.lock:
        _STATE.last_deadletter_total = 0
        _STATE.last_cost_total_usd = 0.0


# ── Individual collectors (guarded) ────────────────────────


def _collect_health() -> dict[str, Any]:
    """Composite adapter health rollup via ``HealthScorer``.

    Returns ``{totals: {...}, unhealthy: [...], degraded: [...]}``
    so the controller can see which adapters are compromised
    without the full per-adapter table.
    """
    try:
        from core.adapters import router as _router_mod
        from core.adapters.health import HealthScorer
        from core.adapters.metrics import get_metrics
        from core.adapters.rate_limit import get_rate_limiter
        from core.adapters.retry import get_retry_telemetry
        from core.adapters.sla import SLAMonitor
    except Exception as exc:  # noqa: BLE001
        logger.debug("reliability: health deps missing: %s", exc)
        return {
            "totals": {}, "unhealthy": [], "degraded": [],
            "error": f"missing deps: {exc}",
        }

    # SLA rows — evaluate against the default budget catalog.
    try:
        metrics_snap = get_metrics().snapshot()
        sla_rows = SLAMonitor().evaluate_all(metrics_snap)
        sla_rows = [r.to_dict() for r in sla_rows]
    except Exception as exc:  # noqa: BLE001
        logger.debug("reliability: sla snapshot failed: %s", exc)
        sla_rows = []

    # Breakers — only if router singleton already constructed.
    breakers: list[dict[str, Any]] = []
    try:
        router = getattr(_router_mod, "_router", None)
        if router is not None:
            raw = router.breaker_snapshot()
            for name, snap in (raw or {}).items():
                breakers.append({
                    "adapter": name,
                    "state": snap.get("state", "closed"),
                    "consecutive_failures": snap.get(
                        "consecutive_failures", 0,
                    ),
                    "trips": snap.get("trips", 0),
                })
    except Exception as exc:  # noqa: BLE001
        logger.debug("reliability: breaker snapshot failed: %s", exc)

    # Rate-limit rows.
    try:
        rate_rows = get_rate_limiter().snapshot()
    except Exception as exc:  # noqa: BLE001
        logger.debug("reliability: rate snapshot failed: %s", exc)
        rate_rows = []

    # Retry per-adapter rows.
    try:
        retry_snap = get_retry_telemetry().snapshot()
        retry_rows = []
        for name, row in (retry_snap.get("per_adapter") or {}).items():
            calls = int(row.get("calls", 0) or 0)
            successes = int(row.get("successes", 0) or 0)
            retry_rows.append({
                "adapter": name,
                "calls": calls,
                "retries": int(row.get("retries", 0) or 0),
                "giveups": int(row.get("giveups", 0) or 0),
                "successes": successes,
                "success_rate": (
                    (successes / calls) if calls > 0 else 0.0
                ),
            })
    except Exception as exc:  # noqa: BLE001
        logger.debug("reliability: retry snapshot failed: %s", exc)
        retry_rows = []

    try:
        scorer = HealthScorer()
        rows = scorer.score_all(
            sla_rows=sla_rows,
            breakers=breakers,
            rate_rows=rate_rows,
            retry_per_adapter=retry_rows,
        )
        totals = HealthScorer.totals(rows)
        unhealthy = [r.adapter for r in rows if r.grade == "unhealthy"]
        degraded = [r.adapter for r in rows if r.grade == "degraded"]
        return {
            "totals": totals,
            "unhealthy": unhealthy,
            "degraded": degraded,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("reliability: scoring failed: %s", exc)
        return {
            "totals": {}, "unhealthy": [], "degraded": [],
            "error": str(exc),
        }


def _collect_deadletter() -> dict[str, Any]:
    """Dead-letter ledger summary: total records + recent new entries
    since the previous cycle."""
    try:
        from core.adapters.deadletter import get_dead_letter_ledger
    except Exception as exc:  # noqa: BLE001
        logger.debug("reliability: deadletter deps missing: %s", exc)
        return {"size": 0, "total_records": 0, "new_since_last": 0}

    try:
        snap = get_dead_letter_ledger().snapshot()
    except Exception as exc:  # noqa: BLE001
        logger.warning("reliability: deadletter snapshot failed: %s", exc)
        return {"size": 0, "total_records": 0, "new_since_last": 0,
                "error": str(exc)}

    total = int(snap.get("total_records", 0) or 0)
    with _STATE.lock:
        new_since = max(0, total - _STATE.last_deadletter_total)
        _STATE.last_deadletter_total = total
    return {
        "size": int(snap.get("size", 0) or 0),
        "total_records": total,
        "new_since_last": new_since,
        "per_adapter": snap.get("per_adapter") or {},
        "write_failures": int(snap.get("write_failures", 0) or 0),
    }


def _collect_cost() -> dict[str, Any]:
    """Cost attribution summary: total usd, delta since last tick,
    top caller."""
    try:
        from core.adapters.cost_ledger import get_cost_ledger
    except Exception as exc:  # noqa: BLE001
        logger.debug("reliability: cost deps missing: %s", exc)
        return {"total_usd": 0.0, "delta_usd": 0.0, "top_caller": ""}

    try:
        ledger = get_cost_ledger()
        total = float(ledger.total_usd())
        callers = ledger.per_caller()
    except Exception as exc:  # noqa: BLE001
        logger.warning("reliability: cost snapshot failed: %s", exc)
        return {"total_usd": 0.0, "delta_usd": 0.0, "top_caller": "",
                "error": str(exc)}

    with _STATE.lock:
        delta = max(0.0, total - _STATE.last_cost_total_usd)
        _STATE.last_cost_total_usd = total
    top_caller = callers[0]["caller"] if callers else ""
    return {
        "total_usd": round(total, 6),
        "delta_usd": round(delta, 6),
        "top_caller": top_caller,
        "caller_count": len(callers),
    }


# ── Public entrypoint ──────────────────────────────────────


def collect_reliability_signal() -> dict[str, Any]:
    """Return a JSON-safe reliability snapshot for the current cycle.

    Shape::

        {
            "timestamp":   <float>,
            "health":      {"totals": {...}, "unhealthy": [...], "degraded": [...]},
            "deadletter":  {"size": N, "total_records": N, "new_since_last": N, ...},
            "cost":        {"total_usd": F, "delta_usd": F, "top_caller": S, ...},
            "alerts":      [<str>, ...],   # non-empty triggers a phase_error
        }

    ``alerts`` are human-readable strings suitable for both
    logging and as the message field of a reflection-mined
    pattern. They are populated when any of the tunable
    thresholds defined at module level are crossed.
    """
    health = _collect_health()
    deadletter = _collect_deadletter()
    cost = _collect_cost()

    alerts: list[str] = []
    unhealthy = health.get("unhealthy") or []
    if len(unhealthy) >= _UNHEALTHY_ALERT_AT:
        alerts.append(
            f"{len(unhealthy)} adapter(s) unhealthy: "
            f"{','.join(sorted(unhealthy))}"
        )
    new_dl = int(deadletter.get("new_since_last", 0))
    if new_dl >= _NEW_DEADLETTER_ALERT_AT:
        alerts.append(
            f"{new_dl} new dead-letter entry(s) since last cycle"
        )
    delta_usd = float(cost.get("delta_usd", 0.0))
    if delta_usd >= _COST_SPIKE_USD:
        alerts.append(
            f"cost spike ${delta_usd:.4f} in one cycle "
            f"(top_caller={cost.get('top_caller') or '-'})"
        )

    return {
        "timestamp": time.time(),
        "health": health,
        "deadletter": deadletter,
        "cost": cost,
        "alerts": alerts,
    }
