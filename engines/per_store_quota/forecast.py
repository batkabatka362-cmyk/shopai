"""W963-123: cost forecaster.

Predicts when a (store, adapter) pair will hit its cap
based on recent spend rate. Linear extrapolation -- not
ARIMA. The point is to give the operator a "you have ~8
hours of headroom" signal BEFORE the cap fires, not to
hit the right hour to the minute.

Algorithm:
  1. Read last N hours of cost events for the (store,
     adapter) pair via W963-118 query.
  2. Compute the recent spend rate as total / N.
  3. Project the headroom (cap - spend_so_far) at that
     rate.
  4. Return hours_to_cap + a verdict label.

Verdict ladder:
  no_cap:    cap is 0 / unlimited
  no_rate:   spend rate is 0 (no recent activity)
  no_risk:   hours_to_cap > 48 (more than 2 days away)
  imminent:  hours_to_cap in (4, 48] (today or tomorrow)
  critical:  hours_to_cap <= 4 (immediate intervention)
  exhausted: already over cap

Designed to be cheap (single query.iter pass) so the
forecast can run inline in dashboards without slowing
them down.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum

from engines.per_store_costs.query import (
    _stream_events,
)

from .budget_config import resolve_cap

logger = logging.getLogger(__name__)


class ForecastVerdict(str, Enum):
    NO_CAP = "no_cap"
    NO_RATE = "no_rate"
    NO_RISK = "no_risk"
    IMMINENT = "imminent"
    CRITICAL = "critical"
    EXHAUSTED = "exhausted"

    @property
    def severity_rank(self) -> int:
        """Higher = more urgent."""
        return {
            "no_cap": 0,
            "no_risk": 0,
            "no_rate": 0,
            "imminent": 1,
            "critical": 2,
            "exhausted": 3,
        }.get(self.value, 0)


@dataclass
class ForecastSnapshot:
    """Prediction for one (store, adapter) pair."""
    store_id: str
    adapter: str             # Empty = total spend
    cap_usd: float
    spend_so_far_usd: float
    rate_per_hour_usd: float
    headroom_usd: float      # 0.0 if cap exhausted
    hours_to_cap: float      # inf if rate=0; 0.0 if cap=0;
                             # 0.0 if already exhausted
    verdict: ForecastVerdict
    sample_hours: float      # Window the rate was computed over


def _rate_per_hour(
    *,
    store_id: str,
    adapter: str,
    sample_hours: float,
) -> tuple[float, float]:
    """Return (spend_in_sample, sample_hours).

    sample_hours is returned unchanged so the caller can
    log the actual sample window used (in case we ever
    auto-tune).
    """
    if sample_hours <= 0.0:
        return 0.0, 0.0
    cutoff = time.time() - sample_hours * 3600.0
    total = 0.0
    for e in _stream_events(since_ts=cutoff):
        sid = str(e.get("store_id") or "")
        if store_id and sid != store_id:
            continue
        if adapter and str(
            e.get("adapter") or "",
        ) != adapter:
            continue
        try:
            total += float(e.get("cost_usd", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
    return total, sample_hours


def _classify(
    *,
    cap: float,
    rate: float,
    hours_to_cap: float,
    spend_so_far: float,
) -> ForecastVerdict:
    if cap <= 0:
        return ForecastVerdict.NO_CAP
    if spend_so_far >= cap:
        return ForecastVerdict.EXHAUSTED
    if rate <= 0:
        return ForecastVerdict.NO_RATE
    if hours_to_cap <= 4.0:
        return ForecastVerdict.CRITICAL
    if hours_to_cap <= 48.0:
        return ForecastVerdict.IMMINENT
    return ForecastVerdict.NO_RISK


def forecast_to_cap(
    store_id: str,
    *,
    adapter: str = "",
    sample_hours: float = 6.0,
    cap_window_hours: float = 24.0,
) -> ForecastSnapshot:
    """Predict when (store, adapter) will hit its cap.

    Args:
        store_id: target store (required).
        adapter: target adapter; empty = total spend.
        sample_hours: rolling window for rate calculation.
            6h default = recent enough to react to a spike,
            wide enough to avoid noise.
        cap_window_hours: window the cap is enforced over.
            24h default matches resolve_cap which is daily.

    Returns:
        ForecastSnapshot with the verdict label + numeric
        fields populated.
    """
    cap = resolve_cap(
        store_id=store_id, adapter=adapter,
    )

    # Spend so far in the CAP window (typically 24h)
    cap_spend, _ = _rate_per_hour(
        store_id=store_id, adapter=adapter,
        sample_hours=cap_window_hours,
    )

    # Recent spend rate from the SAMPLE window
    sample_spend, sample = _rate_per_hour(
        store_id=store_id, adapter=adapter,
        sample_hours=sample_hours,
    )
    rate = (
        sample_spend / sample if sample > 0 else 0.0
    )

    headroom = max(0.0, cap - cap_spend) if cap > 0 else 0.0
    if cap <= 0:
        hours_to_cap = 0.0
    elif cap_spend >= cap:
        hours_to_cap = 0.0
    elif rate <= 0:
        hours_to_cap = float("inf")
    else:
        hours_to_cap = headroom / rate

    # Sanitise inf for JSON
    hours_for_json = (
        9999.0 if hours_to_cap == float("inf")
        else round(hours_to_cap, 2)
    )

    verdict = _classify(
        cap=cap, rate=rate,
        hours_to_cap=hours_to_cap,
        spend_so_far=cap_spend,
    )

    return ForecastSnapshot(
        store_id=store_id,
        adapter=adapter,
        cap_usd=round(cap, 4),
        spend_so_far_usd=round(cap_spend, 4),
        rate_per_hour_usd=round(rate, 4),
        headroom_usd=round(headroom, 4),
        hours_to_cap=hours_for_json,
        verdict=verdict,
        sample_hours=sample,
    )


def fleet_forecasts(
    *,
    sample_hours: float = 6.0,
    cap_window_hours: float = 24.0,
) -> list[ForecastSnapshot]:
    """Forecast for every (store, adapter) pair seen in
    the cap window. Sorted by verdict severity desc, then
    by hours_to_cap asc so the urgent ones surface first.
    """
    from engines.per_store_costs.query import (
        costs_by_store,
    )
    out: list[ForecastSnapshot] = []
    by_store = costs_by_store(
        window_hours=cap_window_hours,
    )
    for sid, summary in by_store.items():
        if sid in ("(fleet)", ""):
            continue
        # Per-store total
        out.append(forecast_to_cap(
            sid, adapter="",
            sample_hours=sample_hours,
            cap_window_hours=cap_window_hours,
        ))
        # Per-adapter rows
        for adapter_name in summary.by_adapter:
            out.append(forecast_to_cap(
                sid, adapter=adapter_name,
                sample_hours=sample_hours,
                cap_window_hours=cap_window_hours,
            ))

    out.sort(
        key=lambda f: (
            -f.verdict.severity_rank,
            f.hours_to_cap,
            f.store_id,
            f.adapter,
        ),
    )
    return out
