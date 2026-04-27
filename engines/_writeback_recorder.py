"""Phase 8 — record writeback action+result to the autonomous learning loop.

Phase 6 (engine writebacks) and Phase 7 (more writebacks) wire engine
outputs to actual Shopify mutations via the SmartRouter. But those
writes bypass ``execution/smart_executor.py``, so the autonomous
loop's feedback systems (MemoryIntelligence, DataArchitecture,
LearningLoop) never see what happened. The system can mint a 10%
loyalty code but won't learn whether that code drove redemptions.

This module is the bridge. Each writer (``mint_loyalty_code``,
``apply_tags``, ``archive_declining_products``, etc.) calls
``record_writeback(...)`` AFTER its router.execute call, passing
the action shape and the success/error result. The recorder then:

  * Creates a categorized decision memory (via
    ``MemoryIntelligence.create_from_decision``).
  * Records the action+result in the 12-domain DataArchitecture
    (via ``record_action`` + ``attach_result``).
  * Feeds the LearningLoop with metrics for pattern detection.
  * Records failures specifically when score is low — the failure
    intelligence pipeline auto-generates avoidance rules after 3+
    similar failures.

Graceful: every one of these systems is optional. If MemoryIntelligence
is unavailable (import fails / DB locked), that record is skipped.
The writeback itself already happened on Shopify — recording failures
must not propagate up. The ONLY failure mode is silent (logged at
debug); no exception escapes ``record_writeback``.

Score computation mirrors ``SmartExecutor._score_outcome`` for
consistency: base 3.0, +1.0 for success, -1.5 for error, ±0.5 for
revenue impact metric (when supplied), +0.3 if marked profitable,
clamped [1.0, 5.0].
"""
from __future__ import annotations

import os
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("engines.writeback_recorder")


# Test-environment guard. Under pytest, every recorder call would
# fan out to MemoryIntelligence + DataArchitecture + LearningLoop
# and write rows to the real on-disk SQLite databases — including
# the synthetic ``adapter_failed: scope_missing`` and
# ``adapter_raised: network_down`` failures that unit tests
# inject. Those entries then fed the failure-intelligence pipeline
# and produced bogus avoidance rules.
#
# pytest sets ``PYTEST_CURRENT_TEST`` automatically for every test
# (and clears it between tests). When that env var is present, the
# recorder no-ops — preserving the production behaviour, gating
# test pollution, and not requiring a per-test monkeypatch.
def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def record_writeback(
    *,
    engine: str,
    action_type: str,
    capability: str,
    params: dict[str, Any],
    success: bool,
    error: str | None = None,
    metrics: dict[str, Any] | None = None,
) -> None:
    """Record a Phase 6/7 writeback to the autonomous learning systems.

    Args:
        engine: The engine name that issued the writeback
            (e.g. ``"loyalty"``, ``"discount_strategy"``).
            Used as the memory category and namespace.
        action_type: Specific action label
            (e.g. ``"mint_loyalty_code"``, ``"apply_tags"``,
            ``"archive_declining_product"``). Used for memory
            tagging and the action→result join key.
        capability: The Shopify capability invoked
            (e.g. ``"SHOPIFY_CREATE_DISCOUNT"``). Stored as
            metadata so audits can trace which adapter handled
            this action.
        params: The friendly-form params passed to the adapter.
            Stored as the action's input_data — gives future
            sessions visibility into what the engine asked for.
        success: Did the writeback succeed?
            (Result of ``router.execute(...).ok``.)
        error: Error string if not successful (or None).
        metrics: Optional impact metrics for scoring (e.g.
            ``{"revenue_change_pct": 5.2}``, ``{"profitable":
            True}``). Without metrics the score is just based on
            success/failure; with metrics the score reflects
            measured outcome.

    Returns:
        ``None``. Recording failures don't propagate; the writeback
        already happened on Shopify and the engine pipeline must
        keep running.
    """
    if _is_test_environment():
        return

    score = _compute_score(success=success, metrics=metrics)
    result_data: dict[str, Any] = {
        "success": bool(success),
        "capability": capability,
        "engine": engine,
    }
    if error is not None:
        result_data["error"] = str(error)
    if metrics:
        result_data.update({k: v for k, v in metrics.items()})

    action_data: dict[str, Any] = {
        "engine": engine,
        "capability": capability,
        "params": params,
    }

    # ---- MemoryIntelligence ------------------------------------
    _record_in_memory_intel(
        category=engine,
        action_type=action_type,
        action_data=action_data,
        result_data=result_data,
        score=score,
    )

    # ---- DataArchitecture --------------------------------------
    action_id = f"{engine}_{action_type}_{int(time.time() * 1000)}"
    _record_in_data_arch(
        action_id=action_id,
        action_type=action_type,
        action_data=action_data,
        result_data=result_data,
        score=score,
    )

    # ---- LearningLoop ------------------------------------------
    _feed_learning_loop(
        category=engine,
        action_type=action_type,
        action_data=action_data,
        result_data=result_data,
        metrics=metrics,
    )


