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
        _check_autonomy_substrate(),  # Wave 245
        _check_revenue_readiness(),  # W963-1
        _check_phase4_substrate(),  # W963-61
        _check_phase5_autonomy(),   # W963-83
    ]


def _check_phase5_autonomy() -> CheckResult:
    """W963-83: Phase 5 autonomy substrate check.

    Verifies the W963-80 arm_recommender + W963-82 mapping
    are wired and the env-var safety net is configurable.

    Pass: arm_recommender produces output AND mapping is
          imported successfully.
    Warn: substrate ready but SHOPAI_AUTO_DISARM_ON_OVERRIDE
          is unset (operator has visibility but no
          auto-response).
    Fail: arm_recommender import fails or mapping module
          unavailable (Phase 5 substrate broken).
    """
    try:
        from engines.agi_arm_recommender.recommender import (
            recommend,
        )
        from engines.agi_arm_recommender. \
            engine_domain_mapping import (
                domains_used,
            )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="phase5_autonomy",
            status="fail",
            detail=f"Phase 5 module import failed: {exc}",
            fix="reinstall: pip install -e .",
        )
    # Probe recommender
    try:
        r = recommend()
        _ = r.verdict
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="phase5_autonomy",
            status="fail",
            detail=(
                f"arm_recommender probe raised: {exc}"
            ),
            fix=(
                "Run: shopai arm-recommend (manually "
                "to surface error)"
            ),
        )
    # Confirm mapping is populated
    domains = domains_used()
    if not domains:
        return CheckResult(
            name="phase5_autonomy",
            status="fail",
            detail=(
                "engine_to_domain mapping is empty -- no "
                "auto-disarm path possible"
            ),
            fix=(
                "Restore the _ENGINE_TO_DOMAIN catalog in "
                "engine_domain_mapping.py"
            ),
        )
    # Env-var safety net
    if os.environ.get(
        "SHOPAI_AUTO_DISARM_ON_OVERRIDE",
    ) != "1":
        return CheckResult(
            name="phase5_autonomy",
            status="warn",
            detail=(
                f"{len(domains)} autonomy domain(s) "
                "wired but auto-disarm OFF "
                "-- empire has visibility, no response"
            ),
            fix=(
                "export SHOPAI_AUTO_DISARM_ON_OVERRIDE=1 "
                "(empire will auto-disarm spend domains "
                "on critical override)"
            ),
        )
    return CheckResult(
        name="phase5_autonomy",
        status="pass",
        detail=(
            f"{len(domains)} autonomy domain(s) wired + "
            "auto-disarm enabled"
        ),
    )


def _check_phase4_substrate() -> CheckResult:
    """W963-61: verify Phase 4 ritual substrate is wired.

    Probes:
      1. agi_earnings_summary runs without raising.
      2. agi_anomaly_detector runs.
      3. cron_recommender returns an interval.
      4. agi_earnings_history snapshot count + freshness.

    Status:
      pass  -- all four probes OK and snapshots are < 48h old
      warn  -- snapshots stale or count==0 (morning/week
               briefs will return no_data forever otherwise)
      fail  -- a substrate module raised, which means the
               compose-IN/watch-OUT loop is broken
    """
    try:
        from engines.agi_earnings_summary.summarizer import (
            compute_summary,
        )
        from engines.agi_anomaly_detector.detector import (
            detect,
        )
        from engines.cron_recommender.recommender import (
            recommend,
        )
        from engines.agi_earnings_history import store as h
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="phase4_substrate",
            status="fail",
            detail=(
                f"Phase 4 module import failed: {exc}"
            ),
            fix="reinstall: pip install -e .",
        )
    raised: list[str] = []
    for label, fn in (
        ("summary", lambda: compute_summary(days=7)),
        ("anomaly", lambda: detect(window=14)),
        ("cron", lambda: recommend()),
    ):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            raised.append(f"{label}({exc!r})")
    if raised:
        return CheckResult(
            name="phase4_substrate",
            status="fail",
            detail=(
                "Phase 4 probe raised: " + ", ".join(raised)
            ),
            fix=(
                "Run each engine manually: "
                "shopai earnings-summary / anomalies / "
                "cron-recommend"
            ),
        )
    try:
        total = h.snapshot_count()
    except Exception:  # noqa: BLE001
        total = 0
    if total == 0:
        return CheckResult(
            name="phase4_substrate",
            status="warn",
            detail=(
                "0 history snapshots; week-review + "
                "anomaly will return no_data until cron "
                "records a few."
            ),
            fix=(
                "Daily cron: "
                "shopai morning-brief --record (or "
                "shopai earnings-history --record)"
            ),
        )
    # Check freshness of the latest snapshot
    try:
        latest = h.latest()
        if not latest:
            stale = True
        else:
            import time as _t
            ts = float(latest.get("ts", 0) or 0)
            stale = (_t.time() - ts) > (48.0 * 3600.0)
    except Exception:  # noqa: BLE001
        stale = False
    if stale:
        return CheckResult(
            name="phase4_substrate",
            status="warn",
            detail=(
                f"{total} snapshot(s); latest is > 48h old"
            ),
            fix=(
                "Re-enable daily cron: shopai "
                "morning-brief --record"
            ),
        )
    return CheckResult(
        name="phase4_substrate",
        status="pass",
        detail=(
            f"{total} snapshot(s); summary + anomaly + "
            "cron probes OK"
        ),
    )


