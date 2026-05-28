"""External notification fan-out for empire alerts.

Wave 53: when the autonomous loop detects something the
operator should know about (stale cycle, revenue regression,
spend cap breach, engine quarantine), surface it via an
external webhook so operator gets a push notification
without manually running daily-brief.

The webhook URL is configurable; ShopAI doesn't bundle Slack /
Discord / Pushbullet adapters. Operator points the env var
``SHOPAI_NOTIFY_WEBHOOK_URL`` at any HTTP endpoint that
accepts a JSON POST -- Slack incoming webhook URL, n8n
workflow, Zapier hook, custom relay.

## Payload shape

POST JSON body:
    {
      "source": "shopai",
      "captured_at": float,
      "alerts": [
        {
          "kind": str,  // "stale_cycle", "revenue_regression",
                        // "spend_breach", "engine_paused"
          "severity": str,  // "info", "warn", "critical"
          "message": str,
          "context": dict,
        },
        ...
      ],
      "summary": str,
    }

## Throttling

Alerts shouldn't spam. Per-kind dedup file at
``data/notify_state.json`` records the last firing time for
each alert kind. Default cooldown: 1 hour (configurable via
``SHOPAI_NOTIFY_COOLDOWN_SECONDS``).

## Env-var contract

  SHOPAI_NOTIFY_WEBHOOK_URL=https://... -- target webhook
  SHOPAI_NOTIFY_COOLDOWN_SECONDS=N      -- min seconds between
                                          repeat alerts of
                                          the same kind
                                          (default 3600)
  SHOPAI_NOTIFY_DRY_RUN=1                -- assemble alerts +
                                          print payload but
                                          don't POST

## Pattern J

Under pytest, ``_post_webhook`` short-circuits. Tests verify
alert collection + payload shape without making real HTTP
calls.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_ENV_URL = "SHOPAI_NOTIFY_WEBHOOK_URL"
_ENV_COOLDOWN = "SHOPAI_NOTIFY_COOLDOWN_SECONDS"
_ENV_DRY_RUN = "SHOPAI_NOTIFY_DRY_RUN"

_DEFAULT_COOLDOWN = 3600  # 1 hour


@dataclass
class NotifyAlert:
    kind: str
    severity: str  # info / warn / critical
    message: str
    context: dict[str, Any] = field(default_factory=dict)


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def webhook_url() -> str | None:
    return os.environ.get(_ENV_URL) or None


def cooldown_seconds() -> int:
    raw = os.environ.get(_ENV_COOLDOWN)
    if not raw:
        return _DEFAULT_COOLDOWN
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_COOLDOWN


def is_dry_run() -> bool:
    return os.environ.get(_ENV_DRY_RUN) == "1"


def _data_dir() -> Path:
    base = os.environ.get("SHOPAI_DATA_DIR")
    p = Path(base) if base else Path("data")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _state_path() -> Path:
    return _data_dir() / "notify_state.json"


def _load_state() -> dict[str, float]:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def _save_state(state: dict[str, float]) -> None:
    p = _state_path()
    try:
        p.write_text(
            json.dumps(state, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def collect_alerts() -> list[NotifyAlert]:
    """Scan the substrate for alert-worthy conditions."""
    alerts: list[NotifyAlert] = []

    # 1. Stale cycle (cron may be broken)
    try:
        from engines._cycle_history import last_run
        lr = last_run()
        if lr is not None:
            age_h = (time.time() - lr.started_at) / 3600.0
            if age_h > 24.0:
                alerts.append(NotifyAlert(
                    kind="stale_cycle",
                    severity="warn",
                    message=(
                        f"Last cycle ran {age_h:.1f}h ago "
                        f"(>24h). Cron may be broken."
                    ),
                    context={"age_hours": round(age_h, 1)},
                ))
    except Exception as exc:  # noqa: BLE001
        logger.debug("notify: stale_cycle probe raised: %s", exc)

    # 2. Revenue regression (delta alerts)
    try:
        from engines._attribution_delta import latest_delta
        delta = latest_delta()
        if delta is not None and delta.has_alerts:
            top = delta.alerts[0]
            alerts.append(NotifyAlert(
                kind="revenue_regression",
                severity="critical",
                message=(
                    f"Revenue regression: {top.scope}:"
                    f"{top.name} -- {top.reason}"
                ),
                context={
                    "alert_count": len(delta.alerts),
                    "overall_delta": delta.overall_revenue_delta,
                },
            ))
    except Exception as exc:  # noqa: BLE001
        logger.debug("notify: revenue probe raised: %s", exc)

    # 3. Spend cap breach
    try:
        from engines._spend_cap import check_caps
        breaches = check_caps()
        if breaches:
            top = breaches[0]
            alerts.append(NotifyAlert(
                kind="spend_breach",
                severity="critical",
                message=(
                    f"Spend cap breached: {top.window_label} "
                    f"${top.actual_spend:.0f} > "
                    f"${top.cap_usd:.0f}"
                ),
                context={
                    "window": top.window_label,
                    "over_by": top.over_by,
                },
            ))
    except Exception as exc:  # noqa: BLE001
        logger.debug("notify: spend probe raised: %s", exc)

    # 4. Engine quarantine recently triggered
    try:
        from core.approval import quarantine
        state = quarantine.load_state()
        pauses = list(state.alert_paused or [])
        if pauses:
            sample_names = [
                p[0] if isinstance(p, tuple) else str(p)
                for p in pauses[:3]
            ]
            alerts.append(NotifyAlert(
                kind="engine_paused",
                severity="warn",
                message=(
                    f"{len(pauses)} engine(s) alert-paused: "
                    f"{', '.join(sample_names)}"
                    + (" ..." if len(pauses) > 3 else "")
                ),
                context={"pause_count": len(pauses)},
            ))
    except Exception as exc:  # noqa: BLE001
        logger.debug("notify: quarantine probe raised: %s", exc)

    # 5. Wave 108: refund auto-pause OR critical refund health.
    # Operator wants to know when the autonomous refund loop
    # has stopped (real money flow paused) or when failure rate
    # is breaching the threshold.
    try:
        from engines.returns_management.refund_state import (
            get_state as _refund_state,
        )
        from engines.returns_management.refund_health import (
            analyze_refund_health as _refund_health,
        )
        rstate = _refund_state()
        if rstate.paused:
            alerts.append(NotifyAlert(
                kind="refund_paused",
                severity="critical",
                message=(
                    f"Refund auto-pause active: "
                    f"{rstate.reason or '(no reason)'}"
                ),
                context={
                    "reason": rstate.reason,
                    "paused_at": rstate.paused_at,
                    "auto_resume_after": (
                        rstate.auto_resume_after
                    ),
                },
            ))
        else:
            health = _refund_health(window_hours=24.0)
            if health.verdict == "critical":
                alerts.append(NotifyAlert(
                    kind="refund_health_critical",
                    severity="critical",
                    message=(
                        f"Refund failure ratio "
                        f"{health.failure_ratio:.0%} >= "
                        "critical threshold "
                        f"(n={health.sample_size})"
                    ),
                    context={
                        "failure_ratio": health.failure_ratio,
                        "sample_size": health.sample_size,
                    },
                ))
    except Exception as exc:  # noqa: BLE001
        logger.debug("notify: refund probe raised: %s", exc)

    # 6. Wave 115: budget auto-pause OR critical budget health.
    # Same shape as refund alerts above.
    try:
        from engines.roas_guardrails.budget_state import (
            get_state as _budget_state,
        )
        from engines.roas_guardrails.budget_health import (
            analyze_budget_health as _budget_health,
        )
        bstate = _budget_state()
        if bstate.paused:
            alerts.append(NotifyAlert(
                kind="budget_paused",
                severity="critical",
                message=(
                    f"Budget auto-pause active: "
                    f"{bstate.reason or '(no reason)'}"
                ),
                context={
                    "reason": bstate.reason,
                    "paused_at": bstate.paused_at,
                    "auto_resume_after": (
                        bstate.auto_resume_after
                    ),
                },
            ))
        else:
            bhealth = _budget_health(window_hours=24.0)
            if bhealth.verdict == "critical":
                alerts.append(NotifyAlert(
                    kind="budget_health_critical",
                    severity="critical",
                    message=(
                        f"Budget failure ratio "
                        f"{bhealth.failure_ratio:.0%} >= "
                        "critical threshold "
                        f"(n={bhealth.sample_size})"
                    ),
                    context={
                        "failure_ratio": bhealth.failure_ratio,
                        "sample_size": bhealth.sample_size,
                    },
                ))
    except Exception as exc:  # noqa: BLE001
        logger.debug("notify: budget probe raised: %s", exc)

    # 7. Wave 130: fulfillment auto-pause OR critical health.
    try:
        from engines.fulfillment_autonomy.fulfillment_state import (
            get_state as _ff_state,
        )
        from engines.fulfillment_autonomy.fulfillment_health import (
            analyze_fulfillment_health as _ff_health,
        )
        fstate = _ff_state()
        if fstate.paused:
            alerts.append(NotifyAlert(
                kind="fulfillment_paused",
                severity="critical",
                message=(
                    f"Fulfillment auto-pause active: "
                    f"{fstate.reason or '(no reason)'}"
                ),
                context={
                    "reason": fstate.reason,
                    "paused_at": fstate.paused_at,
                    "auto_resume_after": (
                        fstate.auto_resume_after
                    ),
                },
            ))
        else:
            fh = _ff_health(window_hours=24.0)
            if fh.verdict == "critical":
                alerts.append(NotifyAlert(
                    kind="fulfillment_health_critical",
                    severity="critical",
                    message=(
                        f"Fulfillment failure ratio "
                        f"{fh.failure_ratio:.0%} >= "
                        "critical threshold "
                        f"(n={fh.sample_size})"
                    ),
                    context={
                        "failure_ratio": fh.failure_ratio,
                        "sample_size": fh.sample_size,
                    },
                ))
    except Exception as exc:  # noqa: BLE001
        logger.debug("notify: fulfillment probe raised: %s", exc)

    # 8. Wave 136: inventory auto-pause / critical health.
    try:
        from engines.inventory_autonomy.inventory_state import (
            get_state as _inv_state,
        )
        from engines.inventory_autonomy.inventory_health import (
            analyze_inventory_health as _inv_health,
        )
        istate = _inv_state()
        if istate.paused:
            alerts.append(NotifyAlert(
                kind="inventory_paused",
                severity="critical",
                message=(
                    f"Inventory auto-pause active: "
                    f"{istate.reason or '(no reason)'}"
                ),
                context={
                    "reason": istate.reason,
                    "paused_at": istate.paused_at,
                    "auto_resume_after": (
                        istate.auto_resume_after
                    ),
                },
            ))
        else:
            ih = _inv_health(window_hours=24.0)
            if ih.verdict == "critical":
                alerts.append(NotifyAlert(
                    kind="inventory_health_critical",
                    severity="critical",
                    message=(
                        f"Inventory failure ratio "
                        f"{ih.failure_ratio:.0%} >= "
                        "critical threshold "
                        f"(n={ih.sample_size})"
                    ),
                    context={
                        "failure_ratio": ih.failure_ratio,
                        "sample_size": ih.sample_size,
                    },
                ))
    except Exception as exc:  # noqa: BLE001
        logger.debug("notify: inventory probe raised: %s", exc)

    # 9. Wave 159: discount cleanup auto-pause / critical.
    try:
        from engines.discount_cleanup_autonomy.cleanup_state import (
            get_state as _cu_state,
        )
        from engines.discount_cleanup_autonomy.cleanup_health import (
            analyze_cleanup_health as _cu_health,
        )
        cstate = _cu_state()
        if cstate.paused:
            alerts.append(NotifyAlert(
                kind="discount_cleanup_paused",
                severity="critical",
                message=(
                    f"Discount cleanup auto-pause active: "
                    f"{cstate.reason or '(no reason)'}"
                ),
                context={
                    "reason": cstate.reason,
                    "paused_at": cstate.paused_at,
                    "auto_resume_after": (
                        cstate.auto_resume_after
                    ),
                },
            ))
        else:
            ch = _cu_health(window_hours=24.0)
            if ch.verdict == "critical":
                alerts.append(NotifyAlert(
                    kind="discount_cleanup_health_critical",
                    severity="critical",
                    message=(
                        f"Discount cleanup failure ratio "
                        f"{ch.failure_ratio:.0%} >= critical "
                        f"(n={ch.sample_size})"
                    ),
                    context={
                        "failure_ratio": ch.failure_ratio,
                        "sample_size": ch.sample_size,
                    },
                ))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "notify: discount_cleanup probe raised: %s", exc,
        )

    # 10. Wave 179: order followup auto-pause / critical.
    try:
        from engines.order_followup_autonomy.followup_state import (
            get_state as _fu_state,
        )
        from engines.order_followup_autonomy.followup_health import (
            analyze_followup_health as _fu_health,
        )
        fustate = _fu_state()
        if fustate.paused:
            alerts.append(NotifyAlert(
                kind="order_followup_paused",
                severity="critical",
                message=(
                    f"Order followup auto-pause active: "
                    f"{fustate.reason or '(no reason)'}"
                ),
                context={
                    "reason": fustate.reason,
                    "paused_at": fustate.paused_at,
                    "auto_resume_after": (
                        fustate.auto_resume_after
                    ),
                },
            ))
        else:
            fuh = _fu_health(window_hours=24.0)
            if fuh.verdict == "critical":
                alerts.append(NotifyAlert(
                    kind="order_followup_health_critical",
                    severity="critical",
                    message=(
                        f"Order followup failure ratio "
                        f"{fuh.failure_ratio:.0%} >= critical "
                        f"(n={fuh.sample_size})"
                    ),
                    context={
                        "failure_ratio": fuh.failure_ratio,
                        "sample_size": fuh.sample_size,
                    },
                ))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "notify: order_followup probe raised: %s", exc,
        )

    # 11. Wave 200: product SEO auto-pause / critical.
    try:
        from engines.product_seo_autonomy.seo_state import (
            get_state as _seo_state,
        )
        from engines.product_seo_autonomy.seo_health import (
            analyze_seo_health as _seo_health,
        )
        seostate = _seo_state()
        if seostate.paused:
            alerts.append(NotifyAlert(
                kind="product_seo_paused",
                severity="critical",
                message=(
                    f"Product SEO auto-pause active: "
                    f"{seostate.reason or '(no reason)'}"
                ),
                context={
                    "reason": seostate.reason,
                    "paused_at": seostate.paused_at,
                    "auto_resume_after": (
                        seostate.auto_resume_after
                    ),
                },
            ))
        else:
            seoh = _seo_health(window_hours=24.0)
            if seoh.verdict == "critical":
                alerts.append(NotifyAlert(
                    kind="product_seo_health_critical",
                    severity="critical",
                    message=(
                        f"Product SEO failure ratio "
                        f"{seoh.failure_ratio:.0%} >= critical"
                        f" (n={seoh.sample_size})"
                    ),
                    context={
                        "failure_ratio": seoh.failure_ratio,
                        "sample_size": seoh.sample_size,
                    },
                ))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "notify: product_seo probe raised: %s", exc,
        )

    # 12. Wave 397: customer outreach auto-pause / critical.
    try:
        from engines.customer_outreach_autonomy.outreach_state import (  # noqa: E501
            get_state as _co_state,
        )
        from engines.customer_outreach_autonomy.outreach_health import (  # noqa: E501
            analyze_customer_outreach_health as _co_health,
        )
        costate = _co_state()
        if costate.paused:
            alerts.append(NotifyAlert(
                kind="customer_outreach_paused",
                severity="critical",
                message=(
                    f"Customer outreach auto-pause active: "
                    f"{costate.reason or '(no reason)'}"
                ),
                context={
                    "reason": costate.reason,
                    "paused_at": costate.paused_at,
                    "auto_resume_after": (
                        costate.auto_resume_after
                    ),
                },
            ))
        else:
            coh = _co_health(window_hours=24.0)
            if coh.verdict == "critical":
                alerts.append(NotifyAlert(
                    kind=(
                        "customer_outreach_health_critical"
                    ),
                    severity="critical",
                    message=(
                        f"Customer outreach failure ratio "
                        f"{coh.failure_ratio:.0%} >= critical"
                        f" (n={coh.sample_size})"
                    ),
                    context={
                        "failure_ratio": coh.failure_ratio,
                        "sample_size": coh.sample_size,
                    },
                ))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "notify: customer_outreach probe raised: %s",
            exc,
        )

    # 13. Wave 453: catalog quality auto-pause / critical.
    try:
        from engines.catalog_quality_autonomy.quality_state import (  # noqa: E501
            get_state as _cq_state,
        )
        from engines.catalog_quality_autonomy.quality_health import (  # noqa: E501
            analyze_catalog_quality_health as _cq_health,
        )
        cqstate = _cq_state()
        if cqstate.paused:
            alerts.append(NotifyAlert(
                kind="catalog_quality_paused",
                severity="critical",
                message=(
                    f"Catalog quality auto-pause active: "
                    f"{cqstate.reason or '(no reason)'}"
                ),
                context={
                    "reason": cqstate.reason,
                    "paused_at": cqstate.paused_at,
                    "auto_resume_after": (
                        cqstate.auto_resume_after
                    ),
                },
            ))
        else:
            cqh = _cq_health(window_hours=24.0)
            if cqh.verdict == "critical":
                alerts.append(NotifyAlert(
                    kind="catalog_quality_health_critical",
                    severity="critical",
                    message=(
                        f"Catalog quality failure ratio "
                        f"{cqh.failure_ratio:.0%} >= critical"
                        f" (n={cqh.sample_size})"
                    ),
                    context={
                        "failure_ratio": cqh.failure_ratio,
                        "sample_size": cqh.sample_size,
                    },
                ))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "notify: catalog_quality probe raised: %s", exc,
        )

    # 14. Wave 153: autonomy coalesce. Opt-in via
    # SHOPAI_NOTIFY_AUTONOMY_COALESCE=1. When set, replace
    # per-domain {refund,budget,fulfillment,inventory,
    # discount_cleanup,order_followup,product_seo}_paused /
    # _health_critical alerts with a single rolled-up
    # autonomy_degraded alert.
    if os.environ.get("SHOPAI_NOTIFY_AUTONOMY_COALESCE", "") in (
        "1", "true", "yes",
    ):
        autonomy_kinds = {
            "refund_paused", "refund_health_critical",
            "budget_paused", "budget_health_critical",
            "fulfillment_paused",
            "fulfillment_health_critical",
            "inventory_paused", "inventory_health_critical",
            "discount_cleanup_paused",
            "discount_cleanup_health_critical",
            "order_followup_paused",
            "order_followup_health_critical",
            "product_seo_paused",
            "product_seo_health_critical",
            "customer_outreach_paused",
            "customer_outreach_health_critical",
            "catalog_quality_paused",
            "catalog_quality_health_critical",
        }
        autonomy_alerts = [
            a for a in alerts if a.kind in autonomy_kinds
        ]
        if len(autonomy_alerts) >= 2:
            # Coalesce: drop the per-domain alerts + emit a
            # single rollup.
            non_autonomy = [
                a for a in alerts
                if a.kind not in autonomy_kinds
            ]
            domains_affected = sorted({
                a.kind.split("_")[0] for a in autonomy_alerts
            })
            non_autonomy.append(NotifyAlert(
                kind="autonomy_degraded",
                severity="critical",
                message=(
                    f"{len(autonomy_alerts)} autonomy "
                    f"alert(s) across "
                    f"{len(domains_affected)} domain(s): "
                    f"{', '.join(domains_affected)}"
                ),
                context={
                    "alert_count": len(autonomy_alerts),
                    "domains": domains_affected,
                    "alert_kinds": sorted(
                        a.kind for a in autonomy_alerts
                    ),
                },
            ))
            return non_autonomy

    return alerts


def _filter_by_cooldown(
    alerts: list[NotifyAlert],
    state: dict[str, float],
    now: float,
    cooldown: int,
) -> list[NotifyAlert]:
    """Drop alerts whose kind fired within the cooldown."""
    out: list[NotifyAlert] = []
    for a in alerts:
        last_fired = state.get(a.kind, 0.0)
        if (now - last_fired) < cooldown:
            continue
        out.append(a)
    return out


def _post_webhook(
    url: str, payload: dict[str, Any],
) -> bool:
    """POST payload to webhook URL. Returns True on success."""
    if _is_test_environment():
        return True  # Pattern J: no real HTTP under tests
    try:
        import requests as _requests
    except ImportError:
        logger.warning("notify: 'requests' not installed; skipping")
        return False
    try:
        resp = _requests.post(
            url, json=payload, timeout=10.0,
        )
        return resp.status_code < 400
    except Exception as exc:  # noqa: BLE001
        logger.warning("notify: webhook POST failed: %s", exc)
        return False


def notify_check() -> dict[str, Any]:
    """Run the full notify check: collect, cooldown-filter,
    post, persist state.

    Returns a result dict for CLI rendering.
    """
    url = webhook_url()
    cooldown = cooldown_seconds()
    dry_run = is_dry_run()

    alerts = collect_alerts()
    now = time.time()
    state = _load_state()
    fireable = _filter_by_cooldown(
        alerts, state, now, cooldown,
    )

    result: dict[str, Any] = {
        "url_configured": bool(url),
        "dry_run": dry_run,
        "total_alerts": len(alerts),
        "fireable_alerts": len(fireable),
        "cooldown_seconds": cooldown,
        "alerts": [
            {
                "kind": a.kind, "severity": a.severity,
                "message": a.message, "context": a.context,
            }
            for a in fireable
        ],
        "posted": False,
    }

    if not fireable:
        return result

    summary_parts = [
        f"[{a.severity.upper()}] {a.message[:80]}"
        for a in fireable
    ]
    payload: dict[str, Any] = {
        "source": "shopai",
        "captured_at": now,
        "alerts": result["alerts"],
        "summary": " | ".join(summary_parts),
    }

    # Wave 68: optionally include the empire summary paragraph
    # alongside the alerts. Operator's Slack message becomes
    # one-shot: alerts + 1-paragraph context.
    if os.environ.get("SHOPAI_NOTIFY_INCLUDE_SUMMARY") == "1":
        try:
            from engines._empire_summarizer import (
                summarize_empire,
            )
            empire = summarize_empire()
            payload["empire_summary"] = {
                "text": empire.text,
                "used_llm": empire.used_llm,
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "notify: empire summary inclusion failed: %s",
                exc,
            )

    if dry_run:
        result["payload"] = payload
        return result

    if not url:
        return result

    ok = _post_webhook(url, payload)
    result["posted"] = ok

    if ok:
        # Update cooldown state for fired alert kinds
        for a in fireable:
            state[a.kind] = now
        _save_state(state)

    return result
