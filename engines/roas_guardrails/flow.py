"""ROAS Guardrails Engine — campaign metrics → kill/scale/hold decisions.

Consumes a list of campaign performance records (spend, revenue,
purchases, impressions, clicks) and emits per-campaign decisions:

  * ``kill``      — pause the campaign (ROAS catastrophically low)
  * ``reduce``    — cut budget by N% (ROAS below target but salvageable)
  * ``hold``      — keep current budget (ROAS in acceptable band)
  * ``scale``     — increase budget by N% (ROAS strong)
  * ``scale_aggressive`` — increase budget by larger N% (ROAS exceptional)
  * ``learning``  — too early to decide (spend < floor)

Thresholds (configurable via ``thresholds`` input dict):

  ROAS < 1.0              → ``kill`` (losing money on every dollar)
  ROAS 1.0 – 1.5          → ``reduce`` 30%
  ROAS 1.5 – 2.0          → ``hold``
  ROAS 2.0 – 3.0          → ``scale`` +20%
  ROAS ≥ 3.0              → ``scale_aggressive`` +50%

Learning-phase gate: campaigns with total spend < $50 (configurable
via ``spend_floor_usd``) emit ``learning`` instead of kill/reduce,
because ROAS is not statistically meaningful with small samples.
Scale decisions still fire during learning if ROAS > 2.0 (upside
risk is acceptable).

CPA guard: even if ROAS looks healthy, a CPA exceeding the product
margin triggers a ``reduce`` override. This prevents campaigns
where a single high-value order masks poor unit economics.

This engine is PURELY DETERMINISTIC — no adapter I/O. It emits
an action plan that the downstream controller can feed to
ADS_PAUSE_CAMPAIGN / ADS_UPDATE_BUDGET / ADS_RESUME_CAMPAIGN
capabilities.
"""
from __future__ import annotations

import copy
import time
from typing import Any

ENGINE_NAME = "roas_guardrails"

_DEFAULT_SPEND_FLOOR = 50.0
_DEFAULT_THRESHOLDS = {
    "kill":             1.0,
    "reduce":           1.5,
    "hold":             2.0,
    "scale":            3.0,
}
_DEFAULT_REDUCE_PCT = 0.30
_DEFAULT_SCALE_PCT = 0.20
_DEFAULT_SCALE_AGGRESSIVE_PCT = 0.50
_DEFAULT_MAX_DAILY_BUDGET = 100.0


class RoasGuardrailsEngine:
    """Wrapper class for engine-registry compatibility."""

    ENGINE_NAME = ENGINE_NAME
    engine_name = ENGINE_NAME

    def run(self, input_data: dict[str, Any] | None = None) -> dict[str, Any]:
        return run(input_data)


def _fail(msg: str, start: float) -> dict[str, Any]:
    return {
        "status": "error",
        "data": {},
        "meta": {
            "engine": ENGINE_NAME,
            "timestamp": time.time(),
            "elapsed_seconds": round(time.monotonic() - start, 3),
        },
        "error": msg,
    }


