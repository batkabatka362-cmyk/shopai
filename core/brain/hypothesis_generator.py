"""Hypothesis generator — auto-create falsifiable hypotheses.

hypothesis.py registers hypotheses and scores them, but it relies on
a human or another subsystem to *think up* the hypothesis. This
module closes that loop: given a stream of anomalies (drift alerts,
pre-breach alerts, violated assumptions, concept signatures), it
proposes testable hypotheses with:

  • subject       — what we're claiming about
  • kpi           — the observable
  • direction     — "above" | "below" | "same"
  • magnitude     — the expected effect size
  • horizon_days  — when to resolve
  • rationale     — one-sentence why

Generated hypotheses are deduped by signature so a drift alert that
keeps firing does not spam the log. Callers submit each hypothesis
to ``hypothesis.predict(...)`` for formal tracking.

Templates are registered via ``register_template`` so new signal
shapes produce new candidate hypotheses without touching the engine
core. Pure stdlib, deterministic.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.hypothesis_generator")


Direction = Literal["above", "below", "same"]
Kind = Literal[
    "drift", "assumption_violation", "pre_breach",
    "concept_cluster", "anomaly",
]


@dataclass
class GeneratedHypothesis:
    id: str
    signature: str          # dedupe key
    kind: Kind
    subject: str
    kpi: str
    direction: Direction
    magnitude: float
    horizon_days: float
    rationale: str
    confidence: float
    source_refs: tuple[str, ...]
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "signature": self.signature,
            "kind": self.kind,
            "subject": self.subject,
            "kpi": self.kpi,
            "direction": self.direction,
            "magnitude": round(self.magnitude, 4),
            "horizon_days": round(self.horizon_days, 2),
            "rationale": self.rationale,
            "confidence": round(self.confidence, 4),
            "source_refs": list(self.source_refs),
            "ts": self.ts,
        }


@dataclass
class HypothesisTemplate:
    id: str
    kind: Kind
    trigger: Callable[[dict[str, Any]], bool]
    builder: Callable[[dict[str, Any]], GeneratedHypothesis | None]
    description: str = ""


def _drift_trigger(event: dict[str, Any]) -> bool:
    return (
        event.get("kind") == "drift"
        and float(event.get("drift_score", 0.0)) >= 2.0
    )


def _drift_builder(
    event: dict[str, Any],
) -> GeneratedHypothesis | None:
    pid = str(event.get("predictor_id", ""))
    bias = float(event.get("bias", 0.0))
    if not pid:
        return None
    direction: Direction = "above" if bias > 0 else "below"
    magnitude = abs(bias)
    sig = f"drift:{pid}:{direction}"
    return GeneratedHypothesis(
        id=uuid.uuid4().hex,
        signature=sig,
        kind="drift",
        subject=pid,
        kpi=pid,
        direction=direction,
        magnitude=magnitude,
        horizon_days=3.0,
        rationale=(
            f"{pid} drifting {direction} by {bias:+.3f}; "
            "if bias persists, stale intercept"
        ),
        confidence=min(
            1.0, 0.3 + float(event.get("drift_score", 0.0)) / 10.0,
        ),
        source_refs=(f"world_model_updater:{pid}",),
        ts=time.time(),
    )


def _assumption_trigger(event: dict[str, Any]) -> bool:
    return (
        event.get("kind") == "assumption_violation"
        and bool(event.get("kpi"))
    )


def _assumption_builder(
    event: dict[str, Any],
) -> GeneratedHypothesis | None:
    kpi = str(event.get("kpi", ""))
    expected = float(event.get("expected_value", 0.0))
    observed = float(event.get("observed_value", 0.0))
    if not kpi:
        return None
    direction: Direction = "above" if observed > expected else "below"
    magnitude = abs(observed - expected)
    sig = f"assume:{kpi}:{direction}"
    return GeneratedHypothesis(
        id=uuid.uuid4().hex,
        signature=sig,
        kind="assumption_violation",
        subject=kpi,
        kpi=kpi,
        direction=direction,
        magnitude=magnitude,
        horizon_days=5.0,
        rationale=(
            f"Expected {kpi}≈{expected:.3f} but saw {observed:.3f}; "
            "test whether shift is persistent"
        ),
        confidence=0.6,
        source_refs=(
            f"assumption_ledger:{event.get('assumption_id', '')}",
        ),
        ts=time.time(),
    )


def _pre_breach_trigger(event: dict[str, Any]) -> bool:
    sev = event.get("kind") == "pre_breach" and (
        event.get("severity") in ("warning", "critical")
    )
    return bool(sev)


def _pre_breach_builder(
    event: dict[str, Any],
) -> GeneratedHypothesis | None:
    kpi = str(event.get("kpi", ""))
    if not kpi:
        return None
    direction = event.get("direction", "below")
    if direction not in ("above", "below", "same"):
        direction = "below"
    sig = f"pre_breach:{kpi}:{direction}"
    horizon = 1.0 if event.get("severity") == "critical" else 3.0
    return GeneratedHypothesis(
        id=uuid.uuid4().hex,
        signature=sig,
        kind="pre_breach",
        subject=kpi,
        kpi=kpi,
        direction=direction,
        magnitude=abs(float(event.get("slope", 0.01))),
        horizon_days=horizon,
        rationale=(
            f"{kpi} trajectory crosses threshold soon — "
            "test whether intervention reverses"
        ),
        confidence=float(event.get("confidence", 0.5)),
        source_refs=("predictive_alerter:" + kpi,),
        ts=time.time(),
    )


_DEFAULT_TEMPLATES: tuple[HypothesisTemplate, ...] = (
    HypothesisTemplate(
        id="drift_template",
        kind="drift",
        trigger=_drift_trigger,
        builder=_drift_builder,
        description="World-model drift → corrective hypothesis",
    ),
    HypothesisTemplate(
        id="assumption_template",
        kind="assumption_violation",
        trigger=_assumption_trigger,
        builder=_assumption_builder,
        description="Violated assumption → retest hypothesis",
    ),
    HypothesisTemplate(
        id="pre_breach_template",
        kind="pre_breach",
        trigger=_pre_breach_trigger,
        builder=_pre_breach_builder,
        description="Pre-breach alert → reversal hypothesis",
    ),
)


class HypothesisGenerator:
    def __init__(
        self,
        *,
        templates: Iterable[HypothesisTemplate] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._templates: list[HypothesisTemplate] = list(
            templates if templates is not None
            else _DEFAULT_TEMPLATES,
        )
        self._recent: dict[str, GeneratedHypothesis] = {}
        # signature → latest hypothesis for dedupe

    def register_template(self, tpl: HypothesisTemplate) -> None:
        with self._lock:
            self._templates.append(tpl)

    def unregister_template(self, template_id: str) -> bool:
        with self._lock:
            before = len(self._templates)
            self._templates = [
                t for t in self._templates if t.id != template_id
            ]
            return len(self._templates) < before

    # ── Generate ─────────────────────────────────────────

    def generate(
        self,
        event: dict[str, Any],
    ) -> GeneratedHypothesis | None:
        if not event or not event.get("kind"):
            return None
        with self._lock:
            templates = list(self._templates)
        for tpl in templates:
            try:
                if not tpl.trigger(event):
                    continue
                h = tpl.builder(event)
                if h is None:
                    continue
            except Exception as exc:
                logger.debug(
                    "template %s failed: %s", tpl.id, exc,
                )
                continue
            with self._lock:
                existing = self._recent.get(h.signature)
                if existing is not None:
                    # Don't duplicate; refresh ts on existing
                    existing.ts = h.ts
                    existing.confidence = max(
                        existing.confidence, h.confidence,
                    )
                    return existing
                self._recent[h.signature] = h
            return h
        return None

    def generate_batch(
        self, events: Iterable[dict[str, Any]],
    ) -> list[GeneratedHypothesis]:
        out: list[GeneratedHypothesis] = []
        for ev in events:
            h = self.generate(ev)
            if h is not None:
                out.append(h)
        return out

    # ── Queries ──────────────────────────────────────────

    def recent(
        self, *, limit: int = 20,
    ) -> list[GeneratedHypothesis]:
        with self._lock:
            rs = list(self._recent.values())
        rs.sort(key=lambda h: -h.ts)
        return rs[: max(1, int(limit))]

    def by_kind(self, kind: Kind) -> list[GeneratedHypothesis]:
        with self._lock:
            out = [
                h for h in self._recent.values() if h.kind == kind
            ]
        out.sort(key=lambda h: -h.confidence)
        return out

    def stats(self) -> dict[str, Any]:
        with self._lock:
            by_kind: dict[str, int] = {}
            for h in self._recent.values():
                by_kind[h.kind] = by_kind.get(h.kind, 0) + 1
            return {
                "templates": len(self._templates),
                "tracked": len(self._recent),
                "by_kind": by_kind,
                "template_ids": sorted(
                    t.id for t in self._templates
                ),
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._recent)
            self._recent.clear()
        return n
