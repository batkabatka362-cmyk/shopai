"""Insight synthesiser — distil observations into 1-line learnings.

The brain hoards observations: calibration reports, drift alerts,
validated/violated assumptions, funnel snapshots, pre-breach alerts.
Owners scrolling a dashboard see metrics but not *takeaways*. The
synthesiser compresses the current cycle's evidence into a short list
of ``Insight`` objects — each a one-sentence claim with:

  • kind         — "calibration" / "drift" / "assumption" / "funnel"
                   / "pre_breach"
  • statement    — the claim, human-readable
  • confidence   — 0..1 (how much evidence)
  • supporting   — list of keys/ids pointing to source data
  • severity     — "info" / "warning" / "critical"

Insights are prioritised (critical > warning > info, then confidence
descending) so owners see the top N that matter most. Callers can
pin an insight for the Obsidian vault, or mark dismissed so it
doesn't repeat.

Pure stdlib, deterministic. Complements weekly_digest (which renders
a full narrative) by being realtime + punchy.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.insight_synthesizer")


Kind = Literal[
    "calibration", "drift", "assumption", "funnel",
    "pre_breach", "imitation", "owner",
]
Severity = Literal["info", "warning", "critical"]


@dataclass
class Insight:
    id: str
    kind: Kind
    statement: str
    confidence: float
    severity: Severity
    supporting: tuple[str, ...]
    ts: float
    pinned: bool = False
    dismissed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "statement": self.statement,
            "confidence": round(self.confidence, 4),
            "severity": self.severity,
            "supporting": list(self.supporting),
            "ts": self.ts,
            "pinned": self.pinned,
            "dismissed": self.dismissed,
        }


_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}


def _calibration_insights(
    report: dict[str, Any] | None,
) -> list[Insight]:
    if not report or not report.get("n_total", 0):
        return []
    err = float(report.get("calibration_error", 0.0))
    over = float(report.get("overconfidence_score", 0.0))
    n = int(report["n_total"])
    out: list[Insight] = []
    if err > 0.2:
        out.append(Insight(
            id=uuid.uuid4().hex,
            kind="calibration",
            statement=(
                f"Confidence calibration drifts by {err:.2f}; "
                f"{'over' if over > 0 else 'under'}confident across "
                f"{n} decisions"
            ),
            confidence=min(1.0, 0.4 + err),
            severity="warning" if err < 0.4 else "critical",
            supporting=("meta_reasoner",),
            ts=time.time(),
        ))
    return out


def _drift_insights(
    alerts: list[dict[str, Any]] | None,
) -> list[Insight]:
    out: list[Insight] = []
    for a in alerts or []:
        out.append(Insight(
            id=uuid.uuid4().hex,
            kind="drift",
            statement=(
                f"Predictor {a.get('predictor_id')} drifting: "
                f"{a.get('suggestion', '')}"
            ),
            confidence=0.7,
            severity="warning",
            supporting=("world_model_updater",),
            ts=time.time(),
        ))
    return out


def _assumption_insights(
    stats: dict[str, Any] | None,
) -> list[Insight]:
    if not stats or stats.get("total", 0) == 0:
        return []
    vrate = float(stats.get("violation_rate", 0.0))
    if vrate <= 0.3:
        return []
    sev: Severity = "critical" if vrate > 0.6 else "warning"
    return [Insight(
        id=uuid.uuid4().hex,
        kind="assumption",
        statement=(
            f"{vrate:.0%} of resolved assumptions were violated — "
            "revisit base beliefs"
        ),
        confidence=min(1.0, 0.3 + vrate),
        severity=sev,
        supporting=("assumption_ledger",),
        ts=time.time(),
    )]


def _funnel_insights(
    snapshot: dict[str, Any] | None,
) -> list[Insight]:
    if not snapshot:
        return []
    leak = snapshot.get("biggest_leak")
    diag = snapshot.get("biggest_leak_diagnosis", "")
    conv = float(snapshot.get("overall_conversion", 0.0))
    if not leak:
        return []
    sev: Severity = "warning" if conv < 0.01 else "info"
    return [Insight(
        id=uuid.uuid4().hex,
        kind="funnel",
        statement=(
            f"Biggest leak: {leak[0]}→{leak[1]} ({diag})"
        ),
        confidence=0.8,
        severity=sev,
        supporting=("revenue_funnel",),
        ts=time.time(),
    )]


def _pre_breach_insights(
    alerts: list[dict[str, Any]] | None,
) -> list[Insight]:
    out: list[Insight] = []
    for a in alerts or []:
        sev = a.get("severity", "info")
        if sev == "none":
            continue
        if sev not in ("info", "warning", "critical"):
            continue
        secs = a.get("projected_breach_s")
        hint = (
            f"breach in {secs/3600:.1f}h"
            if isinstance(secs, (int, float)) and secs > 0
            else "already breaching"
        )
        out.append(Insight(
            id=uuid.uuid4().hex,
            kind="pre_breach",
            statement=(
                f"KPI {a.get('kpi', '?')} trending "
                f"{a.get('direction', '?')} threshold; {hint}"
            ),
            confidence=float(a.get("confidence", 0.5)),
            severity=sev,
            supporting=("predictive_alerter",),
            ts=time.time(),
        ))
    return out


class InsightSynthesizer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._insights: dict[str, Insight] = {}

    # ── Synthesise ───────────────────────────────────────

    def synthesise(
        self,
        *,
        calibration_report: dict[str, Any] | None = None,
        drift_alerts: list[dict[str, Any]] | None = None,
        assumption_stats: dict[str, Any] | None = None,
        funnel_snapshot: dict[str, Any] | None = None,
        pre_breach_alerts: list[dict[str, Any]] | None = None,
    ) -> list[Insight]:
        produced: list[Insight] = []
        produced.extend(
            _calibration_insights(calibration_report),
        )
        produced.extend(_drift_insights(drift_alerts))
        produced.extend(_assumption_insights(assumption_stats))
        produced.extend(_funnel_insights(funnel_snapshot))
        produced.extend(_pre_breach_insights(pre_breach_alerts))
        with self._lock:
            for i in produced:
                self._insights[i.id] = i
        produced.sort(
            key=lambda i: (
                _SEVERITY_RANK[i.severity],
                -i.confidence, i.ts,
            ),
        )
        return produced

    # ── Lifecycle ────────────────────────────────────────

    def pin(self, insight_id: str) -> Insight:
        with self._lock:
            i = self._insights.get(insight_id)
            if i is None:
                raise ValueError(
                    f"unknown insight {insight_id!r}",
                )
            i.pinned = True
            return i

    def dismiss(self, insight_id: str) -> Insight:
        with self._lock:
            i = self._insights.get(insight_id)
            if i is None:
                raise ValueError(
                    f"unknown insight {insight_id!r}",
                )
            i.dismissed = True
            return i

    # ── Queries ──────────────────────────────────────────

    def active(
        self, *, limit: int | None = None,
    ) -> list[Insight]:
        with self._lock:
            active = [
                i for i in self._insights.values()
                if not i.dismissed
            ]
        active.sort(
            key=lambda i: (
                0 if i.pinned else 1,
                _SEVERITY_RANK[i.severity],
                -i.confidence,
            ),
        )
        if limit is not None:
            active = active[: max(1, int(limit))]
        return active

    def pinned(self) -> list[Insight]:
        with self._lock:
            return [
                i for i in self._insights.values()
                if i.pinned and not i.dismissed
            ]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            by_sev: dict[str, int] = {}
            by_kind: dict[str, int] = {}
            for i in self._insights.values():
                if i.dismissed:
                    continue
                by_sev[i.severity] = by_sev.get(i.severity, 0) + 1
                by_kind[i.kind] = by_kind.get(i.kind, 0) + 1
            return {
                "total": len(self._insights),
                "active": sum(
                    1 for i in self._insights.values()
                    if not i.dismissed
                ),
                "pinned": sum(
                    1 for i in self._insights.values()
                    if i.pinned and not i.dismissed
                ),
                "by_severity": by_sev,
                "by_kind": by_kind,
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._insights)
            self._insights.clear()
        return n