def _check_revenue_readiness() -> CheckResult:
    """W963-1: revenue-readiness gate.

    Reports a warning when the fleet baseline diagnostic surfaces
    a cold_start / building_traction verdict. Doesn't BLOCK
    go-live (operator may intentionally go live on a cold store
    that they'll seed via day-one bootstrap), but the warning
    surfaces the gap loudly so the next action is obvious.
    """
    try:
        from engines.revenue_readiness import RevenueReadinessEngine
        result = RevenueReadinessEngine().run({})
        data = result.get("data") or {}
        if not data:
            return CheckResult(
                name="revenue_readiness",
                status="warn",
                detail="diagnostic returned no data",
                fix="shopai revenue-readiness --json",
            )
        verdict = data.get("verdict", "unknown")
        passed = data.get("passed", 0)
        total = data.get("total", 0)
        next_action = data.get("next_action") or ""
        if verdict == "earning_active":
            return CheckResult(
                name="revenue_readiness",
                status="pass",
                detail=f"earning_active ({passed}/{total} gates)",
            )
        if verdict == "growing":
            return CheckResult(
                name="revenue_readiness",
                status="pass",
                detail=f"growing ({passed}/{total} gates)",
            )
        return CheckResult(
            name="revenue_readiness",
            status="warn",
            detail=f"{verdict} ({passed}/{total} gates)",
            fix=next_action or (
                "shopai revenue-readiness "
                "(run for per-gate detail)"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="revenue_readiness",
            status="warn",
            detail=f"check raised: {type(exc).__name__}",
            fix="shopai revenue-readiness --json",
        )


def _check_autonomy_substrate() -> CheckResult:
    """Wave 245: the autonomy-doctor verdict gates go-live.

    A mis-wired autonomy substrate (missing cycle hook, missing
    notify alert kinds, missing template piece) won't block
    operator-driven engine fires but it WILL silently break the
    autonomous safety loop (auto-pause won't fire, notify
    webhook won't escalate, status rollup is wrong).

    Catch it BEFORE the operator flips cron on.
    """
    try:
        from core.automation.autonomy_doctor import (
            run_autonomy_doctor,
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="autonomy_substrate",
            status="warn",
            detail=f"doctor module unavailable: {exc}",
            fix="shopai autonomy-doctor",
        )
    try:
        report = run_autonomy_doctor()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="autonomy_substrate",
            status="warn",
            detail=f"doctor crashed: {exc}",
            fix="shopai autonomy-doctor --json",
        )
    if report.fail_count > 0:
        broken = [
            d.name for d in report.domains if d.cls == "fail"
        ]
        return CheckResult(
            name="autonomy_substrate",
            status="fail",
            detail=(
                f"{report.fail_count} domain(s) "
                f"mis-wired: {broken}"
            ),
            fix="shopai autonomy-doctor + drill the [BAD] rows",
        )
    if report.warn_count > 0:
        flagged = [
            d.name for d in report.domains if d.cls == "warn"
        ]
        return CheckResult(
            name="autonomy_substrate",
            status="warn",
            detail=(
                f"{report.warn_count} domain(s) warn: "
                f"{flagged}"
            ),
            fix=(
                f"shopai autonomy-doctor + drill the "
                f"[WRN] rows -- often resolvable via "
                f"-resume or -health --apply-bridge"
            ),
        )
    return CheckResult(
        name="autonomy_substrate",
        status="pass",
        detail=(
            f"{len(report.domains)} domain(s) "
            "wired + nominal"
        ),
    )


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
