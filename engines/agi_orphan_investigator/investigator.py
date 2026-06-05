"""Aggregate + drill into orphan AGI attribution claims."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EngineOrphanStats:
    engine: str
    orphan_count: int = 0
    stores_affected: list[str] = field(default_factory=list)
    action_types: list[str] = field(default_factory=list)
    median_age_hours: float = 0.0
    suspicion: str = "low"   # low / medium / high


@dataclass
class StoreOrphanStats:
    store_id: str
    orphan_count: int = 0
    distinct_engines: int = 0


@dataclass
class OrphanReport:
    days: int
    attribution_window_hours: float
    total_orphan_count: int = 0
    total_stores_with_orphans: int = 0
    distinct_engines: int = 0
    by_engine: list[EngineOrphanStats] = field(
        default_factory=list,
    )
    by_store: list[StoreOrphanStats] = field(
        default_factory=list,
    )
    headline: str = ""
    next_action: str = ""
    drill_hints: list[str] = field(default_factory=list)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2.0
    return s[mid]


def _classify_suspicion(stats: EngineOrphanStats) -> str:
    """Higher orphan count + more affected stores =
    higher suspicion this engine is misconfigured vs
    occasional miss."""
    if stats.orphan_count >= 10:
        return "high"
    if stats.orphan_count >= 4 and (
        len(stats.stores_affected) >= 2
    ):
        return "high"
    if stats.orphan_count >= 3:
        return "medium"
    return "low"


def _build_drill_hints(
    report: OrphanReport,
) -> list[str]:
    hints: list[str] = []
    if not report.by_engine:
        return hints
    top = report.by_engine[0]
    if top.suspicion == "high":
        hints.append(
            f"shopai engine pulse {top.engine}  "
            f"-- check recent activity"
        )
        hints.append(
            f"shopai engine alerts  "
            f"-- has {top.engine} been flagged?"
        )
    if (
        report.attribution_window_hours
        and report.attribution_window_hours < 168.0
        and top.median_age_hours
        > report.attribution_window_hours
    ):
        hints.append(
            "Consider wider attribution window: "
            f"--attribution-window-hours "
            f"{int(top.median_age_hours * 1.2)}"
        )
    if len(report.by_store) >= 2:
        hints.append(
            "shopai reconcile --store <X>  "
            "-- drill per-store"
        )
    return hints


def _build_headline(report: OrphanReport) -> str:
    if report.total_orphan_count == 0:
        return (
            "No orphan AGI claims detected in window."
        )
    top = report.by_engine[0] if report.by_engine else None
    if top is None:
        return (
            f"{report.total_orphan_count} orphan(s) "
            f"across {report.distinct_engines} engine(s)."
        )
    return (
        f"{report.total_orphan_count} orphan(s) across "
        f"{report.distinct_engines} engine(s); top: "
        f"{top.engine} ({top.orphan_count}, "
        f"{top.suspicion}-suspicion)"
    )


def _build_next_action(report: OrphanReport) -> str:
    if report.total_orphan_count == 0:
        return "Clean -- reconciliation is honest."
    high = [
        e for e in report.by_engine
        if e.suspicion == "high"
    ]
    if high:
        names = ", ".join(
            e.engine for e in high[:3]
        )
        return (
            f"{len(high)} high-suspicion engine(s): "
            f"{names}. Run drill hints below."
        )
    return (
        f"{report.total_orphan_count} orphan(s) -- low "
        "suspicion; widen attribution window or watch."
    )


def investigate(
    *,
    days: int = 7,
    attribution_window_hours: float = 48.0,
    fleet_report_override: Any = None,
) -> OrphanReport:
    """Build the structured drill report."""
    report = OrphanReport(
        days=max(1, min(days, 365)),
        attribution_window_hours=max(
            0.0, float(attribution_window_hours),
        ),
    )
    if fleet_report_override is not None:
        fleet = fleet_report_override
    else:
        try:
            from engines.revenue_reconciliation.reconciler \
                import reconcile_fleet
            fleet = reconcile_fleet(
                days=report.days,
                attribution_window_hours=(
                    report.attribution_window_hours
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "orphan_investigator: recon raised: %s",
                exc,
            )
            return report

    by_engine_map: dict[str, EngineOrphanStats] = {}
    by_store_count: dict[str, int] = {}
    by_store_engines: dict[str, set[str]] = {}
    engine_ages: dict[str, list[float]] = {}

    for store_recon in getattr(fleet, "by_store", []) or []:
        orphans = list(
            getattr(store_recon, "orphans", None) or []
        )
        sid = getattr(store_recon, "store_id", "")
        if not orphans:
            continue
        by_store_count[sid] = (
            by_store_count.get(sid, 0) + len(orphans)
        )
        by_store_engines.setdefault(sid, set())
        for orphan in orphans:
            eng = str(getattr(orphan, "engine", "") or "")
            if not eng:
                eng = "(unknown)"
            atype = str(
                getattr(orphan, "action_type", "") or "",
            )
            try:
                age = float(
                    getattr(orphan, "age_hours", 0) or 0
                )
            except (TypeError, ValueError):
                age = 0.0
            stats = by_engine_map.setdefault(
                eng,
                EngineOrphanStats(engine=eng),
            )
            stats.orphan_count += 1
            if sid and sid not in stats.stores_affected:
                stats.stores_affected.append(sid)
            if (
                atype
                and atype not in stats.action_types
            ):
                stats.action_types.append(atype)
            engine_ages.setdefault(eng, []).append(age)
            by_store_engines[sid].add(eng)

    for eng, stats in by_engine_map.items():
        stats.median_age_hours = round(
            _median(engine_ages.get(eng, [])), 1,
        )
        stats.suspicion = _classify_suspicion(stats)
    # Sort engines by orphan count desc
    report.by_engine = sorted(
        by_engine_map.values(),
        key=lambda s: s.orphan_count, reverse=True,
    )
    # Per-store stats
    for sid, cnt in by_store_count.items():
        report.by_store.append(StoreOrphanStats(
            store_id=sid, orphan_count=cnt,
            distinct_engines=len(by_store_engines[sid]),
        ))
    report.by_store.sort(
        key=lambda s: s.orphan_count, reverse=True,
    )
    report.total_orphan_count = sum(
        by_store_count.values()
    )
    report.total_stores_with_orphans = len(by_store_count)
    report.distinct_engines = len(by_engine_map)
    report.headline = _build_headline(report)
    report.next_action = _build_next_action(report)
    report.drill_hints = _build_drill_hints(report)
    return report
