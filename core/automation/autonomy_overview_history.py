"""Autonomy-overview history persistence (W900).

Records each ``build_overview()`` snapshot to a bounded JSON
log at ``data/autonomy_overview_history.json``. Operators can
then query "when did the verdict flip from active to
degraded?" — the question the standalone overview CLI cannot
answer because it shows only the current snapshot.

Pattern J guard: ``record_snapshot`` short-circuits under
pytest. Tests that need to exercise persistence install an
autouse fixture that patches ``_is_test_environment``.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


_DEFAULT_PATH = Path("data") / "autonomy_overview_history.json"
_MAX_ENTRIES = 500


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


@dataclass
class OverviewHistoryEntry:
    captured_at: float
    store_id: str | None
    window_hours: float
    verdict: str
    armed_total: int
    fires_total: int
    fires_invoked: int
    fires_errors: int
    cooldown_blocked: int
    alerts_critical: int
    alerts_warn: int

    @classmethod
    def from_snapshot(cls, snap) -> "OverviewHistoryEntry":
        return cls(
            captured_at=snap.captured_at,
            store_id=snap.store_id,
            window_hours=snap.window_hours,
            verdict=snap.verdict,
            armed_total=snap.armed_total,
            fires_total=snap.fires_total,
            fires_invoked=snap.fires_invoked,
            fires_errors=snap.fires_errors,
            cooldown_blocked=snap.cooldown_blocked,
            alerts_critical=snap.alerts_critical,
            alerts_warn=snap.alerts_warn,
        )

    def to_dict(self) -> dict:
        return {
            "captured_at": self.captured_at,
            "store_id": self.store_id,
            "window_hours": self.window_hours,
            "verdict": self.verdict,
            "armed_total": self.armed_total,
            "fires_total": self.fires_total,
            "fires_invoked": self.fires_invoked,
            "fires_errors": self.fires_errors,
            "cooldown_blocked": self.cooldown_blocked,
            "alerts_critical": self.alerts_critical,
            "alerts_warn": self.alerts_warn,
        }


def _resolve_path(path: Path | None = None) -> Path:
    return path or _DEFAULT_PATH


def _read_raw(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "overview history read raised: %s", exc,
        )
    return []


def _write_raw(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bounded = entries[-_MAX_ENTRIES:]
    path.write_text(
        json.dumps(bounded, indent=2, default=str),
        encoding="utf-8",
    )


def record_snapshot(
    snap,
    *,
    path: Path | None = None,
) -> None:
    """Append snapshot to history (skips under pytest)."""
    if _is_test_environment():
        return
    p = _resolve_path(path)
    rows = _read_raw(p)
    entry = OverviewHistoryEntry.from_snapshot(snap)
    rows.append(entry.to_dict())
    _write_raw(p, rows)


def recent_entries(
    *,
    limit: int = 50,
    store_id: str | None = None,
    window_hours: float | None = None,
    path: Path | None = None,
) -> list[OverviewHistoryEntry]:
    """Return recent entries newest-first, optionally filtered."""
    p = _resolve_path(path)
    rows = _read_raw(p)
    out: list[OverviewHistoryEntry] = []
    cutoff = (
        time.time() - window_hours * 3600.0
        if window_hours else None
    )
    for row in reversed(rows):
        if store_id is not None:
            if row.get("store_id") != store_id:
                continue
        if cutoff is not None:
            if float(row.get("captured_at") or 0) < cutoff:
                continue
        try:
            out.append(OverviewHistoryEntry(
                captured_at=float(row.get(
                    "captured_at", 0,
                )),
                store_id=row.get("store_id"),
                window_hours=float(row.get(
                    "window_hours", 24.0,
                )),
                verdict=str(row.get("verdict", "")),
                armed_total=int(row.get("armed_total", 0)),
                fires_total=int(row.get("fires_total", 0)),
                fires_invoked=int(row.get(
                    "fires_invoked", 0,
                )),
                fires_errors=int(row.get("fires_errors", 0)),
                cooldown_blocked=int(row.get(
                    "cooldown_blocked", 0,
                )),
                alerts_critical=int(row.get(
                    "alerts_critical", 0,
                )),
                alerts_warn=int(row.get("alerts_warn", 0)),
            ))
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "skip malformed history row: %s", exc,
            )
            continue
        if len(out) >= limit:
            break
    return out


def verdict_transitions(
    *,
    store_id: str | None = None,
    path: Path | None = None,
) -> list[dict]:
    """Return verdict-change events (chronological).

    Each entry: {at, from, to, store_id}. The very first
    history row counts as a transition from None -> verdict.
    """
    p = _resolve_path(path)
    rows = _read_raw(p)
    out: list[dict] = []
    prev: str | None = None
    for row in rows:
        if store_id is not None:
            if row.get("store_id") != store_id:
                continue
        cur = str(row.get("verdict", ""))
        if cur != prev:
            out.append({
                "at": float(row.get("captured_at", 0)),
                "from": prev,
                "to": cur,
                "store_id": row.get("store_id"),
            })
            prev = cur
    return out


def history_size(*, path: Path | None = None) -> int:
    p = _resolve_path(path)
    return len(_read_raw(p))
