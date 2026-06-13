"""Reasoning rules for the store strategist.

Each rule maps an observed signal → a Recommendation. Rules
are deterministic + composable. The LLM-augmented variant
(future) wraps this baseline.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Recommendation:
    action: str                       # Short imperative
    reasoning: str                    # Why
    confidence: float                 # 0..1
    impact: str                       # high / medium / low
    drill_command: str                # `shopai X`
    priority_score: float = 0.0       # Computed
    source_signal: str = ""           # Which collector


@dataclass
class StoreContext:
    """Aggregated observation signals."""
    store_id: str
    niche: str = ""
    funnel_verdict: str = "unknown"
    funnel_weakest: str = ""
    funnel_drop: float = 0.0
    trajectory_verdict: str = "unknown"
    trajectory_slope_pct: float = 0.0
    earning_engines: list[str] = field(default_factory=list)
    earning_count: int = 0
    total_revenue_7d: float = 0.0
    checkup_verdict: str = "unknown"
    checkup_partial: list[str] = field(default_factory=list)
    autonomy_overall: str = "unknown"
    autonomy_paused: list[str] = field(default_factory=list)
    has_products: bool = False
    has_ads_wired: bool = False
    has_esp_wired: bool = False


def _safe_call(fn, default, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "store_strategist: call %s raised: %s",
            getattr(fn, "__name__", "?"), exc,
        )
        return default


def collect_context(
    store_id: str,
) -> StoreContext:
    """Pull all observation signals for a single store."""
    ctx = StoreContext(store_id=store_id)

    # Niche (from StoreManager)
    try:
        from data_pipeline.store.store_manager import (
            StoreManager,
        )
        row = StoreManager().get_store(store_id) or {}
        ctx.niche = (row.get("niche") or "").strip().lower()
    except Exception as exc:  # noqa: BLE001
        logger.debug("strategist niche lookup: %s", exc)

    # Funnel
    try:
        from engines.conversion_funnel import (
            ConversionFunnelEngine,
        )
        fr = ConversionFunnelEngine().run({
            "data": {"days": 7, "store_id": store_id},
        })
        data = fr.get("data") or {}
        ctx.funnel_verdict = data.get("verdict", "unknown")
        ctx.funnel_weakest = data.get("weakest_link", "")
        ctx.funnel_drop = float(
            data.get("weakest_drop") or 0.0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("strategist funnel: %s", exc)

    # Trajectory
    try:
        from engines.daily_trajectory import (
            DailyTrajectoryEngine,
        )
        tr = DailyTrajectoryEngine().run({
            "data": {"days": 14, "store_id": store_id},
        })
        data = tr.get("data") or {}
        ctx.trajectory_verdict = data.get(
            "verdict", "unknown",
        )
        ctx.trajectory_slope_pct = float(
            data.get("slope_pct") or 0.0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("strategist trajectory: %s", exc)

    # Earnings by engine
    try:
        from engines.earnings_by_engine import (
            EarningsByEngineEngine,
        )
        er = EarningsByEngineEngine().run({
            "data": {
                "window_hours": 168.0,
                "store_id": store_id,
            },
        })
        data = er.get("data") or {}
        ctx.earning_count = int(data.get("earning_count") or 0)
        ctx.total_revenue_7d = float(
            data.get("total_attributed_revenue") or 0.0,
        )
        ctx.earning_engines = [
            e.get("engine", "")
            for e in (data.get("engines") or [])
            if e.get("verdict") == "earning"
        ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("strategist earnings: %s", exc)

    # Checkup
    try:
        from engines.checkup import CheckupEngine
        cr = CheckupEngine().run({
            "data": {"store_id": store_id},
        })
        data = cr.get("data") or {}
        ctx.checkup_verdict = data.get("verdict", "unknown")
        for e in data.get("engines") or []:
            if e.get("verdict") == "partial":
                ctx.checkup_partial.append(
                    e.get("engine", ""),
                )
                if e.get("engine") == "ads_launcher":
                    ctx.has_ads_wired = False
                if e.get("engine") == "email_connect":
                    ctx.has_esp_wired = False
            elif e.get("verdict") == "ready":
                if e.get("engine") == "ads_launcher":
                    ctx.has_ads_wired = True
                if e.get("engine") == "email_connect":
                    ctx.has_esp_wired = True
                if e.get("engine") in (
                    "product_sourcer", "earn_bootstrap",
                ):
                    ctx.has_products = True
    except Exception as exc:  # noqa: BLE001
        logger.debug("strategist checkup: %s", exc)

    # Autonomy
    try:
        from core.automation.autonomy_status import (
            get_autonomy_status,
        )
        kwargs = {}
        if store_id:
            kwargs["store_id"] = store_id
        report = get_autonomy_status(**kwargs)
        ctx.autonomy_overall = getattr(
            report, "overall_verdict", "unknown",
        )
        for d in getattr(report, "domains", []) or []:
            if getattr(d, "paused", False):
                ctx.autonomy_paused.append(d.name)
    except Exception as exc:  # noqa: BLE001
        logger.debug("strategist autonomy: %s", exc)

    return ctx


def _impact_to_score(impact: str) -> float:
    return {"high": 1.0, "medium": 0.6, "low": 0.3}.get(
        impact, 0.5,
    )


def _compute_priority(rec: Recommendation) -> float:
    """Priority = confidence * impact_score."""
    return rec.confidence * _impact_to_score(rec.impact)


def derive_recommendations(
    ctx: StoreContext,
) -> list[Recommendation]:
    """Apply the deterministic rule set."""
    out: list[Recommendation] = []

    # Rule 1: critical substrate gaps block everything.
    if ctx.checkup_verdict == "error":
        out.append(Recommendation(
            action=(
                "Fix substrate errors before firing any engine"
            ),
            reasoning=(
                "checkup verdict=error -- 1+ engine raised "
                "an exception. Other recommendations are "
                "moot until substrate is healthy."
            ),
            confidence=0.95,
            impact="high",
            drill_command="shopai checkup --json",
            source_signal="checkup",
        ))

    # Rule 2: missing products = cold_start, MUST seed first.
    if not ctx.has_products and ctx.total_revenue_7d == 0.0:
        out.append(Recommendation(
            action=(
                "Seed product catalog (cold-start)"
            ),
            reasoning=(
                "No products + no revenue = empty store. "
                "Nothing else helps until catalog is live."
            ),
            confidence=0.9,
            impact="high",
            drill_command=(
                f"shopai earn-bootstrap --niche "
                f"{ctx.niche or 'general'} --count 20 --yes"
            ),
            source_signal="cold_start",
        ))

    # Rule 3: trajectory declining → check + intervene.
    if ctx.trajectory_verdict == "declining":
        out.append(Recommendation(
            action=(
                "Investigate revenue decline + fire "
                "intervention"
            ),
            reasoning=(
                f"trajectory slope {ctx.trajectory_slope_pct:+.1f}%. "
                "Something stopped working — check engine "
                "alerts + run a fresh cycle."
            ),
            confidence=0.8,
            impact="high",
            drill_command="shopai engine alerts",
            source_signal="trajectory",
        ))

    # Rule 4: funnel weakest = checkouts_completed → cart recovery.
    if ctx.funnel_weakest == "checkouts_completed":
        out.append(Recommendation(
            action="Fire cart_recovery for abandoned checkouts",
            reasoning=(
                f"Biggest funnel drop is checkout → paid "
                f"({ctx.funnel_drop*100:.0f}% abandon). "
                "cart_recovery targets exactly this stage."
            ),
            confidence=0.85,
            impact="high",
            drill_command=(
                "shopai approvals approve-all "
                "--engine cart_recovery --execute"
            ),
            source_signal="funnel",
        ))

    # Rule 5: funnel weakest = checkouts_started → CRO.
    if ctx.funnel_weakest == "checkouts_started":
        out.append(Recommendation(
            action="Run CRO variants on top product",
            reasoning=(
                f"Biggest funnel drop is product → checkout "
                f"({ctx.funnel_drop*100:.0f}%). CRO variants "
                "target product page conversion."
            ),
            confidence=0.7,
            impact="medium",
            drill_command="shopai cro variants",
            source_signal="funnel",
        ))

    # Rule 6: trajectory rising + funnel healthy → bump ads.
    if (
        ctx.trajectory_verdict == "rising"
        and ctx.funnel_verdict == "healthy"
        and ctx.has_ads_wired
    ):
        out.append(Recommendation(
            action="Reinvest: bump ad budget on top channel",
            reasoning=(
                f"Trajectory rising +{ctx.trajectory_slope_pct:.1f}% "
                "with healthy funnel. Reinvest into the engine "
                "that's already converting."
            ),
            confidence=0.8,
            impact="high",
            drill_command=(
                "shopai roas && shopai ads launch "
                "--budget-daily 25"
            ),
            source_signal="trajectory_funnel",
        ))

    # Rule 7: no ESP wired → review/welcome are silent.
    if not ctx.has_esp_wired:
        out.append(Recommendation(
            action="Wire ESP (Brevo / Resend) credentials",
            reasoning=(
                "review_request + welcome_series require an "
                "ESP. Without one, ~30% of post-purchase "
                "conversion leverage stays dormant."
            ),
            confidence=0.7,
            impact="medium",
            drill_command=(
                "shopai email connect brevo --api-key KEY"
            ),
            source_signal="checkup",
        ))

    # Rule 8: no ads wired + has products → ads operator action.
    if not ctx.has_ads_wired and ctx.has_products:
        out.append(Recommendation(
            action="Wire paid channel (Meta or Google Ads)",
            reasoning=(
                "Products live but no ads. Organic traffic "
                "alone rarely crosses cold_start; paid is "
                "the fastest cycle-back."
            ),
            confidence=0.7,
            impact="medium",
            drill_command=(
                "shopai ads connect meta --token X "
                "--account-id Y"
            ),
            source_signal="checkup",
        ))

    # Rule 9: autonomy paused → unblock first.
    if ctx.autonomy_paused:
        paused_list = ", ".join(ctx.autonomy_paused)
        out.append(Recommendation(
            action=(
                f"Investigate paused autonomy domains: "
                f"{paused_list}"
            ),
            reasoning=(
                "Paused domains can't fire writers. Review "
                "the pause reason + manually clear if safe."
            ),
            confidence=0.75,
            impact="medium",
            drill_command="shopai autonomy-status",
            source_signal="autonomy",
        ))

    # Rule 10: catch-all when nothing recommended.
    if not out and ctx.total_revenue_7d > 0.0:
        out.append(Recommendation(
            action="Already earning — schedule recurring cycle",
            reasoning=(
                f"7d revenue ${ctx.total_revenue_7d:.2f} with "
                "no critical signals. Lock in the win."
            ),
            confidence=0.6,
            impact="medium",
            drill_command="shopai cycle schedule",
            source_signal="catch_all_earning",
        ))
    elif not out:
        out.append(Recommendation(
            action="Wait for more data",
            reasoning=(
                "Not enough signal to recommend confidently. "
                "Need at least 7 days of cycle activity."
            ),
            confidence=0.3,
            impact="low",
            drill_command="shopai cycle status",
            source_signal="catch_all_quiet",
        ))

    # Compute priority for ranking.
    for r in out:
        r.priority_score = round(_compute_priority(r), 3)

    out.sort(key=lambda r: r.priority_score, reverse=True)
    return out


def overall_verdict(
    ctx: StoreContext,
    recs: list[Recommendation],
) -> str:
    """Pick a coarse verdict: intervene / active / wait."""
    if any(r.impact == "high" and r.confidence >= 0.8 for r in recs):
        # critical action recommended
        return "intervene"
    if ctx.total_revenue_7d > 0.0:
        return "active"
    return "wait"
