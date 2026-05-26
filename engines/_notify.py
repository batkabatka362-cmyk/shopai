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
    payload = {
        "source": "shopai",
        "captured_at": now,
        "alerts": result["alerts"],
        "summary": " | ".join(summary_parts),
    }

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