# ── Score ──────────────────────────────────────────────────────


_BASE_SCORE = 3.0
_SUCCESS_BONUS = 1.0
_ERROR_PENALTY = 1.5
_REVENUE_BONUS = 0.5
_PROFITABLE_BONUS = 0.3
_MIN_SCORE = 1.0
_MAX_SCORE = 5.0


def _compute_score(
    *,
    success: bool,
    metrics: dict[str, Any] | None,
) -> float:
    """Mirror ``SmartExecutor._score_outcome`` for consistency.

    Base 3.0, ±adjustments based on success/error/metrics, clamped
    to [1.0, 5.0]. The score determines whether MemoryIntelligence
    promotes this memory and whether failure-intelligence kicks in
    (score ≤ 2.0 triggers failure recording).
    """
    score = _BASE_SCORE
    if success:
        score += _SUCCESS_BONUS
    else:
        score -= _ERROR_PENALTY

    if metrics:
        rev = metrics.get("revenue_change_pct")
        try:
            rev_f = float(rev) if rev is not None else 0.0
        except (TypeError, ValueError):
            rev_f = 0.0
        if rev_f > 5:
            score += _REVENUE_BONUS
        elif rev_f < -5:
            score -= _REVENUE_BONUS

        if metrics.get("profitable"):
            score += _PROFITABLE_BONUS

    return max(_MIN_SCORE, min(_MAX_SCORE, round(score, 1)))


# ── Memory Intelligence ───────────────────────────────────────


def _record_in_memory_intel(
    *,
    category: str,
    action_type: str,
    action_data: dict[str, Any],
    result_data: dict[str, Any],
    score: float,
) -> None:
    """Best-effort write to ``MemoryIntelligence.create_from_decision``."""
    intel = _get_memory_intel()
    if intel is None:
        return
    try:
        intel.create_from_decision(
            category=category,
            input_data=action_data,
            action=action_type,
            result=result_data,
            score=score,
            tags=[
                category, action_type, "writeback",
                "success" if result_data.get("success") else "failure",
            ],
        )
        # Failures are gold — auto-record after 3+ similar so the
        # avoidance-rule pipeline can act.
        if score <= 2.0:
            intel.record_failure(
                category=category,
                failure_data={
                    "action": action_data,
                    "result": result_data,
                },
                root_cause=str(
                    result_data.get("error", f"low_score_{score}"),
                ),
                severity="critical" if score <= 1.5 else "medium",
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("memory_intel record failed: %s", exc)


# ── Data Architecture ─────────────────────────────────────────


def _record_in_data_arch(
    *,
    action_id: str,
    action_type: str,
    action_data: dict[str, Any],
    result_data: dict[str, Any],
    score: float,
) -> None:
    """Best-effort write to the 12-domain action→result tables."""
    arch = _get_data_arch()
    if arch is None:
        return
    try:
        arch.record_action(
            action_id=action_id,
            action_type=action_type,
            action_data=action_data,
        )
        arch.attach_result(action_id, result_data, score=score)
    except Exception as exc:  # noqa: BLE001
        logger.debug("data_arch record failed: %s", exc)


# ── Learning Loop ─────────────────────────────────────────────


def _feed_learning_loop(
    *,
    category: str,
    action_type: str,
    action_data: dict[str, Any],
    result_data: dict[str, Any],
    metrics: dict[str, Any] | None,
) -> None:
    """Best-effort feed to the LearningLoop for pattern detection."""
    loop = _get_learning_loop()
    if loop is None:
        return
    try:
        loop.learn(
            category=category,
            input_data=action_data,
            action=action_type,
            result=result_data,
            metrics={
                "profit": float(
                    (metrics or {}).get("revenue_change_pct", 0) or 0,
                ),
                "conversion": float(
                    (metrics or {}).get("conversion_lift", 0) or 0,
                ),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("learning_loop record failed: %s", exc)


# ── Lazy-loaded singletons ─────────────────────────────────────


def _get_memory_intel() -> Any | None:
    try:
        from core.memory.intelligence import get_memory_intelligence
    except Exception as exc:  # noqa: BLE001
        logger.debug("memory_intel import failed: %s", exc)
        return None
    try:
        return get_memory_intelligence()
    except Exception as exc:  # noqa: BLE001
        logger.debug("memory_intel init failed: %s", exc)
        return None


def _get_data_arch() -> Any | None:
    try:
        from core.data.architecture import get_data_architecture
    except Exception as exc:  # noqa: BLE001
        logger.debug("data_arch import failed: %s", exc)
        return None
    try:
        return get_data_architecture()
    except Exception as exc:  # noqa: BLE001
        logger.debug("data_arch init failed: %s", exc)
        return None


def _get_learning_loop() -> Any | None:
    try:
        from core.brain.learning_loop import LearningLoop
    except Exception as exc:  # noqa: BLE001
        logger.debug("learning_loop import failed: %s", exc)
        return None
    try:
        return LearningLoop()
    except Exception as exc:  # noqa: BLE001
        logger.debug("learning_loop init failed: %s", exc)
        return None
