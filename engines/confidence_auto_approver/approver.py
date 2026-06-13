"""Per-engine trust scoring + auto-approve PENDING actions.

For each PENDING action:
  1. Pull engine's outcome stats via queue.engine_outcome_stats
  2. Compute positive_ratio = positive / (positive + negative)
  3. If positive_ratio >= threshold AND sample >= min_sample:
     trust = earned, auto-approve via queue.approve
  4. Otherwise leave PENDING

Per-store scoping: when store_id supplied, both the stats
lookup AND the PENDING list filter by store.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TrustDecision:
    action_id: str
    engine: str
    action_type: str
    store_id: str = ""
    sample_size: int = 0
    positive_ratio: float = 0.0
    threshold_met: bool = False
    approved: bool = False
    skip_reason: str = ""


@dataclass
class AutoApproveReport:
    confirmed: bool
    min_sample: int
    min_positive_ratio: float
    store_id: str | None
    pending_scanned: int = 0
    approved_count: int = 0
    skipped_count: int = 0
    decisions: list[TrustDecision] = field(default_factory=list)
    skip_reasons: dict[str, int] = field(default_factory=dict)


def _engine_trust_score(
    queue: Any,
    engine: str,
    store_id: str | None,
    *,
    min_sample: int,
    min_positive_ratio: float,
) -> tuple[bool, int, float]:
    """Compute (trust_earned, sample_size, positive_ratio)
    for an (engine, store) pair."""
    try:
        stats = queue.engine_outcome_stats(
            engine, store_id=store_id,
        ) or {}
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "auto_approver: stats lookup raised: %s", exc,
        )
        return (False, 0, 0.0)

    pos = int(stats.get("positive_count", 0) or 0)
    neg = int(stats.get("negative_count", 0) or 0)
    sample = pos + neg
    if sample == 0:
        return (False, 0, 0.0)
    ratio = pos / sample
    earned = (
        sample >= min_sample
        and ratio >= min_positive_ratio
    )
    return (earned, sample, ratio)


def _bump_skip(report: AutoApproveReport, reason: str) -> None:
    report.skipped_count += 1
    report.skip_reasons[reason] = (
        report.skip_reasons.get(reason, 0) + 1
    )


def auto_approve_pending(
    *,
    confirmed: bool,
    min_sample: int = 5,
    min_positive_ratio: float = 0.8,
    store_id: str | None = None,
    max_approvals: int = 50,
) -> AutoApproveReport:
    """Scan PENDING approvals + auto-approve those whose
    engine has earned trust per-store."""
    report = AutoApproveReport(
        confirmed=confirmed,
        min_sample=max(1, min_sample),
        min_positive_ratio=max(
            0.0, min(1.0, min_positive_ratio),
        ),
        store_id=store_id,
    )

    try:
        from core.approval.queue import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "auto_approver: queue import raised: %s", exc,
        )
        return report

    # Pull PENDING. Per-store filter when store_id supplied.
    try:
        kwargs = {"limit": 200}
        if store_id:
            kwargs["store_id"] = store_id
        pending = list(queue.list_pending(**kwargs))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "auto_approver: list_pending raised: %s", exc,
        )
        return report

    report.pending_scanned = len(pending)
    # Cache trust by (engine, store) so we don't hit
    # engine_outcome_stats N times for batched actions.
    trust_cache: dict[
        tuple[str, str], tuple[bool, int, float],
    ] = {}

    for action in pending:
        eng = getattr(action, "engine", "") or ""
        atype = getattr(action, "action_type", "") or ""
        aid = str(getattr(action, "id", "") or "")
        sid = getattr(action, "store_id", "") or ""
        decision = TrustDecision(
            action_id=aid,
            engine=eng,
            action_type=atype,
            store_id=sid,
        )

        if not eng or not aid:
            decision.skip_reason = "missing_id_or_engine"
            report.decisions.append(decision)
            _bump_skip(report, "missing_id_or_engine")
            continue

        scope = sid if sid else ""
        key = (eng, scope)
        if key not in trust_cache:
            trust_cache[key] = _engine_trust_score(
                queue, eng,
                scope if scope else None,
                min_sample=report.min_sample,
                min_positive_ratio=report.min_positive_ratio,
            )
        earned, sample, ratio = trust_cache[key]
        decision.sample_size = sample
        decision.positive_ratio = round(ratio, 3)
        decision.threshold_met = earned

        if not earned:
            decision.skip_reason = (
                "insufficient_sample"
                if sample < report.min_sample
                else "ratio_below_threshold"
            )
            report.decisions.append(decision)
            _bump_skip(report, decision.skip_reason)
            continue

        if not confirmed:
            decision.skip_reason = "dry_run"
            report.decisions.append(decision)
            _bump_skip(report, "dry_run")
            continue

        if report.approved_count >= max_approvals:
            decision.skip_reason = "max_approvals_hit"
            report.decisions.append(decision)
            _bump_skip(report, "max_approvals_hit")
            continue

        try:
            queue.approve(
                aid,
                decided_by="confidence_auto_approver",
                reason=(
                    f"auto: {sample} sample / "
                    f"{ratio*100:.0f}% positive >= "
                    f"{report.min_positive_ratio*100:.0f}% "
                    f"threshold"
                ),
            )
            decision.approved = True
            report.approved_count += 1
        except Exception as exc:  # noqa: BLE001
            decision.skip_reason = (
                f"approve_failed: {type(exc).__name__}"
            )
            report.skip_reasons["approve_failed"] = (
                report.skip_reasons.get("approve_failed", 0)
                + 1
            )

        report.decisions.append(decision)

    return report
