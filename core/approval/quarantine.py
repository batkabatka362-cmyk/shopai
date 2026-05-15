"""Failed-engine quarantine — auto-pause engines producing
predominantly negative outcomes.

This is the complement to PR #161's auto-approve threshold.
Auto-approve protects throughput on engines whose recent
outcomes are mostly positive; quarantine protects the merchant
when an engine starts producing mostly negative outcomes
(refunds, complaints, returns).

Two-state machine:
  - **Healthy**: engine's recent outcomes pass the guardrails;
    new enqueues land PENDING (default) or APPROVED (if the
    engine is also on the auto-approve allowlist).
  - **Quarantined**: engine's recent outcomes fail the
    guardrails; new enqueues are immediately REJECTED with
    ``decided_by="auto_quarantine"`` and a reason. The engine
    stays quarantined until an operator explicitly clears it
    via ``shopai approvals quarantine --release <engine>``.

Guardrails (all checked at enqueue time):
  1. At least ``MIN_OUTCOMES_OBSERVED`` (default 20) polarised
     outcomes — same statistical floor as auto-approve. No
     premature quarantine on noise.
  2. Outcome ratio (positive / polarised) is BELOW
     ``MAX_NEGATIVE_RATIO`` (default 0.50 — i.e. quarantine
     fires when ≥ 50% of recent outcomes are negative).
  3. Engine is NOT in the operator-managed exemption list
     (``data/quarantine_exemptions.json``). Some engines
     legitimately have higher negative ratios (e.g. a returns
     engine where "refund issued" is a positive outcome but
     polarity tagging marks it negative) — operators can
     exempt those.

Manual override path: ``release_engine(name)`` adds the engine
to a release list so quarantine logic is bypassed until the
engine's recent history rolls forward enough to re-trigger.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from utils.logger import get_logger

if TYPE_CHECKING:
    from core.approval.queue import ApprovalQueue

logger = get_logger("core.approval.quarantine")

# Thresholds (same env-var pattern as auto_approve.py)
MIN_OUTCOMES_OBSERVED = int(
    os.environ.get("SHOPAI_QUARANTINE_MIN_OUTCOMES", "20")
)
MAX_NEGATIVE_RATIO = float(
    os.environ.get("SHOPAI_QUARANTINE_MAX_NEG_RATIO", "0.50")
)

_DEFAULT_STATE_PATH = Path("data") / "quarantine_state.json"
_LOCK = threading.Lock()


@dataclass(frozen=True)
class QuarantineState:
    """Persisted quarantine state.

    - ``exemptions``: engines the operator has flagged as never-
      quarantine (legit-negative-polarity cases). Permanent
      until removed.
    - ``released``: engines the operator has explicitly cleared
      after a quarantine event. Bypasses re-quarantine until
      the operator removes them from the list. Engines on this
      list still get all normal flow — release is a manual
      override, not a permanent immunity.
    """

    exemptions: frozenset[str]
    released: frozenset[str]

    def is_exempt(self, engine: str) -> bool:
        return engine in self.exemptions

    def is_released(self, engine: str) -> bool:
        return engine in self.released


def _state_path() -> Path:
    data_dir = os.environ.get("SHOPAI_DATA_DIR")
    if data_dir:
        return Path(data_dir) / "quarantine_state.json"
    return _DEFAULT_STATE_PATH


def load_state() -> QuarantineState:
    """Fails open: missing / corrupt file returns empty state
    (no exemptions, no releases). Quarantine still works because
    its guardrails are derived from queue stats, not the file."""
    path = _state_path()
    try:
        if not path.exists():
            return QuarantineState(
                exemptions=frozenset(), released=frozenset(),
            )
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.debug(
            "quarantine state read failed (%s); failing open: %s",
            path, exc,
        )
        return QuarantineState(
            exemptions=frozenset(), released=frozenset(),
        )
    if not isinstance(data, dict):
        return QuarantineState(
            exemptions=frozenset(), released=frozenset(),
        )
    return QuarantineState(
        exemptions=frozenset(
            str(e).strip()
            for e in data.get("exemptions", []) or []
            if str(e).strip()
        ),
        released=frozenset(
            str(e).strip()
            for e in data.get("released", []) or []
            if str(e).strip()
        ),
    )


def save_state(state: QuarantineState) -> None:
    """Atomic write via temp + rename."""
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "exemptions": sorted(state.exemptions),
        "released": sorted(state.released),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    with _LOCK:
        tmp.write_text(
            json.dumps(payload, indent=2), encoding="utf-8",
        )
        tmp.replace(path)


def exempt_engine(engine: str) -> QuarantineState:
    """Permanently mark an engine as exempt from quarantine."""
    engine = engine.strip()
    if not engine:
        raise ValueError("engine name must be non-empty")
    s = load_state()
    new = QuarantineState(
        exemptions=s.exemptions | {engine},
        released=s.released,
    )
    save_state(new)
    return new


def unexempt_engine(engine: str) -> QuarantineState:
    engine = engine.strip()
    if not engine:
        raise ValueError("engine name must be non-empty")
    s = load_state()
    new = QuarantineState(
        exemptions=s.exemptions - {engine},
        released=s.released,
    )
    save_state(new)
    return new


def release_engine(engine: str) -> QuarantineState:
    """Manually release a quarantined engine. The engine joins
    the released list; new enqueues bypass the quarantine check.
    Operator can clear the release later if quarantine should
    re-engage."""
    engine = engine.strip()
    if not engine:
        raise ValueError("engine name must be non-empty")
    s = load_state()
    new = QuarantineState(
        exemptions=s.exemptions,
        released=s.released | {engine},
    )
    save_state(new)
    return new


def clear_release(engine: str) -> QuarantineState:
    engine = engine.strip()
    if not engine:
        raise ValueError("engine name must be non-empty")
    s = load_state()
    new = QuarantineState(
        exemptions=s.exemptions,
        released=s.released - {engine},
    )
    save_state(new)
    return new


# ── Evaluator ──────────────────────────────────────────────────


@dataclass(frozen=True)
class QuarantineDecision:
    should_quarantine: bool
    reason: str
    negative_ratio: float | None
    total_polarised: int


def evaluate(
    *,
    engine: str,
    queue: "ApprovalQueue",
    state: QuarantineState | None = None,
) -> QuarantineDecision:
    """Decide whether ``engine`` should currently be quarantined.

    Returns a decision plus a human-readable reason. The reason
    lands in the ``decision_log`` so a future audit can answer
    "why was this auto-rejected?" without re-running the
    decision.
    """
    s = state if state is not None else load_state()

    if s.is_exempt(engine):
        return QuarantineDecision(
            should_quarantine=False,
            reason="engine_exempt",
            negative_ratio=None,
            total_polarised=0,
        )

    if s.is_released(engine):
        return QuarantineDecision(
            should_quarantine=False,
            reason="engine_released_by_operator",
            negative_ratio=None,
            total_polarised=0,
        )

    try:
        stats = queue.engine_outcome_stats(engine)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "engine_outcome_stats raised for %s: %s", engine, exc,
        )
        return QuarantineDecision(
            should_quarantine=False,
            reason="outcome_stats_unavailable",
            negative_ratio=None,
            total_polarised=0,
        )

    positive = int(stats.get("positive_count", 0) or 0)
    negative = int(stats.get("negative_count", 0) or 0)
    polarised = positive + negative

    if polarised < MIN_OUTCOMES_OBSERVED:
        return QuarantineDecision(
            should_quarantine=False,
            reason=(
                f"insufficient_history "
                f"({polarised} < {MIN_OUTCOMES_OBSERVED})"
            ),
            negative_ratio=None,
            total_polarised=polarised,
        )

    negative_ratio = negative / polarised
    if negative_ratio < MAX_NEGATIVE_RATIO:
        return QuarantineDecision(
            should_quarantine=False,
            reason=(
                f"healthy "
                f"(negative_ratio={negative_ratio:.2f} < "
                f"{MAX_NEGATIVE_RATIO:.2f})"
            ),
            negative_ratio=negative_ratio,
            total_polarised=polarised,
        )

    return QuarantineDecision(
        should_quarantine=True,
        reason=(
            f"auto_quarantine: negative_ratio="
            f"{negative_ratio:.2f} >= {MAX_NEGATIVE_RATIO:.2f} "
            f"history={polarised}"
        ),
        negative_ratio=negative_ratio,
        total_polarised=polarised,
    )


def _is_test_environment() -> bool:
    """Pattern J gate — quarantine must NEVER fire from under
    pytest, even with seeded outcomes. Tests that exercise the
    integration patch this function."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def maybe_quarantine(
    *,
    queue: "ApprovalQueue",
    action_id: str,
    engine: str,
) -> QuarantineDecision:
    """Evaluate + (if positive) immediately auto-reject the just-
    enqueued action with ``decided_by="auto_quarantine"``.

    Called from ``ApprovalQueue.enqueue`` AFTER the row is
    persisted and AFTER the auto-approve check. The order matters:
    auto-approve is the throughput happy path; quarantine is the
    safety net. An engine cannot be on both the auto-approve
    allowlist and quarantined at the same time without operator
    intervention — but if it somehow is, quarantine evaluates
    the not-yet-transitioned PENDING action because auto-approve's
    success short-circuits its caller's later logic.
    """
    if _is_test_environment():
        return QuarantineDecision(
            should_quarantine=False,
            reason="pytest_guard",
            negative_ratio=None,
            total_polarised=0,
        )

    decision = evaluate(engine=engine, queue=queue)
    if decision.should_quarantine:
        try:
            queue.reject(
                action_id,
                decided_by="auto_quarantine",
                reason=decision.reason,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "auto-quarantine transition failed for %s: %s",
                action_id, exc,
            )
    return decision
