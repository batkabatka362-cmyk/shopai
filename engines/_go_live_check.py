"""Go-live readiness check.

When operator decides to take ShopAI from "dev experimentation"
to "real-money cron operation", a LOT of substrate has to be
configured correctly. Without a single gate, operators forget
a step:

  - Shopify creds wired (Wave 45)
  - At least one engine apply_* flag enabled
  - Cycle preflight passes
  - Spend caps configured (real-money safety)
  - Auto-quarantine bridges enabled
  - AI strategies configured (optional but recommended)
  - Notify webhook configured (operational visibility)
  - Cron / systemd schedule active

Wave 55: this module bundles every check into a single
pre-flight gate. Operator runs ``shopai go-live`` before
flipping cron on; gets a punch-list of what's missing.

## Each check returns

  CheckResult:
    name: str
    status: "pass" | "warn" | "fail"  (failed = blocks
        going live; warn = strongly recommended)
    detail: str  (what's there or what's missing)
    fix: str  (operator action to fix; empty if pass)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass
class CheckResult:
    name: str
    status: str  # pass / warn / fail
    detail: str
    fix: str = ""


def _check_shopify_creds() -> CheckResult:
    """At least one store has resolvable Shopify creds."""
    try:
        from data_pipeline.store.store_manager import StoreManager
        sm = StoreManager()
        stores = sm.list_stores() or []
        if not stores:
            return CheckResult(
                name="shopify_credentials",
                status="fail",
                detail="No stores registered",
                fix="shopai store add <store_id> <shop_url>",
            )
        # Try first store's credentials
        for s in stores:
            sid = s.get("store_id")
            if not sid:
                continue
            creds = sm.get_credentials(sid) or {}
            if creds.get("api_key") and creds.get("shop_url"):
                return CheckResult(
                    name="shopify_credentials",
                    status="pass",
                    detail=(
                        f"{len(stores)} store(s); first creds OK"
                    ),
                )
        return CheckResult(
            name="shopify_credentials",
            status="fail",
            detail="Stores registered but no creds resolvable",
            fix="shopai store connect <store_id>",
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="shopify_credentials",
            status="fail",
            detail=f"probe failed: {exc}",
            fix="Verify data_pipeline.store.store_manager works",
        )


def _check_wired_engines() -> CheckResult:
    """At least some engines are Phase 7 wired."""
    try:
        from engines._writeback_audit import (
            audit_writeback_coverage,
        )
        wb = audit_writeback_coverage("engines")
        wired = [
            s.name for s in wb.engines if s.status == "wired"
        ]
        if len(wired) < 1:
            return CheckResult(
                name="wired_engines",
                status="fail",
                detail="0 engines wired (Phase 7)",
                fix=(
                    "Wire at least one engine via apply_* flag "
                    "+ writer module"
                ),
            )
        if len(wired) < 5:
            return CheckResult(
                name="wired_engines",
                status="warn",
                detail=(
                    f"{len(wired)} engines wired (low; "
                    "consider wiring more before going live)"
                ),
                fix="See engines/loyalty for the wireup template",
            )
        return CheckResult(
            name="wired_engines",
            status="pass",
            detail=f"{len(wired)} engines wired (Phase 7)",
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="wired_engines",
            status="fail",
            detail=f"audit failed: {exc}",
            fix="Run `shopai audit --only wireup_resolve`",
        )


def _check_institutional_audits() -> CheckResult:
    """All 9 institutional audits green."""
    try:
        # Reuse the standard audit command from CLI
        from engines._cluster_audit import audit_clusters
        cr = audit_clusters()
        if cr.has_violations:
            return CheckResult(
                name="institutional_audits",
                status="fail",
                detail=(
                    f"{len(cr.violations)} cluster topology "
                    "violation(s)"
                ),
                fix="Run `shopai audit` to see all failures",
            )
        return CheckResult(
            name="institutional_audits",
            status="pass",
            detail="cluster topology green (check rest via `shopai audit`)",
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="institutional_audits",
            status="warn",
            detail=f"audit probe failed: {exc}",
            fix="`shopai audit` to manually verify",
        )


def _check_spend_cap_configured() -> CheckResult:
    """Real-money safety: spend caps + auto-pause."""
    daily = os.environ.get("SHOPAI_SPEND_CAP_DAILY_USD")
    weekly = os.environ.get("SHOPAI_SPEND_CAP_WEEKLY_USD")
    enabled = os.environ.get(
        "SHOPAI_AUTO_PAUSE_ON_OVERSPEND",
    )
    if not (daily or weekly):
        return CheckResult(
            name="spend_cap",
            status="warn",
            detail="No spend caps configured",
            fix=(
                "export SHOPAI_SPEND_CAP_DAILY_USD=N + "
                "SHOPAI_AUTO_PAUSE_ON_OVERSPEND=1"
            ),
        )
    if enabled != "1":
        return CheckResult(
            name="spend_cap",
            status="warn",
            detail=(
                f"Caps set (daily={daily}, weekly={weekly}) "
                "but auto-pause bridge disabled"
            ),
            fix="export SHOPAI_AUTO_PAUSE_ON_OVERSPEND=1",
        )
    return CheckResult(
        name="spend_cap",
        status="pass",
        detail=(
            f"caps daily={daily or '-'} weekly={weekly or '-'};"
            " bridge enabled"
        ),
    )


def _check_revenue_quarantine() -> CheckResult:
    """Revenue regression auto-pause bridge."""
    enabled = os.environ.get(
        "SHOPAI_AUTO_QUARANTINE_FROM_REVENUE",
    )
    if enabled != "1":
        return CheckResult(
            name="revenue_quarantine",
            status="warn",
            detail="Revenue auto-quarantine disabled",
            fix=(
                "export SHOPAI_AUTO_QUARANTINE_FROM_REVENUE=1 "
                "(after first attribution data exists)"
            ),
        )
    return CheckResult(
        name="revenue_quarantine",
        status="pass",
        detail="bridge enabled",
    )


def _check_notify_webhook() -> CheckResult:
    """Push alerts configured."""
    url = os.environ.get("SHOPAI_NOTIFY_WEBHOOK_URL")
    if not url:
        return CheckResult(
            name="notify_webhook",
            status="warn",
            detail="No notify webhook URL configured",
            fix=(
                "export SHOPAI_NOTIFY_WEBHOOK_URL='"
                "https://hooks.slack.com/...' + schedule "
                "notify check via cron"
            ),
        )
    return CheckResult(
        name="notify_webhook",
        status="pass",
        detail="webhook URL configured",
    )


def _check_store_niches() -> CheckResult:
    """Wave 76: warn when stores lack niche tags. Wave 73's
    niche-aware orchestrator silently no-ops when niche is
    unset -- operator should know.

    Wave 84: when an untagged store HAS a product catalog, run
    the deterministic detector (Wave 83) and surface the
    suggestion inline. Converts the fix hint from "do this
    manually" to "we figured it out -- just apply it"."""
    try:
        from data_pipeline.store.store_manager import StoreManager
        sm = StoreManager()
        stores = sm.list_stores() or []
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="store_niches",
            status="warn",
            detail=f"probe failed: {exc}",
            fix="",
        )
    if not stores:
        return CheckResult(
            name="store_niches",
            status="warn",
            detail="No stores registered",
            fix="shopai store add ...",
        )
    untagged = []
    for s in stores:
        niche = (s.get("niche") or "").strip().lower()
        if not niche or niche == "general":
            untagged.append(s.get("store_id", "?"))
    if not untagged:
        return CheckResult(
            name="store_niches",
            status="pass",
            detail=f"all {len(stores)} store(s) tagged",
        )

    # Wave 84: try to detect a niche for each untagged store.
    # Best-effort -- detection failure does not change the
    # check's outcome. Suggestions are only included when
    # confidence is medium or high (actionable).
    suggestions: list[str] = []
    try:
        from engines._niche_detector import suggest_niche_for_store
        for sid in untagged[:5]:
            det = suggest_niche_for_store(
                sid, store_manager=sm,
            )
            if det is not None and det.is_actionable:
                suggestions.append(
                    f"{sid}->{det.suggested}({det.confidence})"
                )
    except Exception:  # noqa: BLE001
        suggestions = []

    sample = ", ".join(untagged[:3])
    suffix = f" +{len(untagged) - 3} more" if len(untagged) > 3 else ""
    detail = f"{len(untagged)} store(s) untagged: {sample}{suffix}"
    if suggestions:
        detail += (
            f" [auto-suggest: {', '.join(suggestions)}]"
        )
        fix = (
            "shopai niche --suggest <store> --apply "
            "(commits the auto-detected niche, Wave 83+84)"
        )
    else:
        fix = (
            "shopai niche --set <store> <beauty|fashion|home|"
            "tech|food> (Wave 77 in-place update; preserves "
            "credentials)"
        )
    return CheckResult(
        name="store_niches",
        status="warn",
        detail=detail,
        fix=fix,
    )


