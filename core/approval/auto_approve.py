"""Auto-approve threshold for engines with proven outcome history.

The default approval contract is: every engine action requires a
human review before execute. That's the right default for engines
without track records, but for engines with hundreds of approvals
behind them and a consistently positive outcome ratio, the manual
click adds friction without insight gain.

This module implements operator-controlled auto-approve for engines
that opt in AND clear a set of outcome / confidence guardrails:

  1. The engine appears in the operator-managed allowlist
     (``auto_approve_config.json``). Default empty → safe default
     is no auto-approve.
  2. The engine has at least ``MIN_OUTCOMES_OBSERVED`` (default 20)
     matched outcomes. Prevents cold-start auto-approval where the
     ratio is statistically unreliable.
  3. The engine's outcome ratio (positive / (positive + negative))
     is ≥ ``MIN_OUTCOME_RATIO`` (default 0.85).
  4. The proposed action's confidence is ≥ ``MIN_CONFIDENCE``
     (default 0.85). Confidence-less actions never auto-approve.
  5. The engine's :class:`EngineHealth` verdict is NOT
     ``"unhealthy"``. Composite health scorer (alerts + quarantine
     + outcome + failure rate) refuses auto-approve when the
     engine is in degradation -- even if outcome_ratio LOOKED fine
     on the static window. Refuses ONLY on unhealthy; ``"warning"``
     still auto-approves (the warning verdict by itself doesn't
     constitute a degradation signal sharp enough to block). The
     guard is fail-open: if the health scorer raises, auto-approve
     proceeds based on the other four guards.

If all four pass, the dispatcher reports ``(True, reason)`` and the
queue auto-transitions PENDING → APPROVED with
``decided_by="auto_threshold"`` plus a human-readable reason. The
``decision_log`` table (PR #156) records the auto-decision so the
audit trail is complete — an operator can later inspect EVERY
auto-approval and reconstruct why.

Safe defaults:
  - Allowlist is empty by default. Auto-approve never fires until
    an operator explicitly opts in per engine via
    ``shopai approvals auto-config --enable <engine>``.
  - The four guardrails compose with AND — failing any one
    falls back to manual review.
  - Reading the config file fails open (return empty set) — a
    corrupt / missing file disables auto-approve, never enables it.
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

logger = get_logger("core.approval.auto_approve")

# Thresholds — chosen so a typical "proven" engine clears them
# comfortably but a noisy engine never does. Override via
# environment variables at startup if needed; runtime mutation
# is intentionally NOT supported (config drift across processes).
MIN_OUTCOMES_OBSERVED = int(
    os.environ.get("SHOPAI_AUTO_APPROVE_MIN_OUTCOMES", "20")
)
MIN_OUTCOME_RATIO = float(
    os.environ.get("SHOPAI_AUTO_APPROVE_MIN_RATIO", "0.85")
)
MIN_CONFIDENCE = float(
    os.environ.get("SHOPAI_AUTO_APPROVE_MIN_CONFIDENCE", "0.85")
)

_DEFAULT_CONFIG_PATH = Path("data") / "auto_approve_config.json"
# W962: RLock so mutators can wrap their full read-modify-write
# under the same lock save_config holds.
_LOCK = threading.RLock()


# ── Allowlist persistence ──────────────────────────────────────


@dataclass(frozen=True)
class AutoApproveConfig:
    """Engine-level opt-in for auto-approve. Allowlist is a set of
    engine namespaces; the rest fall through to manual review."""

    allowlist: frozenset[str]

    def is_enabled(self, engine: str) -> bool:
        return engine in self.allowlist


def _config_path() -> Path:
    """Resolve the config file path. Honors SHOPAI_DATA_DIR for
    tests + alt deployments; falls back to data/ at the project
    root (matches the rest of the persistence layer)."""
    data_dir = os.environ.get("SHOPAI_DATA_DIR")
    if data_dir:
        return Path(data_dir) / "auto_approve_config.json"
    return _DEFAULT_CONFIG_PATH


def load_config() -> AutoApproveConfig:
    """Read the persisted allowlist. Fails open (returns empty
    allowlist) on missing file or parse error — the safe default
    is no auto-approve."""
    path = _config_path()
    try:
        if not path.exists():
            return AutoApproveConfig(allowlist=frozenset())
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.debug(
            "auto_approve config read failed (%s); failing open: %s",
            path, exc,
        )
        return AutoApproveConfig(allowlist=frozenset())

    raw_list = data.get("allowlist", []) if isinstance(data, dict) else []
    if not isinstance(raw_list, list):
        return AutoApproveConfig(allowlist=frozenset())
    return AutoApproveConfig(
        allowlist=frozenset(
            str(e).strip() for e in raw_list if str(e).strip()
        ),
    )


def save_config(config: AutoApproveConfig) -> None:
    """Persist the allowlist. Atomic write via temp + rename so a
    crash mid-write can't leave a half-truncated config."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"allowlist": sorted(config.allowlist)}
    tmp = path.with_suffix(path.suffix + ".tmp")
    with _LOCK:
        tmp.write_text(
            json.dumps(payload, indent=2), encoding="utf-8",
        )
        tmp.replace(path)