def run(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Public entry point — campaign metrics → guardrail decisions."""
    start = time.monotonic()
    data = copy.deepcopy(input_data or {})

    if data.get("status") == "fail":
        return _fail(data.get("error") or "Upstream failure", start)

    campaigns = data.get("campaigns")
    if not isinstance(campaigns, list) or not campaigns:
        return _fail("'campaigns' list is required and must be non-empty", start)

    thresholds = data.get("thresholds") or {}
    if not isinstance(thresholds, dict):
        thresholds = {}

    t_kill = _to_float(thresholds.get("kill")) or _DEFAULT_THRESHOLDS["kill"]
    t_reduce = _to_float(thresholds.get("reduce")) or _DEFAULT_THRESHOLDS["reduce"]
    t_hold = _to_float(thresholds.get("hold")) or _DEFAULT_THRESHOLDS["hold"]
    t_scale = _to_float(thresholds.get("scale")) or _DEFAULT_THRESHOLDS["scale"]

    spend_floor = thresholds.get("spend_floor_usd")
    if spend_floor is not None:
        spend_floor = _to_float(spend_floor)
    else:
        spend_floor = _DEFAULT_SPEND_FLOOR

    max_daily = _to_float(thresholds.get("max_daily_budget_usd")) or _DEFAULT_MAX_DAILY_BUDGET
    cpa_ceiling = _to_float(thresholds.get("cpa_ceiling_usd")) or 0.0

    reduce_pct = _to_float(thresholds.get("reduce_pct")) or _DEFAULT_REDUCE_PCT
    scale_pct = _to_float(thresholds.get("scale_pct")) or _DEFAULT_SCALE_PCT
    scale_agg_pct = _to_float(thresholds.get("scale_aggressive_pct")) or _DEFAULT_SCALE_AGGRESSIVE_PCT

    decisions: list[dict[str, Any]] = []
    summary = {
        "total_campaigns": len(campaigns),
        "kill": 0,
        "reduce": 0,
        "hold": 0,
        "scale": 0,
        "scale_aggressive": 0,
        "learning": 0,
    }

    for c in campaigns:
        if not isinstance(c, dict):
            continue
        decision = _evaluate_campaign(
            campaign=c,
            t_kill=t_kill,
            t_reduce=t_reduce,
            t_hold=t_hold,
            t_scale=t_scale,
            spend_floor=spend_floor,
            max_daily=max_daily,
            cpa_ceiling=cpa_ceiling,
            reduce_pct=reduce_pct,
            scale_pct=scale_pct,
            scale_agg_pct=scale_agg_pct,
        )
        decisions.append(decision)
        action = decision["action"]
        if action in summary:
            summary[action] += 1

    elapsed = round(time.monotonic() - start, 3)
    return {
        "status": "success",
        "data": {
            "decisions": decisions,
            "summary": summary,
            "thresholds_used": {
                "kill": t_kill,
                "reduce": t_reduce,
                "hold": t_hold,
                "scale": t_scale,
                "spend_floor_usd": spend_floor,
                "max_daily_budget_usd": max_daily,
                "cpa_ceiling_usd": cpa_ceiling,
            },
        },
        "meta": {
            "engine": ENGINE_NAME,
            "timestamp": time.time(),
            "elapsed_seconds": elapsed,
        },
        "error": None,
    }


def _evaluate_campaign(
    *,
    campaign: dict[str, Any],
    t_kill: float,
    t_reduce: float,
    t_hold: float,
    t_scale: float,
    spend_floor: float,
    max_daily: float,
    cpa_ceiling: float,
    reduce_pct: float,
    scale_pct: float,
    scale_agg_pct: float,
) -> dict[str, Any]:
    """Evaluate a single campaign and return an action decision."""
    campaign_id = str(campaign.get("campaign_id", "") or "")
    campaign_name = str(campaign.get("campaign_name", "") or "")
    spend = _to_float(campaign.get("spend"))
    revenue = _to_float(campaign.get("revenue"))
    purchases = _to_int(campaign.get("purchases"))
    daily_budget = _to_float(campaign.get("daily_budget"))
    current_status = str(campaign.get("status", "ACTIVE") or "ACTIVE").upper()

    roas = revenue / spend if spend > 0 else 0.0
    cpa = spend / purchases if purchases > 0 else 0.0

    in_learning = spend < spend_floor

    action, reason, budget_change = _decide(
        roas=roas,
        cpa=cpa,
        spend=spend,
        daily_budget=daily_budget,
        in_learning=in_learning,
        current_status=current_status,
        t_kill=t_kill,
        t_reduce=t_reduce,
        t_hold=t_hold,
        t_scale=t_scale,
        max_daily=max_daily,
        cpa_ceiling=cpa_ceiling,
        reduce_pct=reduce_pct,
        scale_pct=scale_pct,
        scale_agg_pct=scale_agg_pct,
    )

    result: dict[str, Any] = {
        "campaign_id":   campaign_id,
        "campaign_name": campaign_name,
        "action":        action,
        "reason":        reason,
        "roas":          round(roas, 2),
        "cpa":           round(cpa, 2),
        "spend":         round(spend, 2),
        "revenue":       round(revenue, 2),
        "purchases":     purchases,
        "in_learning":   in_learning,
    }

    if budget_change is not None:
        result["new_daily_budget"] = round(budget_change, 2)

    return result


def _decide(
    *,
    roas: float,
    cpa: float,
    spend: float,
    daily_budget: float,
    in_learning: bool,
    current_status: str,
    t_kill: float,
    t_reduce: float,
    t_hold: float,
    t_scale: float,
    max_daily: float,
    cpa_ceiling: float,
    reduce_pct: float,
    scale_pct: float,
    scale_agg_pct: float,
) -> tuple[str, str, float | None]:
    """Core decision logic. Returns (action, reason, new_daily_budget|None)."""

    if current_status == "PAUSED":
        if roas >= t_hold:
            return (
                "scale",
                f"paused campaign has ROAS {roas:.1f}x — recommend resume + scale",
                None,
            )
        return ("hold", "campaign already paused", None)

    if spend == 0 and daily_budget == 0:
        return ("learning", "no spend data yet", None)

    # CPA ceiling override — even if ROAS looks healthy, CPA too high
    # means unit economics are unsustainable
    if cpa_ceiling > 0 and cpa > cpa_ceiling and not in_learning:
        new_budget = max(daily_budget * (1 - reduce_pct), 1.0)
        return (
            "reduce",
            f"CPA ${cpa:.2f} exceeds ceiling ${cpa_ceiling:.2f}",
            new_budget,
        )

    # Learning-phase protection for downside actions
    if in_learning:
        if roas >= t_hold:
            new_budget = min(daily_budget * (1 + scale_pct), max_daily)
            return (
                "scale",
                f"ROAS {roas:.1f}x during learning — early scale",
                new_budget,
            )
        return (
            "learning",
            f"spend ${spend:.2f} < floor ${_DEFAULT_SPEND_FLOOR:.2f} — too early to judge",
            None,
        )

    # Post-learning-phase ROAS decisions
    if roas < t_kill:
        return ("kill", f"ROAS {roas:.1f}x < {t_kill:.1f}x — losing money", None)

    if roas < t_reduce:
        new_budget = max(daily_budget * (1 - reduce_pct), 1.0)
        return (
            "reduce",
            f"ROAS {roas:.1f}x < {t_reduce:.1f}x — cut budget {reduce_pct:.0%}",
            new_budget,
        )

    if roas < t_hold:
        return ("hold", f"ROAS {roas:.1f}x in hold band ({t_reduce:.1f}x–{t_hold:.1f}x)", None)

    if roas < t_scale:
        new_budget = min(daily_budget * (1 + scale_pct), max_daily)
        return (
            "scale",
            f"ROAS {roas:.1f}x — scale budget +{scale_pct:.0%}",
            new_budget,
        )

    new_budget = min(daily_budget * (1 + scale_agg_pct), max_daily)
    return (
        "scale_aggressive",
        f"ROAS {roas:.1f}x ≥ {t_scale:.1f}x — aggressive scale +{scale_agg_pct:.0%}",
        new_budget,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_float(val: Any) -> float:
    if val is None:
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _to_int(val: Any) -> int:
    if val is None:
        return 0
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return 0
