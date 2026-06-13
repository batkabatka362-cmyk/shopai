"""Autonomy export (W369): single-shot full-substrate JSON dump.

When the operator hands off a store to another operator, posts
an incident postmortem, or wants to feed substrate state to an
LLM agent for analysis, they need ONE command to dump
everything. autonomy-export composes every per-surface reader
into a single JSON envelope.

Sections in the export:
  - `meta`: timestamp, window_hours, store_id
  - `status`: autonomy_status DomainSummary rollup
  - `doctor`: autonomy_doctor wiring health
  - `smoke`: autonomy_smoke runtime exerciser results
  - `bench`: autonomy_bench latency measurements
  - `env`: Pattern T env knob registry
  - `recent_events`: autonomy_history timeline (capped at 50)
  - `audits`: every pattern-X-audit verdict (from CLI's
    aggregator)

Deliberately read-only -- no calls to pause / resume / bridges.
Safe to run any time.

Useful for:
  - operator handoffs
  - post-incident postmortems
  - empire-wide comparison (one export per store)
  - LLM agent ingestion as decision-time context
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AutonomyExport:
    meta: dict[str, Any] = field(default_factory=dict)
    status: dict[str, Any] = field(default_factory=dict)
    doctor: dict[str, Any] = field(default_factory=dict)
    smoke: dict[str, Any] = field(default_factory=dict)
    bench: dict[str, Any] = field(default_factory=dict)
    env: dict[str, Any] = field(default_factory=dict)
    recent_events: list[dict[str, Any]] = field(
        default_factory=list,
    )
    audits: dict[str, Any] = field(default_factory=dict)


def _safe_dataclass_asdict(obj: Any) -> dict[str, Any]:
    """Best-effort asdict; returns {} on failure."""
    try:
        return asdict(obj)
    except Exception:  # noqa: BLE001
        return {}


def _status_section(
    window_hours: float, store_id: str | None,
) -> dict[str, Any]:
    try:
        from core.automation.autonomy_status import (
            get_autonomy_status,
        )
        r = get_autonomy_status(
            window_hours=window_hours, store_id=store_id,
        )
        return {
            "overall_verdict": r.overall_verdict,
            "overall_next_action": r.overall_next_action,
            "total_applied": r.total_applied,
            "paused_domains": list(r.paused_domains),
            "domains": [
                _safe_dataclass_asdict(d) for d in r.domains
            ],
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"status section failed: {exc!s:.80}"}


def _doctor_section(
    window_hours: float, store_id: str | None,
) -> dict[str, Any]:
    try:
        from core.automation.autonomy_doctor import (
            run_autonomy_doctor,
        )
        r = run_autonomy_doctor(
            window_hours=window_hours, store_id=store_id,
        )
        return {
            "overall_cls": r.overall_cls,
            "overall_next_action": r.overall_next_action,
            "ok": r.ok_count,
            "warn": r.warn_count,
            "fail": r.fail_count,
            "domains": [
                _safe_dataclass_asdict(d) for d in r.domains
            ],
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"doctor section failed: {exc!s:.80}"}


def _smoke_section() -> dict[str, Any]:
    try:
        from core.automation.autonomy_smoke import (
            run_autonomy_smoke,
        )
        r = run_autonomy_smoke()
        return {
            "overall_cls": r.overall_cls,
            "ok": r.ok_count,
            "error": r.error_count,
            "domains": [
                _safe_dataclass_asdict(d) for d in r.domains
            ],
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"smoke section failed: {exc!s:.80}"}


def _bench_section(runs: int) -> dict[str, Any]:
    try:
        from core.automation.autonomy_bench import (
            run_autonomy_bench,
        )
        r = run_autonomy_bench(runs_per_domain=runs)
        return {
            "runs_per_domain": r.runs_per_domain,
            "total_ms": r.total_ms,
            "slowest_domain": r.slowest_domain,
            "slowest_median_ms": r.slowest_median_ms,
            "domains": [
                _safe_dataclass_asdict(d) for d in r.domains
            ],
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"bench section failed: {exc!s:.80}"}


def _env_section() -> dict[str, Any]:
    try:
        from engines._pattern_t_audit import (
            build_autonomy_env_registry,
        )
        r = build_autonomy_env_registry()
        return {
            "total_knobs": r.total_knobs,
            "set_count": r.set_count,
            "knobs": [
                {
                    "name": k.name,
                    "domain": k.domain,
                    "value": k.current_value,
                }
                for k in r.knobs
            ],
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"env section failed: {exc!s:.80}"}


def _events_section(
    window_hours: float,
    store_id: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    try:
        from core.automation.autonomy_history import (
            run_autonomy_history,
        )
        r = run_autonomy_history(
            window_hours=window_hours, store_id=store_id,
        )
        return [
            {
                "timestamp": e.timestamp,
                "domain": e.domain,
                "action": e.action,
                "status": e.status,
                "detail": e.detail,
            }
            for e in r.entries[:limit]
        ]
    except Exception:  # noqa: BLE001
        return []


def _audits_section() -> dict[str, Any]:
    """Best-effort: re-invoke each known per-domain audit and
    record its pass/fail."""
    audits_to_run = [
        ("pattern_w", "engines._pattern_w_audit",
         "run_pattern_w_audit"),
        ("pattern_x", "engines._pattern_x_audit",
         "run_pattern_x_audit"),
        ("pattern_yprime", "engines._pattern_yprime_audit",
         "run_pattern_yprime_audit"),
        ("pattern_ac", "engines._pattern_ac_audit",
         "run_pattern_ac_audit"),
        ("pattern_ad", "engines._pattern_ad_audit",
         "run_pattern_ad_audit"),
        ("pattern_ae", "engines._pattern_ae_audit",
         "run_pattern_ae_audit"),
        ("pattern_af", "engines._pattern_af_audit",
         "run_pattern_af_audit"),
        ("pattern_ag", "engines._pattern_ag_audit",
         "run_pattern_ag_audit"),
        ("pattern_ah", "engines._pattern_ah_audit",
         "run_pattern_ah_audit"),
        ("pattern_ai", "engines._pattern_ai_audit",
         "run_pattern_ai_audit"),
        ("pattern_aj", "engines._pattern_aj_audit",
         "run_pattern_aj_audit"),
        ("pattern_ak", "engines._pattern_ak_audit",
         "run_pattern_ak_audit"),
        ("pattern_al", "engines._pattern_al_audit",
         "run_pattern_al_audit"),
        ("pattern_am", "engines._pattern_am_audit",
         "run_pattern_am_audit"),
        ("pattern_an", "engines._pattern_an_audit",
         "run_pattern_an_audit"),
        ("pattern_ao", "engines._pattern_ao_audit",
         "run_pattern_ao_audit"),
        ("pattern_ap", "engines._pattern_ap_audit",
         "run_pattern_ap_audit"),
        ("pattern_aq", "engines._pattern_aq_audit",
         "run_pattern_aq_audit"),
        ("pattern_ar", "engines._pattern_ar_audit",
         "run_pattern_ar_audit"),
        ("pattern_as", "engines._pattern_as_audit",
         "run_pattern_as_audit"),
    ]
    out: dict[str, Any] = {}
    from importlib import import_module
    for short_name, mod_name, fn_name in audits_to_run:
        try:
            mod = import_module(mod_name)
            fn = getattr(mod, fn_name)
            r = fn()
            out[short_name] = {
                "ok": not r.has_violations,
                "violations": (
                    len(r.violations)
                    if hasattr(r, "violations") else 0
                ),
            }
        except Exception as exc:  # noqa: BLE001
            out[short_name] = {
                "ok": False,
                "error": str(exc)[:80],
            }
    return out


def run_autonomy_export(
    *,
    window_hours: float = 24.0,
    store_id: str | None = None,
    bench_runs: int = 1,
    events_limit: int = 50,
    skip_bench: bool = False,
    skip_audits: bool = False,
) -> AutonomyExport:
    """Assemble the full substrate export."""
    export = AutonomyExport()
    export.meta = {
        "generated_at": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
        ),
        "window_hours": window_hours,
        "store_id": store_id,
    }
    export.status = _status_section(window_hours, store_id)
    export.doctor = _doctor_section(window_hours, store_id)
    export.smoke = _smoke_section()
    if not skip_bench:
        export.bench = _bench_section(bench_runs)
    export.env = _env_section()
    export.recent_events = _events_section(
        window_hours, store_id, events_limit,
    )
    if not skip_audits:
        export.audits = _audits_section()
    return export