def enable_engine(engine: str) -> AutoApproveConfig:
    engine = engine.strip()
    if not engine:
        raise ValueError("engine name must be non-empty")
    # W962: span load+modify+save so concurrent enable+disable
    # don't clobber each other's set diff.
    with _LOCK:
        cfg = load_config()
        new = AutoApproveConfig(
            allowlist=cfg.allowlist | {engine},
        )
        save_config(new)
    return new


def disable_engine(engine: str) -> AutoApproveConfig:
    engine = engine.strip()
    if not engine:
        raise ValueError("engine name must be non-empty")
    with _LOCK:
        cfg = load_config()
        new = AutoApproveConfig(
            allowlist=cfg.allowlist - {engine},
        )
        save_config(new)
    return new


# ── Evaluator ──────────────────────────────────────────────────


@dataclass(frozen=True)
class AutoApproveDecision:
    should_auto: bool
    reason: str
    # Snapshot of the inputs at decision time for the audit row.
    confidence: float | None
    outcome_ratio: float | None
    total_outcomes: int


def evaluate(
    *,
    engine: str,
    confidence: float | None,
    queue: "ApprovalQueue",
    config: AutoApproveConfig | None = None,
) -> AutoApproveDecision:
    """Decide whether ``engine``'s newly-enqueued action with the
    given ``confidence`` clears every auto-approve guardrail.

    Returns a decision plus a human-readable reason — the reason
    is what lands in the ``decision_log`` so a future audit can
    answer "why did this auto-approve?" without re-running the
    decision.

    A short-circuit at every guardrail keeps the cost low — most
    engines aren't in the allowlist so the function returns in a
    single dict lookup.
    """
    cfg = config if config is not None else load_config()

    if not cfg.is_enabled(engine):
        return AutoApproveDecision(
            should_auto=False,
            reason="engine_not_in_allowlist",
            confidence=confidence,
            outcome_ratio=None,
            total_outcomes=0,
        )

    if confidence is None:
        return AutoApproveDecision(
            should_auto=False,
            reason="confidence_missing",
            confidence=None,
            outcome_ratio=None,
            total_outcomes=0,
        )

    try:
        conf = float(confidence)
    except (TypeError, ValueError):
        return AutoApproveDecision(
            should_auto=False,
            reason="confidence_not_numeric",
            confidence=None,
            outcome_ratio=None,
            total_outcomes=0,
        )

    if conf < MIN_CONFIDENCE:
        return AutoApproveDecision(
            should_auto=False,
            reason=(
                f"confidence_below_threshold "
                f"({conf:.2f} < {MIN_CONFIDENCE:.2f})"
            ),
            confidence=conf,
            outcome_ratio=None,
            total_outcomes=0,
        )

    try:
        stats = queue.engine_outcome_stats(engine)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "engine_outcome_stats raised for %s: %s", engine, exc,
        )
        return AutoApproveDecision(
            should_auto=False,
            reason="outcome_stats_unavailable",
            confidence=conf,
            outcome_ratio=None,
            total_outcomes=0,
        )

    positive = int(stats.get("positive_count", 0) or 0)
    negative = int(stats.get("negative_count", 0) or 0)
    polarised = positive + negative
    total = int(stats.get("total_outcomes", 0) or 0)

    if polarised < MIN_OUTCOMES_OBSERVED:
        return AutoApproveDecision(
            should_auto=False,
            reason=(
                f"insufficient_history "
                f"({polarised} < {MIN_OUTCOMES_OBSERVED})"
            ),
            confidence=conf,
            outcome_ratio=None,
            total_outcomes=total,
        )

    ratio = positive / polarised if polarised else 0.0
    if ratio < MIN_OUTCOME_RATIO:
        return AutoApproveDecision(
            should_auto=False,
            reason=(
                f"outcome_ratio_below_threshold "
                f"({ratio:.2f} < {MIN_OUTCOME_RATIO:.2f})"
            ),
            confidence=conf,
            outcome_ratio=ratio,
            total_outcomes=total,
        )

    # Guardrail #5: composite engine_health verdict. Refuses
    # auto-approve when the engine is unhealthy by the combined
    # signals (alerts + quarantine + failure rate). Fail-open:
    # a health scorer that raises is treated as silent skip.
    if _engine_unhealthy(engine, queue=queue):
        return AutoApproveDecision(
            should_auto=False,
            reason="engine_health_unhealthy",
            confidence=conf,
            outcome_ratio=ratio,
            total_outcomes=total,
        )

    return AutoApproveDecision(
        should_auto=True,
        reason=(
            f"auto_threshold: confidence={conf:.2f} "
            f"outcome_ratio={ratio:.2f} "
            f"history={polarised}"
        ),
        confidence=conf,
        outcome_ratio=ratio,
        total_outcomes=total,
    )


