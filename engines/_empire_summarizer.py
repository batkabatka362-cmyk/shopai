"""Empire-state natural-language summarizer.

At empire scale (20+ stores), the operator's dashboard becomes
information-dense. Wave 67 ships an LLM-consultant summarizer
that reads the full empire state + emits a one-paragraph
English summary the operator can scan in 5 seconds.

Same consultant pattern as Wave 17/24/34/35/49: deterministic
baseline ALWAYS runs first; LLM may REFINE when
``SHOPAI_AI_STRATEGY=1`` + LLM available. The deterministic
output is a template-based sentence; LLM rewrites for natural
flow when enabled.

## Output shape

EmpireSummary:
  text: str          -- the paragraph
  used_llm: bool     -- whether LLM refined
  key_facts: dict    -- raw data the summary distilled
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EmpireSummary:
    text: str
    used_llm: bool = False
    key_facts: dict[str, Any] = field(default_factory=dict)


def _collect_facts(
    store_id: str | None = None,
) -> dict[str, Any]:
    """Gather every signal the summary needs in one pass.

    Wave 69: when store_id is provided, scope per-store. Cycle
    history stays fleet-wide (cycle is fleet-level) but
    attribution + spend + approval + quarantine all filter to
    the store.
    """
    facts: dict[str, Any] = {"scope_store_id": store_id}
    # Stores
    try:
        from data_pipeline.store.store_manager import StoreManager
        stores = StoreManager().list_stores() or []
        facts["store_count"] = len(stores)
    except Exception:  # noqa: BLE001
        facts["store_count"] = None

    # Last cycle (fleet-wide; per-store filter via runs_for_store
    # would surface only cycles that touched this store)
    try:
        from engines._cycle_history import (
            last_run, runs_for_store,
        )
        if store_id:
            store_runs = runs_for_store(store_id, limit=1)
            lr = store_runs[0] if store_runs else None
        else:
            lr = last_run()
        if lr is not None:
            import time as _t
            facts["last_cycle_age_hours"] = round(
                (_t.time() - lr.started_at) / 3600.0, 1,
            )
            facts["last_cycle_verdict"] = lr.verdict
            facts["last_cycle_ok"] = lr.total_ok
            facts["last_cycle_errors"] = lr.total_errors
    except Exception:  # noqa: BLE001
        pass

    # Revenue attribution (per-store when scoped)
    try:
        from engines._attribution_snapshot import (
            fleet_attribution_rollup, last_snapshot,
        )
        from engines._attribution_delta import latest_delta
        rollup = fleet_attribution_rollup()
        snap = last_snapshot(store_id=store_id)
        delta = latest_delta(store_id=store_id)
        facts["attributed_revenue_7d"] = (
            snap.attributed_revenue if snap else 0.0
        )
        facts["stores_with_attribution"] = (
            rollup.get("store_count", 0)
        )
        if snap and snap.per_cluster:
            facts["top_cluster"] = snap.per_cluster[0]["cluster"]
        if snap and snap.per_engine:
            facts["top_engine"] = snap.per_engine[0]["engine"]
        if delta is not None:
            facts["revenue_delta"] = delta.overall_revenue_delta
            facts["regression_alert_count"] = len(delta.alerts)
    except Exception:  # noqa: BLE001
        pass

    # Spend (per-store when scoped)
    try:
        from engines._spend_cap import check_caps
        breaches = check_caps(store_id=store_id)
        facts["spend_breach_count"] = len(breaches)
    except Exception:  # noqa: BLE001
        pass

    # Approvals
    try:
        from core.approval.queue import get_approval_queue
        queue = get_approval_queue()
        facts["pending_count"] = len(queue.list_by_status("pending"))
    except Exception:  # noqa: BLE001
        pass

    # SLA breaches
    try:
        from engines._approval_sla import compute_sla_report
        sla = compute_sla_report()
        facts["sla_breached"] = sla.breached
        facts["sla_aging"] = sla.aging
    except Exception:  # noqa: BLE001
        pass

    # Quarantine
    try:
        from core.approval import quarantine
        state = quarantine.load_state()
        facts["paused_engines"] = len(state.alert_paused or [])
    except Exception:  # noqa: BLE001
        pass

    # Active alerts
    try:
        from engines._notify import collect_alerts
        alerts = collect_alerts()
        facts["alert_count"] = len(alerts)
        facts["alert_kinds"] = sorted(
            {a.kind for a in alerts},
        )
    except Exception:  # noqa: BLE001
        pass

    # Wave 72: transfer scan candidates (fleet-wide only; per-
    # store scope doesn't add value here since transfer is
    # by definition cross-store)
    if not store_id:
        try:
            from engines._transfer_scanner import (
                scan_empire_transfers,
            )
            scan = scan_empire_transfers(top_k=3)
            facts["transfer_candidate_count"] = (
                scan.total_candidates
            )
            if scan.candidates:
                facts["transfer_top_engine"] = (
                    scan.candidates[0].engine
                )
        except Exception:  # noqa: BLE001
            pass

    return facts


def _deterministic_summary(facts: dict[str, Any]) -> str:
    """Template-based summary -- always works without LLM."""
    parts: list[str] = []
    scope_store = facts.get("scope_store_id")
    if scope_store:
        parts.append(f"Store '{scope_store}' summary.")
    else:
        store_count = facts.get("store_count")
        if store_count is not None:
            parts.append(f"{store_count} store(s) registered.")

    age = facts.get("last_cycle_age_hours")
    verdict = facts.get("last_cycle_verdict")
    if age is not None and verdict:
        cycle_str = (
            f"Last cycle ran {age:.1f}h ago ({verdict}, "
            f"{facts.get('last_cycle_ok', 0)} ok / "
            f"{facts.get('last_cycle_errors', 0)} err)."
        )
        parts.append(cycle_str)
    elif age is None:
        parts.append("No cycle has run yet.")

    rev = facts.get("attributed_revenue_7d", 0.0)
    delta = facts.get("revenue_delta")
    if rev > 0:
        rev_str = f"7-day attributed revenue: ${rev:,.2f}"
        if delta is not None:
            rev_str += (
                f" (delta {'+' if delta >= 0 else ''}"
                f"${delta:,.2f})"
            )
        rev_str += "."
        parts.append(rev_str)

    top_cluster = facts.get("top_cluster")
    top_engine = facts.get("top_engine")
    if top_cluster and top_engine:
        parts.append(
            f"Top earners: cluster={top_cluster}, "
            f"engine={top_engine}."
        )

    issues: list[str] = []
    if facts.get("regression_alert_count", 0) > 0:
        issues.append(
            f"{facts['regression_alert_count']} revenue "
            "regression alert(s)"
        )
    if facts.get("spend_breach_count", 0) > 0:
        issues.append(
            f"{facts['spend_breach_count']} spend cap "
            "breach(es)"
        )
    if facts.get("sla_breached", 0) > 0:
        issues.append(
            f"{facts['sla_breached']} approval(s) past SLA"
        )
    if facts.get("paused_engines", 0) > 0:
        issues.append(
            f"{facts['paused_engines']} engine(s) paused"
        )
    if facts.get("alert_count", 0) > 0:
        kinds = facts.get("alert_kinds") or []
        issues.append(
            f"{facts['alert_count']} active alert(s) "
            f"({', '.join(kinds)})"
        )
    if issues:
        parts.append(
            "Issues needing attention: " + "; ".join(issues) + "."
        )
    else:
        parts.append("No active issues -- empire is healthy.")

    pending = facts.get("pending_count", 0)
    if pending > 0:
        parts.append(
            f"{pending} pending approval(s) -- run "
            "`shopai approvals digest` to triage."
        )

    # Wave 72: transfer candidate hint
    transfer_count = facts.get("transfer_candidate_count", 0)
    if transfer_count > 0:
        top_engine = facts.get("transfer_top_engine", "")
        engine_hint = (
            f" (top: {top_engine})" if top_engine else ""
        )
        parts.append(
            f"{transfer_count} cross-store transfer "
            f"candidate(s){engine_hint} -- run "
            "`shopai transfer scan` to drill."
        )

    return " ".join(parts) if parts else "No empire state available."


def _ai_refine(
    facts: dict[str, Any], deterministic: str,
) -> str | None:
    """Ask LLM to rewrite the deterministic summary for natural
    flow. Returns None on any failure / LLM unavailable."""
    import os
    if not os.environ.get("SHOPAI_AI_STRATEGY"):
        return None
    try:
        from engines._ai_strategies import _LLMClient
        llm = _LLMClient()
        if not llm.available:
            return None
    except Exception:  # noqa: BLE001
        return None

    system = (
        "You are the daily-summary writer for ShopAI, an "
        "autonomous Shopify merchant empire. Given empire "
        "state facts + a deterministic baseline summary, "
        "rewrite as ONE concise paragraph (<= 4 sentences) "
        "the operator can read in 5 seconds. Focus on: "
        "what changed since yesterday, what needs operator "
        "attention right now. Return JSON: "
        "{\"summary\": \"...paragraph...\"}."
    )
    user = json.dumps({
        "deterministic_baseline": deterministic,
        "facts": facts,
    })
    resp = llm.chat_json(system, user)
    if resp is None:
        return None
    s = resp.get("summary")
    if not isinstance(s, str) or not s.strip():
        return None
    return s.strip()


def summarize_empire(
    store_id: str | None = None,
) -> EmpireSummary:
    """Produce a one-paragraph empire summary.

    Args:
        store_id: When provided (Wave 69), scope per-store
            instead of fleet-wide. Per-store attribution,
            spend, alerts; cycle history filtered to that
            store's runs.

    Deterministic always; LLM-refined when SHOPAI_AI_STRATEGY=1
    + LLM available.
    """
    facts = _collect_facts(store_id=store_id)
    deterministic = _deterministic_summary(facts)
    refined = _ai_refine(facts, deterministic)
    if refined:
        return EmpireSummary(
            text=refined,
            used_llm=True,
            key_facts=facts,
        )
    return EmpireSummary(
        text=deterministic,
        used_llm=False,
        key_facts=facts,
    )
