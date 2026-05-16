"""Decision-time RAG retriever.

Returns the top-k past decisions most similar to a query, joined
with their measured outcomes. Scoring is deterministic: weighted
combination of action-type match, capability match, params
overlap, and recency decay.

The implementation goes against the existing ``pending_actions``
+ ``action_outcomes`` tables (PR #57 + PR #156 + the feedback
bridge). No new schema. No vector store. No embeddings.

Why not embeddings:
  - Data volume is small (thousands per engine, not millions).
  - Deterministic scoring is debuggable.
  - Avoids a heavy dependency (sentence-transformers, openai
    embeddings, etc.) and a network call on every decision.
  - The retrieval contract is stable -- adding embeddings later
    swaps the implementation without changing callers.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Any

logger = logging.getLogger(__name__)


# Default scoring weights. Each component is in [0, 1]; the final
# relevance score is the weighted sum, also clamped to [0, 1].
DEFAULT_WEIGHTS = {
    "action_type": 0.4,
    "capability": 0.2,
    "params": 0.25,
    "recency": 0.15,
}

# Recency half-life. 7 days = 50% weight; 28 days = ~12.5% weight.
RECENCY_HALFLIFE_SECONDS = 7.0 * 86_400.0


class DecisionRetrieval:
    """Decision-time retriever.

    Construct with a ``queue=`` override for tests; production
    callers leave it None and use the process-wide
    ApprovalQueue singleton.
    """

    def __init__(
        self,
        *,
        queue: Any = None,
        weights: dict | None = None,
    ) -> None:
        self._queue_override = queue
        self._weights = dict(DEFAULT_WEIGHTS)
        if weights:
            self._weights.update(weights)

    def _queue(self) -> Any:
        if self._queue_override is not None:
            return self._queue_override
        from core.approval.queue import get_approval_queue
        return get_approval_queue()

    # ── Public API ──────────────────────────────────────────

    def retrieve(
        self,
        *,
        engine: str,
        action_type: str | None = None,
        capability: str | None = None,
        params: dict | None = None,
        k: int = 5,
        candidate_pool: int = 100,
        statuses: tuple[str, ...] = ("executed", "failed"),
    ) -> list[dict[str, Any]]:
        """Return top-k similar past decisions for an engine.

        Args:
            engine: Filter to this engine (required -- cross-engine
                retrieval makes no sense; engines speak different
                action-type vocabularies).
            action_type: Optional filter / scoring boost. When
                supplied, candidates with a matching action_type
                score higher.
            capability: Optional filter / scoring boost. Same as
                ``action_type``.
            params: Optional params dict for overlap scoring.
                Matched against each candidate's stored params via
                a key-Jaccard plus value-equality combination.
            k: Number of results to return.
            candidate_pool: Number of candidates to pre-filter
                from the DB before scoring. Larger pool = more
                accurate ranking, slower retrieval. Default 100 is
                appropriate for the current scale (<10k entries).
            statuses: Which action statuses to consider. Default:
                executed + failed (terminal states that have an
                outcome to learn from). Pass
                ``("executed", "failed", "rejected")`` for a
                wider net.

        Returns:
            List of dicts ordered by relevance desc. Each dict has:
              - action_id, engine, action_type, capability, params,
                status, decided_at
              - outcomes: list of recorded outcome rows
              - outcome_summary: aggregate {polarity_counts,
                total_revenue, has_positive, has_negative}
              - relevance: float in [0, 1] -- the score
              - score_components: dict per-factor for debugging
        """
        queue = self._queue()

        # ── Pull candidates ─────────────────────────────────
        candidates = self._pull_candidates(
            queue, engine=engine, statuses=statuses,
            limit=candidate_pool,
        )
        if not candidates:
            return []

        # ── Score each ──────────────────────────────────────
        scored: list[dict] = []
        now = time.time()
        for cand in candidates:
            components = self._score_one(
                cand,
                action_type=action_type,
                capability=capability,
                params=params,
                now=now,
            )
            relevance = self._combine(components)
            cand["relevance"] = round(relevance, 4)
            cand["score_components"] = {
                key: round(value, 4)
                for key, value in components.items()
            }
            scored.append(cand)

        # ── Top-k by relevance ──────────────────────────────
        scored.sort(key=lambda x: -x["relevance"])
        top_k = scored[:max(1, int(k))]

        # ── Attach outcomes (only for top-k -- saves DB hops) ─
        for entry in top_k:
            entry["outcomes"] = self._safe_get_outcomes(
                queue, entry["action_id"],
            )
            entry["outcome_summary"] = _summarize_outcomes(
                entry["outcomes"],
            )

        return top_k

    # ── Candidate pulling ───────────────────────────────────

    def _pull_candidates(
        self, queue: Any, *,
        engine: str, statuses: tuple[str, ...], limit: int,
    ) -> list[dict[str, Any]]:
        """Pull a flat list of candidate decisions for an engine.

        Uses ``ApprovalQueue.list_by_status`` for each requested
        status and merges. Each candidate is a flat dict (NOT an
        ApprovalAction) with the fields the scorer needs.
        """
        try:
            from core.approval.queue import ApprovalStatus
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "decision_retrieval: ApprovalStatus import failed: %s",
                exc,
            )
            return []

        out: list[dict] = []
        for status_name in statuses:
            try:
                status = ApprovalStatus(status_name)
            except ValueError:
                continue
            try:
                actions = queue.list_by_status(
                    status, engine=engine, limit=limit,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "decision_retrieval: list_by_status raised: %s",
                    exc,
                )
                continue
            for action in actions:
                # ApprovalAction is a dataclass; tolerate dict shape
                # too (for fake queues in tests).
                if hasattr(action, "to_dict"):
                    d = action.to_dict()
                else:
                    d = dict(action)
                out.append({
                    "action_id": d.get("id") or d.get("action_id"),
                    "engine": d.get("engine"),
                    "action_type": d.get("action_type"),
                    "capability": d.get("capability"),
                    "params": d.get("params") or {},
                    "status": d.get("status"),
                    "decided_at": d.get("decided_at")
                                  or d.get("proposed_at"),
                    "proposed_at": d.get("proposed_at"),
                    "narrative": d.get("narrative"),
                    "confidence": d.get("confidence"),
                })
        return out

    def _safe_get_outcomes(
        self, queue: Any, action_id: str,
    ) -> list[dict[str, Any]]:
        try:
            return queue.get_outcomes(action_id) or []
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "decision_retrieval: get_outcomes raised: %s", exc,
            )
            return []

    # ── Scoring ─────────────────────────────────────────────

    def _score_one(
        self,
        candidate: dict,
        *,
        action_type: str | None,
        capability: str | None,
        params: dict | None,
        now: float,
    ) -> dict[str, float]:
        action_score = 1.0 if (
            action_type and candidate.get("action_type") == action_type
        ) else 0.0
        capability_score = 1.0 if (
            capability and candidate.get("capability") == capability
        ) else 0.0
        params_score = _params_overlap(
            params or {}, candidate.get("params") or {},
        )
        decided_at = candidate.get("decided_at") or 0
        if decided_at:
            age = max(0.0, float(now) - float(decided_at))
            recency_score = 0.5 ** (age / RECENCY_HALFLIFE_SECONDS)
        else:
            recency_score = 0.0
        return {
            "action_type": action_score,
            "capability": capability_score,
            "params": params_score,
            "recency": recency_score,
        }

    def _combine(self, components: dict[str, float]) -> float:
        score = 0.0
        for key, weight in self._weights.items():
            score += weight * components.get(key, 0.0)
        return max(0.0, min(1.0, score))


# ── Helpers ─────────────────────────────────────────────────


def _params_overlap(a: dict, b: dict) -> float:
    """Combined key-Jaccard + value-equality similarity.

    - Key Jaccard: |A ∩ B| / |A ∪ B|
    - Value match: for keys in both, what fraction have equal values?
    - Final: 0.5 * jaccard + 0.5 * value_match

    Empty dicts on both sides → 0.0 (neither informative).
    """
    if not a and not b:
        return 0.0
    keys_a = set(a.keys())
    keys_b = set(b.keys())
    union = keys_a | keys_b
    if not union:
        return 0.0
    intersection = keys_a & keys_b
    jaccard = len(intersection) / len(union)
    if not intersection:
        return 0.5 * jaccard
    value_match = sum(
        1 for k in intersection if a[k] == b[k]
    ) / len(intersection)
    return 0.5 * jaccard + 0.5 * value_match


def _summarize_outcomes(outcomes: list[dict]) -> dict[str, Any]:
    """Aggregate raw outcome rows into a single summary dict."""
    summary = {
        "count": len(outcomes),
        "polarity_counts": {
            "positive": 0, "negative": 0, "neutral": 0,
        },
        "total_revenue": 0.0,
        "has_positive": False,
        "has_negative": False,
    }
    for o in outcomes:
        polarity = o.get("polarity", "neutral")
        if polarity in summary["polarity_counts"]:
            summary["polarity_counts"][polarity] += 1
        if polarity == "positive":
            summary["has_positive"] = True
        elif polarity == "negative":
            summary["has_negative"] = True
        metrics = o.get("metrics") or {}
        revenue = metrics.get("revenue")
        if revenue is not None:
            try:
                summary["total_revenue"] += float(revenue)
            except (TypeError, ValueError) as exc:
                logger.debug(
                    "outcome revenue %r unparseable: %s",
                    revenue, exc,
                )
    return summary


def retrieve_similar(
    *,
    engine: str,
    action_type: str | None = None,
    capability: str | None = None,
    params: dict | None = None,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Module-level convenience: equivalent to
    ``DecisionRetrieval().retrieve(...)`` using the process-wide
    ApprovalQueue singleton.
    """
    return DecisionRetrieval().retrieve(
        engine=engine,
        action_type=action_type,
        capability=capability,
        params=params,
        k=k,
    )
