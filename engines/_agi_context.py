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