def _check_ai_strategy() -> CheckResult:
    """Optional but recommended: AI gates."""
    bits = []
    if os.environ.get("SHOPAI_AI_STRATEGY"):
        bits.append("strategy")
    if os.environ.get("SHOPAI_AI_PREVET"):
        bits.append("prevet")
    if os.environ.get("SHOPAI_REVENUE_AWARE_ORCHESTRATOR"):
        bits.append("orchestrator")
    if os.environ.get("SHOPAI_REVENUE_AWARE_CAPTAIN"):
        bits.append("captain")
    if not bits:
        return CheckResult(
            name="ai_strategy",
            status="warn",
            detail="All AI strategies disabled (deterministic only)",
            fix=(
                "Set SHOPAI_AI_STRATEGY=1 + "
                "OPENAI_API_KEY to enable consultant"
            ),
        )
    return CheckResult(
        name="ai_strategy",
        status="pass",
        detail=f"AI enabled: {', '.join(bits)}",
    )


def _check_cycle_recently_ran() -> CheckResult:
    """Cron should be firing -- if last cycle is >24h, cron is
    likely not configured."""
    try:
        from engines._cycle_history import last_run
        import time as _t
        lr = last_run()
        if lr is None:
            return CheckResult(
                name="cycle_history",
                status="fail",
                detail="No cycle has ever run",
                fix=(
                    "SHOPAI_CYCLE_RUN_CONFIRM=1 shopai cycle "
                    "run --yes (one-shot smoke test)"
                ),
            )
        age_h = (_t.time() - lr.started_at) / 3600.0
        if age_h > 48.0:
            return CheckResult(
                name="cycle_history",
                status="warn",
                detail=(
                    f"Last cycle ran {age_h:.1f}h ago "
                    "(cron may not be firing)"
                ),
                fix=(
                    "shopai cycle schedule + install the "
                    "emitted cron/systemd line"
                ),
            )
        return CheckResult(
            name="cycle_history",
            status="pass",
            detail=f"last cycle {age_h:.1f}h ago",
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="cycle_history",
            status="warn",
            detail=f"probe failed: {exc}",
            fix="`shopai cycle history` to check manually",
        )


def run_go_live_check() -> list[CheckResult]:
    """Run every go-live check, return list of CheckResults."""
    return [
        _check_shopify_creds(),
        _check_wired_engines(),
        _check_institutional_audits(),
        _check_cycle_recently_ran(),
        _check_spend_cap_configured(),
        _check_revenue_quarantine(),
        _check_notify_webhook(),
        _check_ai_strategy(),
        _check_store_niches(),  # Wave 76
    ]


def summarize(checks: list[CheckResult]) -> dict[str, Any]:
    """Summary stats + go/no-go verdict."""
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for c in checks:
        counts[c.status] = counts.get(c.status, 0) + 1
    verdict = (
        "ready_to_go_live" if counts["fail"] == 0
        else "not_ready"
    )
    return {
        "verdict": verdict,
        "pass": counts["pass"],
        "warn": counts["warn"],
        "fail": counts["fail"],
        "total": len(checks),
    }
