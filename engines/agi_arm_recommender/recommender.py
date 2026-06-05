"""Recommend engine arm/disarm based on Phase 4 signals."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# Engine taxonomy by behavior class. Used by the recipe
# table to decide which set to arm/disarm per verdict.
_REVENUE_DRIVING = (
    "loyalty",
    "email_marketing",
    "affiliate",
    "cart_recovery",
    "browse_recovery",
    "welcome_series",
)
_SPEND_ENGINES = (
    "ads_launcher",
    "pinterest_publisher",
    "instagram_publisher",
    "tiktok_publisher",
)
_RETENTION_ENGINES = (
    "loyalty",
    "cart_recovery",
    "churn_prediction",
    "review_request",
)
_CONSERVATION_ENGINES = (
    "refund_applier",
    "discount_cleanup",
    "cart_recovery",
)
_EXPLORATION_ENGINES = (
    "transfer_scan",
    "content_publisher",
    "product_sourcer",
)
_KICKSTART_ENGINES = (
    "content_publisher",
    "product_sourcer",
    "blog_post_generator",
)
_DESTRUCTIVE_ENGINES = (
    "product_lifecycle",
    "discount_cleanup",
    "refund_applier",
)


@dataclass
class EngineRecommendation:
    engine: str
    action: str   # arm / disarm / maintain
    rationale: str
    priority: str = "normal"  # critical / normal / info


@dataclass
class ArmReport:
    verdict: str
    trajectory: str
    streak_severity: str
    critical_anomaly_count: int
    arm_recommendations: list[EngineRecommendation] = field(
        default_factory=list,
    )
    disarm_recommendations: list[EngineRecommendation] = (
        field(default_factory=list)
    )
    headline: str = ""
    next_action: str = ""
    override_applied: str | None = None


def _gather_signals() -> dict[str, Any]:
    sig: dict[str, Any] = {
        "verdict": "no_data",
        "trajectory": "no_data",
        "streak_top": None,
        "streak_severity": "info",
        "streak_count": 0,
        "critical_anomaly_count": 0,
    }
    try:
        from engines.agi_earnings_summary.summarizer \
            import compute_summary
        s = compute_summary(days=7)
        sig["verdict"] = s.verdict
        sig["history_trend"] = s.trend_verdict
    except Exception as exc:  # noqa: BLE001
        logger.debug("arm: summary raised: %s", exc)
    try:
        from engines.agi_brief_diff.differ import (
            compute_diff,
        )
        d = compute_diff()
        if d.sufficient:
            sig["trajectory"] = d.direction
    except Exception as exc:  # noqa: BLE001
        logger.debug("arm: diff raised: %s", exc)
    try:
        from engines.agi_recommend_streak.detector import (
            detect_streaks,
        )
        sr = detect_streaks(threshold_days=3)
        if sr.attention_needed and sr.top_streak:
            top = getattr(sr, sr.top_streak, None)
            if top is not None:
                sig["streak_top"] = top.name
                sig["streak_severity"] = top.severity
                sig["streak_count"] = top.count
    except Exception as exc:  # noqa: BLE001
        logger.debug("arm: streak raised: %s", exc)
    try:
        from engines.agi_anomaly_detector.detector import (
            detect,
        )
        r = detect(window=14)
        sig["critical_anomaly_count"] = sum(
            1 for a in r.anomalies
            if a.severity == "critical"
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("arm: anomaly raised: %s", exc)
    return sig


def _verdict_recipe(
    verdict: str, trajectory: str,
) -> tuple[list[str], list[str], str]:
    """Returns (arm_list, disarm_list, rationale)."""
    if verdict == "earning":
        if trajectory == "improved":
            return (
                list(_EXPLORATION_ENGINES),
                [],
                (
                    "Earning + improving -- compound by "
                    "exploring transfer/content."
                ),
            )
        if trajectory == "regressed":
            return (
                list(_RETENTION_ENGINES),
                list(_SPEND_ENGINES),
                (
                    "Earning but trajectory regressed -- "
                    "shift to retention; cut spend."
                ),
            )
        return (
            [],
            [],
            "Earning + stable -- maintain current set.",
        )
    if verdict == "organic_only":
        return (
            list(_REVENUE_DRIVING),
            [],
            (
                "Organic only -- arm revenue-driving "
                "engines to establish attribution."
            ),
        )
    if verdict == "attributed_loss":
        return (
            list(_CONSERVATION_ENGINES),
            list(_SPEND_ENGINES),
            (
                "Attributed loss -- disarm spend; arm "
                "conservation engines."
            ),
        )
    # no_data
    return (
        list(_KICKSTART_ENGINES),
        [],
        (
            "Empire idle -- arm kick-start engines so "
            "cycles produce signal."
        ),
    )


def _maybe_override(
    sig: dict[str, Any],
    arm: list[str],
    disarm: list[str],
) -> tuple[list[str], list[str], str | None]:
    """Apply higher-priority override rules. Returns
    (arm, disarm, override_label) -- label is None when
    no override applied.

    W963-93 fix: previously this returned early on the
    first matching override, so a loss_streak override
    co-existing with a critical_anomaly disarmed only
    spend engines (missing destructive). Now MERGES every
    applicable override so the disarm list reflects the
    full safety posture.
    """
    crit_anom = int(sig.get("critical_anomaly_count") or 0)
    streak_top = sig.get("streak_top")
    streak_sev = sig.get("streak_severity")

    disarm_set = set(disarm)
    override_reasons: list[str] = []

    # no_data_streak is mutually exclusive with the others
    # because it overwrites the arm list entirely (empire
    # is genuinely idle long-term). Apply that first and
    # short-circuit -- it doesn't compose with regular
    # arm/disarm logic.
    if (
        streak_top == "no_data_streak"
        and streak_sev == "critical"
    ):
        return (
            list(_KICKSTART_ENGINES),
            disarm,
            "critical_no_data_streak: kick-start only",
        )

    # loss_streak critical: full spend disarm.
    if (
        streak_top == "loss_streak"
        and streak_sev == "critical"
    ):
        disarm_set |= set(_SPEND_ENGINES)
        override_reasons.append(
            "critical_loss_streak: full spend disarm",
        )

    # critical anomaly: destructive engines disarmed.
    # COMPOSES with loss_streak so both safety layers
    # apply when both fire.
    if crit_anom > 0:
        disarm_set |= set(_DESTRUCTIVE_ENGINES)
        override_reasons.append(
            f"critical_anomaly={crit_anom}: "
            "destructive engines disarmed",
        )

    if override_reasons:
        # Preserve original disarm-list order, then append
        # newly-added engines deterministically (sorted).
        original = list(disarm)
        added = sorted(disarm_set - set(disarm))
        return (
            arm,
            original + added,
            "; ".join(override_reasons),
        )
    return (arm, disarm, None)


def _build_headline(report: ArmReport) -> str:
    arm_n = len(report.arm_recommendations)
    dis_n = len(report.disarm_recommendations)
    if not arm_n and not dis_n:
        return (
            f"No changes -- verdict={report.verdict}, "
            "current arming sufficient."
        )
    return (
        f"Recommend {arm_n} ARM + {dis_n} DISARM "
        f"for verdict={report.verdict}, "
        f"trajectory={report.trajectory}"
    )


def _build_next_action(report: ArmReport) -> str:
    if not (
        report.arm_recommendations
        or report.disarm_recommendations
    ):
        return (
            "No action needed -- run shopai cycle run "
            "to fire the current arm set."
        )
    armed = ", ".join(
        r.engine for r in
        report.arm_recommendations[:5]
    )
    if armed:
        suffix = (
            f" (and {len(report.arm_recommendations) - 5} more)"
            if len(report.arm_recommendations) > 5 else ""
        )
        return (
            "Run shopai autonomy-arm "
            f"<domain> per engine OR review and apply: "
            f"{armed}{suffix}"
        )
    return (
        "DISARM-only recommendation -- run "
        "shopai autonomy-disarm <domain> per engine."
    )


def recommend(
    *,
    signals_override: dict[str, Any] | None = None,
) -> ArmReport:
    """Build the structured arm/disarm recommendation."""
    sig = (
        signals_override
        if signals_override is not None
        else _gather_signals()
    )
    report = ArmReport(
        verdict=str(sig.get("verdict") or "no_data"),
        trajectory=str(sig.get("trajectory") or "no_data"),
        streak_severity=str(
            sig.get("streak_severity") or "info",
        ),
        critical_anomaly_count=int(
            sig.get("critical_anomaly_count") or 0,
        ),
    )

    arm_list, disarm_list, base_rationale = _verdict_recipe(
        report.verdict, report.trajectory,
    )
    arm_list, disarm_list, override = _maybe_override(
        sig, arm_list, disarm_list,
    )
    report.override_applied = override

    # Build per-engine recommendations
    for eng in dict.fromkeys(arm_list):  # dedupe preserving order
        report.arm_recommendations.append(
            EngineRecommendation(
                engine=eng,
                action="arm",
                rationale=(
                    override
                    if override
                    else base_rationale
                ),
                priority=(
                    "critical"
                    if override else "normal"
                ),
            )
        )
    for eng in dict.fromkeys(disarm_list):
        report.disarm_recommendations.append(
            EngineRecommendation(
                engine=eng,
                action="disarm",
                rationale=(
                    override
                    if override
                    else base_rationale
                ),
                priority=(
                    "critical"
                    if override else "normal"
                ),
            )
        )
    report.headline = _build_headline(report)
    report.next_action = _build_next_action(report)
    return report
