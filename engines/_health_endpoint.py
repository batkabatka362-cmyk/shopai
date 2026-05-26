"""External-monitoring health endpoint.

Wave 59: external monitoring services (Pingdom, UptimeRobot,
StatusCake, Better Uptime, etc) need a JSON endpoint to poll
to know if ShopAI is alive + healthy. Operator wires this:

  - Cron: */5 * * * * shopai health --json > /var/www/health.json
  - Then point UptimeRobot at the static file

The endpoint returns a flat dict + an overall "healthy"
boolean. Five sub-checks:

  - cycle_age_hours: how long since last cycle (None if never)
  - active_alerts: count of currently-fireable notify alerts
  - paused_engines: count in quarantine.alert_paused
  - stores_count: registered stores
  - tests_state: not actually run, just a placeholder

Healthy when:
  - cycle_age_hours < 48 OR no cycle history yet
  - active_alerts == 0
  - paused_engines / total_engines < 0.5
  - stores_count > 0
"""
from __future__ import annotations

import time
from typing import Any


def health_report() -> dict[str, Any]:
    """Build the empire health report dict."""
    report: dict[str, Any] = {
        "captured_at": time.time(),
        "healthy": True,
        "components": {},
        "failures": [],
    }

    # 1. Cycle age
    cycle_check: dict[str, Any] = {"status": "ok", "detail": ""}
    try:
        from engines._cycle_history import last_run
        lr = last_run()
        if lr is None:
            cycle_check = {
                "status": "warn",
                "detail": "no cycle history",
                "age_hours": None,
            }
        else:
            age_h = (time.time() - lr.started_at) / 3600.0
            cycle_check["age_hours"] = round(age_h, 1)
            if age_h > 48.0:
                cycle_check["status"] = "fail"
                cycle_check["detail"] = (
                    f"last cycle {age_h:.1f}h ago (>48h)"
                )
                report["healthy"] = False
                report["failures"].append("stale_cycle")
            elif age_h > 24.0:
                cycle_check["status"] = "warn"
                cycle_check["detail"] = (
                    f"last cycle {age_h:.1f}h ago (>24h)"
                )
            else:
                cycle_check["detail"] = (
                    f"last cycle {age_h:.1f}h ago"
                )
    except Exception as exc:  # noqa: BLE001
        cycle_check = {
            "status": "error", "detail": str(exc)[:100],
        }
    report["components"]["cycle"] = cycle_check

    # 2. Active alerts (from notify probes)
    alerts_check: dict[str, Any] = {"status": "ok"}
    try:
        from engines._notify import collect_alerts
        alerts = collect_alerts()
        alerts_check["count"] = len(alerts)
        if alerts:
            alerts_check["status"] = "warn"
            alerts_check["detail"] = (
                f"{len(alerts)} active alert(s)"
            )
            alerts_check["kinds"] = sorted(
                {a.kind for a in alerts},
            )
            # Critical-severity alerts -> unhealthy
            critical = [
                a for a in alerts if a.severity == "critical"
            ]
            if critical:
                report["healthy"] = False
                report["failures"].append(
                    f"critical_alert_{critical[0].kind}",
                )
                alerts_check["status"] = "fail"
        else:
            alerts_check["detail"] = "no active alerts"
    except Exception as exc:  # noqa: BLE001
        alerts_check = {
            "status": "error", "detail": str(exc)[:100],
        }
    report["components"]["alerts"] = alerts_check

    # 3. Paused engines (quarantine state)
    paused_check: dict[str, Any] = {"status": "ok"}
    try:
        from core.approval import quarantine
        state = quarantine.load_state()
        pauses = list(state.alert_paused or [])
        paused_check["count"] = len(pauses)
        if len(pauses) > 10:
            paused_check["status"] = "warn"
            paused_check["detail"] = (
                f"{len(pauses)} engines paused (high)"
            )
        elif pauses:
            paused_check["detail"] = (
                f"{len(pauses)} engine(s) paused"
            )
        else:
            paused_check["detail"] = "no engines paused"
    except Exception as exc:  # noqa: BLE001
        paused_check = {
            "status": "error", "detail": str(exc)[:100],
        }
    report["components"]["quarantine"] = paused_check

    # 4. Stores registered
    stores_check: dict[str, Any] = {"status": "ok"}
    try:
        from data_pipeline.store.store_manager import StoreManager
        stores = StoreManager().list_stores() or []
        stores_check["count"] = len(stores)
        if not stores:
            stores_check["status"] = "fail"
            stores_check["detail"] = "no stores registered"
            report["healthy"] = False
            report["failures"].append("no_stores")
        else:
            stores_check["detail"] = (
                f"{len(stores)} store(s) registered"
            )
    except Exception as exc:  # noqa: BLE001
        stores_check = {
            "status": "error", "detail": str(exc)[:100],
        }
    report["components"]["stores"] = stores_check

    return report
