"""Autonomous onboarding wizard.

Wave 92: chains existing substrate (store registration -> first
sync -> niche detection -> launch -> go-live -> schedule) into a
single command. The North Star goal -- "credentials in, earning
out" -- gets a real entry point.

This module is a thin orchestrator: each stage delegates to
existing functions / engines, and the wizard tracks per-stage
status so the operator sees what worked and what's left.

Stages (executed in order):

  1. register      -- StoreManager.add_store
  2. verify_creds  -- sm.test_connection (Wave 93): probe the
                       Shopify token before downstream stages
                       depend on it. Failure SKIPS sync /
                       niche_detect / launch (they can't
                       succeed without working creds) but the
                       wizard still runs go_live + schedule so
                       the operator gets a complete report.
  3. sync          -- first product / order pull from Shopify
  4. niche_detect  -- Wave 83 keyword classifier; auto-applies
                       only when confidence is high (operator can
                       override via niche param)
  5. launch        -- engines.store_setup.launch_orchestrator
                       (policies + pages + discount + collections)
  6. verify_launch -- engines.store_setup.launch_audit (Wave 94):
                       READ-ONLY audit of the 11 launch-readiness
                       gates. Surfaces remaining gaps split by
                       remediation bucket (manual_admin vs
                       launch_closeable) so the operator knows
                       which gaps need their attention vs
                       which can be re-closed autonomously.
  7. go_live       -- engines._go_live_check pre-flight
  8. schedule      -- cron / systemd template emission

Each stage returns a structured OnboardingStage with:
  - name: str
  - status: "success" | "warn" | "fail" | "skipped"
  - detail: str
  - data: dict for downstream stages

Failures in one stage don't poison the others -- the wizard
proceeds with reduced data so the operator gets a complete
punch list, not just the first error.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class OnboardingStage:
    name: str
    status: str  # "success" | "warn" | "fail" | "skipped"
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class OnboardingResult:
    store_id: str
    shop_url: str
    stages: list[OnboardingStage] = field(default_factory=list)
    final_verdict: str = "in_progress"
    # Final "what next" hint for the operator (cron line, or
    # the first failing stage's fix command).
    next_action: str = ""

    @property
    def has_failures(self) -> bool:
        return any(s.status == "fail" for s in self.stages)

    @property
    def has_warnings(self) -> bool:
        return any(s.status == "warn" for s in self.stages)


def onboard_store(
    *,
    store_id: str,
    shop_url: str,
    api_key: str = "",
    client_id: str = "",
    client_secret: str = "",
    name: str = "",
    niche: str = "",
    store_type: str = "dropshipping",
    dry_run: bool = False,
    store_manager: Any = None,
) -> OnboardingResult:
    """Run the full onboarding chain.

    Args:
        store_id: Stable identifier for the store row.
        shop_url: Shopify domain (e.g. ``shop.myshopify.com``).
        api_key: Legacy admin API access token. Mutually
            exclusive with client_id/client_secret.
        client_id / client_secret: OAuth credentials for the
            auto-refresh flow.
        name: Optional human-readable store name.
        niche: Operator-supplied niche. When empty, Wave 83's
            detector runs in stage 3 and auto-applies if
            confidence is high.
        store_type: Store_type column (dropshipping / brand /
            niche / general).
        dry_run: When True, emits the plan without writing
            anything to the DB or hitting Shopify.
        store_manager: Optional StoreManager override (tests).

    Returns:
        OnboardingResult with one OnboardingStage per stage.
    """
    result = OnboardingResult(
        store_id=store_id, shop_url=shop_url,
    )

    # Validate inputs at the boundary so the wizard fails fast
    # rather than producing a half-done state.
    if not store_id or not isinstance(store_id, str):
        result.stages.append(OnboardingStage(
            name="validation",
            status="fail",
            detail="store_id required",
        ))
        result.final_verdict = "failed"
        result.next_action = (
            "Re-run with a valid store_id"
        )
        return result
    if not shop_url or not isinstance(shop_url, str):
        result.stages.append(OnboardingStage(
            name="validation",
            status="fail",
            detail="shop_url required",
        ))
        result.final_verdict = "failed"
        return result
    if not (api_key or (client_id and client_secret)):
        result.stages.append(OnboardingStage(
            name="validation",
            status="fail",
            detail=(
                "credentials required: pass api_key OR "
                "client_id + client_secret"
            ),
        ))
        result.final_verdict = "failed"
        return result

    # When dry_run, build a plan-only result and return.
    if dry_run:
        for stage_name, hint in _DRY_RUN_HINTS:
            result.stages.append(OnboardingStage(
                name=stage_name,
                status="skipped",
                detail=hint,
            ))
        result.final_verdict = "dry_run"
        result.next_action = (
            "Re-run without --dry-run to execute the plan."
        )
        return result

    # ── Stage 1: register ──────────────────────────────────
    sm = store_manager
    if sm is None:
        try:
            from data_pipeline.store.store_manager import (
                StoreManager,
            )
            sm = StoreManager()
        except Exception as exc:  # noqa: BLE001
            result.stages.append(OnboardingStage(
                name="register",
                status="fail",
                detail=f"StoreManager import failed: {exc}",
            ))
            result.final_verdict = "failed"
            result.next_action = "fix import path"
            return result
    try:
        reg = sm.add_store(
            store_id, shop_url,
            api_key=api_key,
            client_id=client_id,
            client_secret=client_secret,
            name=name or store_id,
            niche=niche or "general",
            store_type=store_type,
        )
        if reg.get("error"):
            result.stages.append(OnboardingStage(
                name="register",
                status="fail",
                detail=str(reg["error"]),
            ))
            result.final_verdict = "failed"
            result.next_action = (
                f"Resolve the registration error and re-run "
                f"`shopai onboard {store_id} ...`"
            )
            return result
        result.stages.append(OnboardingStage(
            name="register",
            status="success",
            detail=(
                "OAuth" if client_id else "legacy_token"
            ),
            data={"reg": reg},
        ))
    except Exception as exc:  # noqa: BLE001
        result.stages.append(OnboardingStage(
            name="register",
            status="fail",
            detail=f"add_store raised: {exc}",
        ))
        result.final_verdict = "failed"
        return result

    # ── Stage 2: verify_creds (Wave 93) ─────────────────────
    # Probe the token before downstream stages depend on it.
    # When test_connection fails, mark the subsequent
    # network-dependent stages (sync / niche_detect / launch)
    # as skipped with a clear reason. go_live + schedule
    # still run so the operator gets a complete report.
    creds_ok = False
    try:
        conn = sm.test_connection(store_id) or {}
        if conn.get("connected"):
            creds_ok = True
            result.stages.append(OnboardingStage(
                name="verify_creds",
                status="success",
                detail=(
                    f"connected to {conn.get('shop') or shop_url}"
                ),
                data={"shop": conn.get("shop", "")},
            ))
        else:
            result.stages.append(OnboardingStage(
                name="verify_creds",
                status="fail",
                detail=(
                    f"connection refused: "
                    f"{conn.get('error', 'unknown')}"
                ),
            ))
    except Exception as exc:  # noqa: BLE001
        result.stages.append(OnboardingStage(
            name="verify_creds",
            status="fail",
            detail=f"test_connection raised: {exc}",
        ))

    # ── Stage 3: first sync ────────────────────────────────
    # Best-effort -- a failed sync doesn't block onboarding;
    # operator can re-sync later. Wave 92 surfaces it as warn
    # so the wizard keeps progressing through niche-detect +
    # launch.
    if not creds_ok:
        result.stages.append(OnboardingStage(
            name="sync",
            status="skipped",
            detail="skipped (credentials not verified)",
        ))
    else:
        sync_status = "warn"
        sync_detail = "sync not run (no SyncService available)"
        try:
            from data_pipeline.store.sync_service import SyncService
            sync = SyncService(sm)
            sync_result = sync.sync_store(store_id) or {}
            if sync_result.get("error"):
                sync_status = "warn"
                sync_detail = (
                    f"sync error: {sync_result['error']} "
                    "(can re-run via `shopai store sync`)"
                )
            else:
                sync_status = "success"
                sync_detail = (
                    f"pulled {sync_result.get('products', 0)} "
                    f"product(s), {sync_result.get('orders', 0)} "
                    "order(s)"
                )
        except Exception as exc:  # noqa: BLE001
            sync_status = "warn"
            sync_detail = (
                f"sync raised: {exc} "
                "(stub catalogue or no credentials; can retry)"
            )
        result.stages.append(OnboardingStage(
            name="sync",
            status=sync_status,
            detail=sync_detail,
        ))

    # ── Stage 4: niche detect ──────────────────────────────
    # If operator supplied niche, skip detection. Otherwise
    # run the Wave 83 classifier. Only auto-apply when
    # confidence is HIGH -- medium / low / no_data leave the
    # store on "general" and the operator gets a warn.
    if not creds_ok and not (niche and niche != "general"):
        # Catalog can't be pulled, detector would produce
        # no_data -- skip the stage instead of warning.
        result.stages.append(OnboardingStage(
            name="niche_detect",
            status="skipped",
            detail="skipped (credentials not verified)",
        ))
        final_niche = niche or "general"
    elif niche and niche != "general":
        result.stages.append(OnboardingStage(
            name="niche_detect",
            status="skipped",
            detail=f"operator-supplied niche='{niche}'",
            data={"niche": niche, "source": "operator"},
        ))
        final_niche = niche
    else:
        try:
            from engines._niche_detector import (
                suggest_niche_for_store,
            )
            det = suggest_niche_for_store(
                store_id, store_manager=sm,
            )
        except Exception as exc:  # noqa: BLE001
            det = None
            logger.debug(
                "onboard niche detect raised: %s", exc,
            )
        if det is None:
            result.stages.append(OnboardingStage(
                name="niche_detect",
                status="warn",
                detail="detector unavailable; niche stays 'general'",
            ))
            final_niche = "general"
        elif det.confidence == "high":
            # Auto-apply
            try:
                sm.update_store_niche(store_id, det.suggested)
                final_niche = det.suggested
                result.stages.append(OnboardingStage(
                    name="niche_detect",
                    status="success",
                    detail=(
                        f"auto-applied '{det.suggested}' "
                        f"(confidence=high, "
                        f"products={det.products_analyzed})"
                    ),
                    data={
                        "niche": det.suggested,
                        "source": "detector",
                        "confidence": "high",
                    },
                ))
            except Exception as exc:  # noqa: BLE001
                final_niche = "general"
                result.stages.append(OnboardingStage(
                    name="niche_detect",
                    status="warn",
                    detail=(
                        f"detector suggested "
                        f"'{det.suggested}' but "
                        f"update_store_niche raised: {exc}"
                    ),
                ))
        else:
            final_niche = "general"
            result.stages.append(OnboardingStage(
                name="niche_detect",
                status="warn",
                detail=(
                    f"detection confidence={det.confidence} "
                    f"(not auto-applied); operator: "
                    f"`shopai niche --suggest {store_id}` "
                    "to review"
                ),
                data={
                    "niche_suggested": det.suggested,
                    "confidence": det.confidence,
                },
            ))

    # ── Stage 5: launch ────────────────────────────────────
    if not creds_ok:
        result.stages.append(OnboardingStage(
            name="launch",
            status="skipped",
            detail="skipped (credentials not verified)",
        ))
    else:
        try:
            from engines.store_setup.launch_orchestrator import (
                launch_store,
            )
            launch = launch_store(
                store_name=name or store_id,
                niche=final_niche,
                store_id=store_id,
            )
            if launch.get("ready_to_launch"):
                result.stages.append(OnboardingStage(
                    name="launch",
                    status="success",
                    detail=(
                        f"{len(launch.get('checklist', []))} "
                        "stage(s) completed"
                    ),
                    data={
                        "checklist": launch.get("checklist"),
                    },
                ))
            else:
                failed_stages = [
                    s for s in launch.get("checklist", [])
                    if not s.get("ok")
                ]
                result.stages.append(OnboardingStage(
                    name="launch",
                    status="warn",
                    detail=(
                        f"{len(failed_stages)} stage(s) "
                        "incomplete; see launch checklist"
                    ),
                    data={
                        "checklist": launch.get("checklist"),
                    },
                ))
        except Exception as exc:  # noqa: BLE001
            result.stages.append(OnboardingStage(
                name="launch",
                status="fail",
                detail=f"launch_store raised: {exc}",
            ))

    # ── Stage 6: verify_launch (Wave 94) ───────────────────
    # Read-only audit of the 11 launch-readiness gates. The
    # launch stage above WROTE policies/pages/discounts/etc.;
    # this stage VERIFIES they all landed + surfaces any gaps
    # left for the operator. Skipped when creds_ok is False
    # (audit hits Shopify for every gate).
    if not creds_ok:
        result.stages.append(OnboardingStage(
            name="verify_launch",
            status="skipped",
            detail="skipped (credentials not verified)",
        ))
    else:
        try:
            from engines.store_setup.launch_audit import (
                audit_store,
            )
            audit = audit_store(store_id=store_id)
            if audit.get("ready_to_launch"):
                result.stages.append(OnboardingStage(
                    name="verify_launch",
                    status="success",
                    detail=(
                        f"all 11 gates green "
                        f"({audit.get('completion_pct', 0)}%)"
                    ),
                    data={
                        "completion_pct": audit.get(
                            "completion_pct"
                        ),
                        "ready_to_launch": True,
                    },
                ))
            else:
                manual_gaps = audit.get(
                    "manual_admin_gaps", [],
                ) or []
                closeable_gaps = audit.get(
                    "launch_closeable_gaps", [],
                ) or []
                detail = (
                    f"completion="
                    f"{audit.get('completion_pct', 0)}%; "
                    f"manual_admin={len(manual_gaps)} "
                    f"launch_closeable={len(closeable_gaps)}"
                )
                if closeable_gaps:
                    detail += (
                        " (re-run `shopai launch` to close "
                        "the closeable ones)"
                    )
                result.stages.append(OnboardingStage(
                    name="verify_launch",
                    status="warn",
                    detail=detail,
                    data={
                        "completion_pct": audit.get(
                            "completion_pct"
                        ),
                        "manual_admin_gaps": manual_gaps,
                        "launch_closeable_gaps": (
                            closeable_gaps
                        ),
                        "next_action": audit.get(
                            "next_action"
                        ),
                    },
                ))
        except Exception as exc:  # noqa: BLE001
            result.stages.append(OnboardingStage(
                name="verify_launch",
                status="warn",
                detail=f"audit raised: {exc}",
            ))

    # ── Stage 7: go-live ───────────────────────────────────
    try:
        from engines._go_live_check import (
            run_go_live_check, summarize,
        )
        checks = run_go_live_check()
        summary = summarize(checks)
        if summary["verdict"] == "ready_to_go_live":
            result.stages.append(OnboardingStage(
                name="go_live",
                status="success",
                detail=(
                    f"all gates pass "
                    f"(warns={summary['warn']})"
                ),
                data={"summary": summary},
            ))
        else:
            failing = [
                c.name for c in checks if c.status == "fail"
            ]
            result.stages.append(OnboardingStage(
                name="go_live",
                status="warn",
                detail=(
                    f"verdict={summary['verdict']} "
                    f"failures={','.join(failing)}"
                ),
                data={
                    "summary": summary,
                    "failures": failing,
                },
            ))
    except Exception as exc:  # noqa: BLE001
        result.stages.append(OnboardingStage(
            name="go_live",
            status="warn",
            detail=f"go-live probe raised: {exc}",
        ))

    # ── Stage 8: schedule ──────────────────────────────────
    # Emit a generic POSIX cron line. Operator runs
    # ``shopai cycle schedule`` for the platform-specific
    # template (systemd / Task Scheduler / etc.).
    cron_line = (
        "0 * * * * cd /path/to/shopai && "
        "SHOPAI_CYCLE_RUN_CONFIRM=1 shopai cycle run --yes "
        ">> /var/log/shopai/cycle.log 2>&1"
    )
    result.stages.append(OnboardingStage(
        name="schedule",
        status="success",
        detail="hourly cron template ready",
        data={"cron_line": cron_line},
    ))
    result.next_action = (
        "Install the emitted cron line "
        "(or run `shopai cycle schedule` for the full "
        "platform-specific template)"
    )

    # ── Final verdict ──────────────────────────────────────
    if result.has_failures:
        result.final_verdict = "failed"
        first_fail = next(
            s for s in result.stages if s.status == "fail"
        )
        result.next_action = (
            f"Resolve '{first_fail.name}' failure: "
            f"{first_fail.detail}"
        )
    elif result.has_warnings:
        result.final_verdict = "ready_with_warnings"
        if not result.next_action:
            first_warn = next(
                s for s in result.stages
                if s.status == "warn"
            )
            result.next_action = (
                f"Review '{first_warn.name}' warning: "
                f"{first_warn.detail}"
            )
    else:
        result.final_verdict = "ready"
        if not result.next_action:
            result.next_action = (
                "Store fully onboarded; install the cron "
                "line + monitor `shopai daily-brief`"
            )

    return result


# Used by --dry-run to show the plan without executing
_DRY_RUN_HINTS: list[tuple[str, str]] = [
    ("register",
     "StoreManager.add_store(store_id, shop_url, "
     "creds, name, niche, store_type)"),
    ("verify_creds",
     "sm.test_connection(store_id) -- probe the token; "
     "downstream stages skip on failure"),
    ("sync",
     "SyncService(sm).sync_store(store_id) -- pulls "
     "products + orders"),
    ("niche_detect",
     "engines._niche_detector.suggest_niche_for_store "
     "-> auto-apply if confidence=high"),
    ("launch",
     "engines.store_setup.launch_orchestrator.launch_store "
     "-- policies + pages + discount + collections"),
    ("verify_launch",
     "engines.store_setup.launch_audit.audit_store -- "
     "read-only 11-gate audit; surfaces remaining gaps"),
    ("go_live",
     "engines._go_live_check.run_go_live_check -- 9 gates"),
    ("schedule",
     "emit POSIX cron template; operator can also run "
     "`shopai cycle schedule` for platform-specific output"),
]
