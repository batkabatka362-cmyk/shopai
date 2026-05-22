"""Cycle diary -- chronological event log across all
autonomous-loop history files.

Operators investigating "what has the autonomous loop done
recently?" had to read each history file separately:
cycle_history, auto_demote_history, auto_promote_history,
auto_relax_history, transfer_history, cycle_alert_history.
Six commands, scattered output.

This module is the unified view. Walks every relevant
history module, normalizes events into a common shape, and
returns a single newest-first timeline.

Public surface
--------------
- ``DiaryEvent`` dataclass.
- ``compile_diary(since_seconds, limit)`` -> list[DiaryEvent].

Pure read; no Pattern J needed (nothing writes). Best-
effort: any single source failure -> empty contribution
without breaking the rest.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DiaryEvent:
    """One normalized timeline entry."""

    recorded_at: float
    source: str  # "cycle" | "demote" | "promote" |
    #               "relax" | "transfer" | "alert"
    kind: str   # source-specific event kind
    detail: str
    metrics: dict[str, Any] = field(default_factory=dict)


def compile_diary(
    *,
    since_seconds: int = 86400,
    limit: int = 50,
) -> list[DiaryEvent]:
    """Walk every history module + normalize into a single
    timeline.

    Returns newest-first, capped at ``limit``.
    """
    events: list[DiaryEvent] = []

    # Cycle runs
    try:
        from core.autonomous import (
            cycle_history as _ch,
        )
        for e in _ch.recent_history(
            since_seconds=since_seconds,
        ):
            adv = e.advance or {}
            executed_ok = adv.get("executed_ok", 0) or 0
            refused = adv.get(
                "refused_reliability", 0,
            ) or 0
            mode = "EXEC" if e.executed else "DRY"
            events.append(DiaryEvent(
                recorded_at=e.recorded_at,
                source="cycle",
                kind=mode.lower(),
                detail=(
                    f"[{mode}] cycle ran -- "
                    f"adv={executed_ok}ok/{refused}ref"
                ),
                metrics={
                    "executed_ok": executed_ok,
                    "refused_reliability": refused,
                },
            ))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "compile_diary: cycle_history "
            "raised: %s", exc,
        )

    # Auto-demote / release events
    try:
        from core.capability_planner import (
            auto_demote_history as _adh,
        )
        for e in _adh.recent_history(
            since_seconds=since_seconds,
        ):
            verb = "DEMOTE" if e.kind == "demote" else (
                "RELEASE"
            )
            events.append(DiaryEvent(
                recorded_at=e.recorded_at,
                source="demote",
                kind=e.kind,
                detail=(
                    f"[{verb}] {e.capability} -- "
                    f"{e.reason[:60]}"
                ),
                metrics={"capability": e.capability},
            ))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "compile_diary: auto_demote_history "
            "raised: %s", exc,
        )

    # Auto-promote events
    try:
        from core.capability_planner import (
            auto_promote_history as _aph,
        )
        for e in _aph.recent_history(
            since_seconds=since_seconds,
        ):
            events.append(DiaryEvent(
                recorded_at=e.recorded_at,
                source="promote",
                kind="promote",
                detail=(
                    f"[PROMOTE] {e.capability} -- "
                    f"{e.reason[:60]}"
                ),
                metrics={"capability": e.capability},
            ))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "compile_diary: auto_promote_history "
            "raised: %s", exc,
        )

    # Auto-relax events
    try:
        from core.autonomous import (
            auto_relax_history as _arh,
        )
        for e in _arh.recent_history(
            since_seconds=since_seconds,
        ):
            verb = (
                "RELAX" if e.direction == "relax"
                else "RESTORE"
            )
            events.append(DiaryEvent(
                recorded_at=e.recorded_at,
                source="relax",
                kind=e.direction,
                detail=(
                    f"[{verb}] threshold "
                    f"{e.current_value:.2f} -> "
                    f"{e.proposed_value:.2f}  "
                    f"({e.reason[:50]})"
                ),
                metrics={
                    "from": e.current_value,
                    "to": e.proposed_value,
                },
            ))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "compile_diary: auto_relax_history "
            "raised: %s", exc,
        )

    # Transfer events
    try:
        from core.autonomous import (
            transfer_history as _th,
        )
        for e in _th.recent_history(
            since_seconds=since_seconds,
        ):
            events.append(DiaryEvent(
                recorded_at=e.recorded_at,
                source="transfer",
                kind="enqueue",
                detail=(
                    f"[TRANSFER] {e.engine}/"
                    f"{e.action_type} "
                    f"{e.source_store_id} -> "
                    f"{e.target_store_id}"
                ),
                metrics={
                    "source_store": e.source_store_id,
                    "target_store": e.target_store_id,
                    "engine": e.engine,
                    "action_id": e.action_id,
                },
            ))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "compile_diary: transfer_history "
            "raised: %s", exc,
        )

    # Cycle alert firings (informational; can be noisy)
    try:
        from core.autonomous import (
            cycle_alert_history as _cah,
        )
        for e in _cah.recent_history(
            since_seconds=since_seconds,
        ):
            events.append(DiaryEvent(
                recorded_at=e.recorded_at,
                source="alert",
                kind=e.kind,
                detail=(
                    f"[ALERT] {e.kind} -- "
                    f"{e.detail[:60]}"
                ),
                metrics=e.metrics or {},
            ))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "compile_diary: cycle_alert_history "
            "raised: %s", exc,
        )

    # Newest-first (Windows tie-aware: reverse + stable sort)
    events.reverse()
    events.sort(key=lambda e: -e.recorded_at)
    return events[:max(1, int(limit))]
