"""Shared AGI-stack context-capture helper for engines.

Bridges Phase 6/7 engine writers to the Phase 2 AGI
orchestration layers:

  - ``core.world_model.WorldModel`` — per-store snapshot
  - ``core.decision_retrieval.DecisionRetrieval`` — top-k past
    similar decisions joined with outcomes

When an engine is about to make a decision, it calls
``capture_decision_context(...)`` to get a single dict
containing both signals. The engine can use the dict to (1)
inform the decision and (2) attach it to the
``record_writeback`` metrics so the data architecture and
learning loop see the same context.

v1 contract: capture is **OBSERVATIONAL** — the helper never
modifies the engine's decision. Engines opt into actually
acting on the retrieved context engine-by-engine. This staged
rollout lets us validate the signal before wiring it into the
decision logic.

Resilience: any failure (missing module / DB lock / unavailable
singleton) degrades silently to an empty context dict. The
engine pipeline must keep running even when the AGI stack is
down.

Test-environment guard: under pytest, the helper short-circuits
the same way ``record_writeback`` does. Unit tests injecting
synthetic engine inputs would otherwise hammer the real on-disk
world-model SQLite and decision-retrieval DB.
"""
from __future__ import annotations

import os
from typing import Any

from utils.logger import get_logger

logger = get_logger("engines.agi_context")


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def capture_decision_context(
    *,
    engine: str,
    action_type: str,
    capability: str,
    params: dict[str, Any],
    store_id: str | None = None,
    k: int = 3,
) -> dict[str, Any]:
    """Capture AGI-stack context for a single engine decision.

    Args:
        engine: Engine name issuing the decision. Used to filter
            the retrieval to same-engine past actions.
        action_type: Specific action label
            (e.g. ``"mint_loyalty_code"``).
        capability: Shopify capability that will be invoked.
        params: Friendly-form params -- used for the params
            overlap scoring in retrieval.
        store_id: Optional store ID. When supplied, the
            world-model snapshot is captured for this store.
            Omit to skip the snapshot section.
        k: Number of past decisions to retrieve. Default 3 keeps
            the captured context light; bump for richer reasoning.

    Returns:
        Dict with up to two top-level keys:

          - ``snapshot``: per-store world-model snapshot
            (only populated when ``store_id`` is supplied and
            the world-model module is importable)
          - ``similar``: list of top-k retrieval results

        Plus a ``metrics`` sub-dict ready to pass through to
        ``record_writeback``:

          - ``similar_count``: number of past decisions surfaced
          - ``recent_positive``: whether any of them had a
            positive outcome
          - ``recent_negative``: same, negative
          - ``avg_relevance``: mean relevance across the top-k

        Empty dict (with ``"metrics": {}``) when both sources
        are unavailable.
    """
    if _is_test_environment():
        return {"metrics": {}}

    out: dict[str, Any] = {"metrics": {}}

    # ── Snapshot ────────────────────────────────────────────
    if store_id:
        try:
            from core.world_model import WorldModel
            out["snapshot"] = WorldModel().snapshot(
                store_id, skip_live=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("agi_context snapshot raised: %s", exc)

    # ── Retrieval ───────────────────────────────────────────
    try:
        from core.decision_retrieval import DecisionRetrieval
        similar = DecisionRetrieval().retrieve(
            engine=engine,
            action_type=action_type,
            capability=capability,
            params=params,
            k=k,
        )
        out["similar"] = similar
        out["metrics"].update(_summarize_similar(similar))
    except Exception as exc:  # noqa: BLE001
        logger.debug("agi_context retrieve raised: %s", exc)

    return out


# ── v2 guardrail helpers ───────────────────────────────────────
#
# When an engine wants to USE the captured AGI signal (not just
# observe it), three helpers shape the v2 wiring:
#
#   1. ``guardrail_enabled(engine_name)`` -- env-var opt-in.
#      Each engine has its own switch
#      ``SHOPAI_<ENGINE>_AGI_GUARDRAIL`` so operators can roll
#      out v2 one engine at a time. Default OFF for every engine.
#
#   2. ``should_block_unambiguous_negative(metrics)`` -- strict
#      guardrail. Returns True ONLY when ALL of:
#        - similar_count >= GUARDRAIL_MIN_SIMILAR
#        - recent_negative is True
#        - recent_positive is False (mixed signal → don't block)
#      Conservative on purpose: false positives (block-when-we-
#      shouldn't) cost revenue; false negatives (allow-when-we-
#      should-block) cost only the one bad action's signal.
#
#   3. ``explain_guardrail_block(metrics)`` -- audit reason
#      string for ``record_writeback``'s error field when the
#      guardrail fires.
#
# The loyalty engine (PR #245) was the reference implementation
# with these helpers inlined. This extraction lets other engines
# opt in to v2 by importing the helpers + adding a ~5-line
# check before their main action call.


GUARDRAIL_MIN_SIMILAR = 3
_GUARDRAIL_TRUTHY = {"1", "true", "yes", "on"}


# Canonical roster of engines with v2 guardrail wiring. New
# engines that import ``guardrail_enabled`` /
# ``should_block_unambiguous_negative`` and gate their main
# action call on them should be appended here so the operator
# CLI (``shopai engine guardrail``) surfaces them in the report.
#
# Source of truth — DO NOT hardcode this list elsewhere. The
# CLI handler reads from it via ``guardrail_state()``.
GUARDRAIL_ENGINES: tuple[str, ...] = (
    "loyalty",
    "cart_recovery",
    "browse_recovery",
    "email_marketing",
    "wholesale_b2b",
    "discount_strategy",
    "churn_prediction",
)


def guardrail_state() -> dict[str, bool]:
    """Return ``{engine_name: enabled_bool}`` for every engine
    in :data:`GUARDRAIL_ENGINES`.

    Convenience for the CLI surfaces that report per-engine
    guardrail state. Cheap (env-var reads only); safe to call
    in hot paths since it doesn't touch the queue / world-model.
    """
    return {
        engine: guardrail_enabled(engine)
        for engine in GUARDRAIL_ENGINES
    }


def guardrail_enabled(engine_name: str) -> bool:
    """Per-engine env-var opt-in for the v2 guardrail.

    Env var: ``SHOPAI_<ENGINE_NAME_UPPER>_AGI_GUARDRAIL``.
    Default OFF -- every engine's v2 wiring is opt-in so
    operators roll out one engine at a time and can revert any
    single engine without redeploying.
    """
    var = f"SHOPAI_{engine_name.upper()}_AGI_GUARDRAIL"
    return os.environ.get(var, "") in _GUARDRAIL_TRUTHY


def should_block_unambiguous_negative(
    metrics: dict[str, Any] | None,
) -> bool:
    """Strict guardrail: block ONLY when the signal is unambiguous.

    Returns True iff:
      - At least ``GUARDRAIL_MIN_SIMILAR`` similar past decisions
        exist (sparse signal isn't actionable).
      - At least one had a negative outcome.
      - ZERO had positive outcomes (mixed signal still gets a
        chance -- only unmixed-negative gets blocked).
    """
    if not metrics:
        return False
    try:
        similar = int(metrics.get("similar_count", 0) or 0)
    except (TypeError, ValueError):
        # Non-numeric similar_count → treat as no signal.
        return False
    if similar < GUARDRAIL_MIN_SIMILAR:
        return False
    if not metrics.get("recent_negative", False):
        return False
    if metrics.get("recent_positive", False):
        return False
    return True


def explain_guardrail_block(metrics: dict[str, Any]) -> str:
    """One-line audit reason for ``record_writeback``'s error
    field when the guardrail blocks an action."""
    return (
        f"agi_guardrail_blocked: "
        f"similar={metrics.get('similar_count', 0)} "
        f"negative=true positive=false "
        f"avg_relevance={metrics.get('avg_relevance', 0.0):.2f}"
    )


def _summarize_similar(
    similar: list[dict[str, Any]],
) -> dict[str, Any]:
    """Reduce a retrieval result list to a small metrics dict
    suitable for the record_writeback metrics passthrough."""
    if not similar:
        return {
            "similar_count": 0,
            "recent_positive": False,
            "recent_negative": False,
            "avg_relevance": 0.0,
        }
    total_relevance = 0.0
    recent_positive = False
    recent_negative = False
    for entry in similar:
        total_relevance += float(entry.get("relevance", 0.0) or 0.0)
        summary = entry.get("outcome_summary") or {}
        if summary.get("has_positive"):
            recent_positive = True
        if summary.get("has_negative"):
            recent_negative = True
    return {
        "similar_count": len(similar),
        "recent_positive": recent_positive,
        "recent_negative": recent_negative,
        "avg_relevance": round(total_relevance / len(similar), 4),
    }
