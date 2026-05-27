"""Autonomous ad-budget mutation (Wave 112).

The roas_guardrails engine identifies under-performing campaigns
(ROAS < threshold) and suggests budget cuts. Pre-Wave-112 those
suggestions were advisory only -- operator had to log into Meta
Ads Manager and adjust each campaign manually.

Wave 112 closes the loop. ``apply_budget_changes()``:

  1. Filters the engine's ``recommendations`` to status=cut /
     status=pause rows.
  2. Drops rows whose proposed_budget exceeds the safety
     ceiling (``SHOPAI_BUDGET_MAX_DELTA_USD`` -- default $200
     max delta per single mutation).
  3. Reads ``budget_state.is_paused()`` -- when set, every row
     skips with status="paused" (Wave 111 bridge).
  4. For cuts: calls ``ADS_UPDATE_BUDGET`` with the new daily
     amount.
     For pauses: calls ``ADS_PAUSE_CAMPAIGN``.
  5. Records every outcome via record_writeback (Pattern Z)
     AND record_ad_spend_event (Wave 110 log).

## Opt-in

Default OFF. Caller flips ``data.apply_budget_changes=True``.
Mirrors Wave 6/7 pattern.

## Skip taxonomy

  - paused                  -- budget auto-pause flag set
  - router_unavailable      -- adapters layer not loadable
  - no_campaign_id          -- engine row missing addressable id
  - exceeds_max_delta       -- safety ceiling
  - not_actionable          -- action other than cut/pause
  - adapter_failed          -- adapter raise / userErrors
  - recorded                -- success
"""
from __future__ import annotations

import os
from typing import Any

from engines._writeback_recorder import record_writeback
from engines.roas_guardrails.ad_spend_log import (
    AdSpendEvent, record_ad_spend_event,
)
from engines.roas_guardrails.budget_state import is_paused
from utils.logger import get_logger

logger = get_logger("engines.roas_guardrails.budget_applier")

_ENGINE = "roas_guardrails"
_ACTION_TYPE = "apply_budget_change"


def _max_delta() -> float:
    raw = os.environ.get("SHOPAI_BUDGET_MAX_DELTA_USD", "200")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 200.0


def _get_router() -> Any | None:
    try:
        from core.adapters.router import get_router
        return get_router()
    except Exception:  # noqa: BLE001
        return None


def _capability(name: str) -> Any | None:
    try:
        from core.adapters.base import Capability
        return getattr(Capability, name, None)
    except Exception:  # noqa: BLE001
        return None


def _record(
    *,
    campaign_id: str,
    store_id: str,
    action: str,
    prior: float,
    new: float,
    reason: str,
    applied: bool,
    status: str,
    error: str | None,
) -> None:
    """Fan-out: Pattern Z recorder + ad_spend_log entry."""
    try:
        record_writeback(
            engine=_ENGINE,
            action_type=_ACTION_TYPE,
            capability=(
                "ADS_UPDATE_BUDGET" if action == "cut"
                else "ADS_PAUSE_CAMPAIGN"
            ),
            params={
                "campaign_id": campaign_id,
                "store_id": store_id,
                "action": action,
                "prior_budget": prior,
                "new_budget": new,
            },
            success=applied,
            error=error,
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        record_ad_spend_event(AdSpendEvent(
            campaign_id=campaign_id,
            store_id=store_id,
            action=action,
            prior_budget=prior,
            new_budget=new,
            reason=reason,
            applied=applied,
            status=status,
            error=error or "",
        ))
    except Exception:  # noqa: BLE001
        pass


def apply_budget_changes(
    recommendations: list[dict[str, Any]],
    *,
    max_delta: float | None = None,
) -> list[dict[str, Any]]:
    """Apply budget cuts / campaign pauses for ROAS-flagged
    campaigns.

    Args:
        recommendations: roas_guardrails engine output's
            ``recommendations`` list. Each row carries
            ``{campaign_id, store_id, action, prior_budget,
            proposed_budget, reason}``.
        max_delta: Override the env safety ceiling.

    Returns:
        Per-recommendation list with ``{campaign_id, store_id,
        action, applied, status, error}``.
    """
    if not isinstance(recommendations, list) or (
        not recommendations
    ):
        return []

    cap_delta = (
        max_delta if max_delta is not None else _max_delta()
    )

    # Wave 111: respect the auto-pause flag
    paused = is_paused()

    router = _get_router() if not paused else None
    update_cap = (
        _capability("ADS_UPDATE_BUDGET") if not paused
        else None
    )
    pause_cap = (
        _capability("ADS_PAUSE_CAMPAIGN") if not paused
        else None
    )

    out: list[dict[str, Any]] = []
    for row in recommendations:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("campaign_id", "") or "")
        sid = str(row.get("store_id", "") or "")
        action = str(row.get("action", "") or "").lower()
        try:
            prior = float(row.get("prior_budget", 0) or 0)
        except (TypeError, ValueError):
            prior = 0.0
        try:
            new_budget = float(
                row.get("proposed_budget", 0) or 0,
            )
        except (TypeError, ValueError):
            new_budget = 0.0
        reason = str(row.get("reason", "") or "")
        applied = False
        status_label = ""
        error: str | None = None

        if paused:
            status_label = "paused"
            error = "budget auto-pause flag set"
        elif action not in ("cut", "pause"):
            status_label = "not_actionable"
        elif not cid:
            status_label = "no_campaign_id"
        elif (
            router is None
            or (action == "cut" and update_cap is None)
            or (action == "pause" and pause_cap is None)
        ):
            status_label = "router_unavailable"
        elif (
            action == "cut"
            and abs(prior - new_budget) > cap_delta
        ):
            status_label = "exceeds_max_delta"
            error = (
                f"delta=${abs(prior-new_budget):.0f} > "
                f"cap=${cap_delta:.0f}"
            )
        else:
            try:
                if action == "cut":
                    res = router.execute(
                        update_cap,
                        {
                            "campaign_id": cid,
                            "daily_budget_usd": new_budget,
                        },
                    )
                else:  # pause
                    res = router.execute(
                        pause_cap,
                        {"campaign_id": cid},
                    )
                if getattr(res, "ok", False):
                    applied = True
                    status_label = "recorded"
                else:
                    status_label = "adapter_failed"
                    err_obj = getattr(
                        res, "error", "adapter_failed",
                    )
                    error = (
                        str(err_obj) if err_obj is not None
                        else "adapter_failed"
                    )
            except Exception as exc:  # noqa: BLE001
                status_label = "adapter_failed"
                error = str(exc)

        _record(
            campaign_id=cid,
            store_id=sid,
            action=action or "cut",
            prior=prior,
            new=new_budget,
            reason=reason,
            applied=applied,
            status=status_label,
            error=error,
        )
        out.append({
            "campaign_id": cid,
            "store_id": sid,
            "action": action,
            "applied": applied,
            "status": status_label,
            "error": error,
        })
    return out