def _engine_unhealthy(
    engine: str, *, queue: "ApprovalQueue",
) -> bool:
    """Returns True when the engine's composite health verdict is
    ``"unhealthy"``. Fail-open: any error degrades to False so the
    health guard never blocks more than the other four guards
    already would in its absence.
    """
    try:
        from core.approval.engine_health import score_engine
        health = score_engine(engine, queue=queue)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "auto_approve: engine_health probe raised for %s: %s",
            engine, exc,
        )
        return False
    return health.verdict == "unhealthy"


def _is_test_environment() -> bool:
    """Pattern J gate — auto-approve must NEVER fire from under
    pytest, even if a test seeded an allowlist + outcomes. Tests
    that exercise the evaluator directly call ``evaluate(...)``
    with an explicit config; tests that exercise the queue
    integration patch this function to return ``False``."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def maybe_auto_approve(
    *,
    queue: "ApprovalQueue",
    action_id: str,
    engine: str,
    confidence: float | None,
) -> AutoApproveDecision:
    """Evaluate + (if approved) immediately transition the just-
    enqueued action. Returns the decision so callers can surface
    the auto-decision in their response payload.

    Called from ``ApprovalQueue.enqueue`` AFTER the row is
    persisted — so the auto-transition uses the same code path
    as any operator approval, with the same hook fan-out and
    decision_log row.
    """
    if _is_test_environment():
        return AutoApproveDecision(
            should_auto=False,
            reason="pytest_guard",
            confidence=None,
            outcome_ratio=None,
            total_outcomes=0,
        )

    decision = evaluate(
        engine=engine, confidence=confidence, queue=queue,
    )
    if decision.should_auto:
        try:
            queue.approve(
                action_id,
                decided_by="auto_threshold",
                reason=decision.reason,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "auto-approve transition failed for %s: %s",
                action_id, exc,
            )
    return decision


# ── Candidate finder ───────────────────────────────────────────


@dataclass(frozen=True)
class CandidateEngine:
    """One engine that would pass the outcome-based guardrails
    if added to the allowlist. ``confidence`` isn't checked here —
    it's a per-action property, not per-engine. The CLI surfaces
    this as a recommendation; operators inspecting it decide
    whether to opt in based on the supporting numbers."""

    engine: str
    outcome_ratio: float
    positive: int
    negative: int
    total_polarised: int


def find_candidates(
    queue: "ApprovalQueue",
    *,
    config: AutoApproveConfig | None = None,
) -> list[CandidateEngine]:
    """Scan every engine with outcome history and return the ones
    that would pass the OUTCOME-based guardrails (history + ratio)
    if added to the allowlist. Already-allowlisted engines are
    excluded — the recommendation surface is for adoption, not
    for inventorying current state.

    Returns newest-track-record-first (highest history count) so
    operators see the most-data engines first. Within the same
    history bucket the highest outcome_ratio sorts first.
    """
    cfg = config if config is not None else load_config()
    out: list[CandidateEngine] = []

    try:
        per_engine = queue.all_engine_outcome_stats()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "all_engine_outcome_stats raised: %s", exc,
        )
        return out

    for engine, stats in per_engine.items():
        if cfg.is_enabled(engine):
            continue
        positive = int(stats.get("positive_count", 0) or 0)
        negative = int(stats.get("negative_count", 0) or 0)
        polarised = positive + negative
        if polarised < MIN_OUTCOMES_OBSERVED:
            continue
        ratio = positive / polarised
        if ratio < MIN_OUTCOME_RATIO:
            continue
        out.append(CandidateEngine(
            engine=engine,
            outcome_ratio=round(ratio, 4),
            positive=positive,
            negative=negative,
            total_polarised=polarised,
        ))

    out.sort(
        key=lambda c: (c.total_polarised, c.outcome_ratio),
        reverse=True,
    )
    return out
