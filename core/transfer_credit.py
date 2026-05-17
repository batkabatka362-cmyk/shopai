"""Transfer credit graph — attribute downstream outcomes back to
source actions across stores.

When ``shopai transfer apply`` enqueues a PENDING action on the
target store, the row's narrative carries the source store and
(engine, action_type). After the operator approves + the action
executes + a webhook lands an outcome, we have a chain:

    [source store's executed action]
        ↓ (transfer apply, narrative parsed by transfer_narrative)
    [target store's PENDING → APPROVED → EXECUTED action]
        ↓ (webhook → record_outcome)
    [target's outcome row]

This module computes the credit graph: for each (source_store,
engine, action_type) tuple, sum the outcomes on the TARGET-side
actions that were transfer-applied from it. Operators can see
"loyalty/mint_loyalty_code on store-A inspired 5 successful
transfers across the fleet with $250 attributed revenue".

The data already exists -- ``pending_actions`` rows carry the
transfer narrative + the ``store_id`` (target). ``action_outcomes``
rows are joined per action. No schema change required; pure
read-side analytics.

Used by (or will be used by):
- ``shopai transfer credit`` (future CLI) — operator surface
- ``core.world_model._section_transfer_credit`` (future) — per-
  store snapshot enrichment
- AGI ranking signal — source actions with high transfer credit
  rank higher in retrieval

This module is the data-producing core; surfaces consume it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TransferCredit:
    """Aggregated downstream outcomes attributable to one source
    (engine, action_type) tuple.

    Fields:
        source_store: Store id the transfers originated from
            (parsed from each target action's narrative).
        engine: Engine namespace.
        action_type: Specific action label.
        transfer_count: Number of distinct target actions that
            were transfer-applied from this source tuple.
        executed_count: Subset of transfers where the target
            action reached status=EXECUTED. Lower bound on
            outcomes-having transfers (pending/failed transfers
            contribute zero outcomes by definition).
        positive_outcomes: Count of polarity='positive' outcome
            rows summed across all executed target actions.
        negative_outcomes: Same, polarity='negative'.
        revenue: Sum of ``metrics.revenue`` across all outcome
            rows on the executed target actions.
        score: ``positive / (positive + negative)`` over the
            attributed outcomes; ``None`` when no polarised
            outcomes have arrived yet.
    """

    source_store: str
    engine: str
    action_type: str
    transfer_count: int
    executed_count: int
    positive_outcomes: int
    negative_outcomes: int
    revenue: float
    score: float | None


def compute_transfer_credits(
    queue: Any,
    *,
    source_store: str | None = None,
    engine: str | None = None,
    limit: int = 500,
) -> list[TransferCredit]:
    """Compute the transfer credit graph.

    Args:
        queue: ApprovalQueue (or compatible) -- must expose
            ``_conn`` for SQL access and ``get_outcomes(id)``.
        source_store: Optional filter -- only return credits for
            transfers originating from this store (parsed from
            target narratives).
        engine: Optional filter -- only return credits for one
            engine.
        limit: Cap on raw target-action rows scanned. Default
            500 fits the current scale; bump for fleets with
            thousands of transfers.

    Returns:
        List of :class:`TransferCredit`, ranked by transfer_count
        desc (most-replicated source actions first), with
        positive_outcomes desc + revenue desc as tiebreakers.

    Queue exceptions are NOT caught here; callers decide how
    to handle them. Empty list when nothing matches.
    """
    from core.approval.outcome_aggregator import aggregate_outcomes
    from core.transfer_narrative import (
        SQL_LIKE_CLAUSE,
        parse_engine_action,
        parse_source_store,
    )

    # Pull every target-side transfer-applied action.
    clauses = [SQL_LIKE_CLAUSE]
    params: list[Any] = []
    if engine:
        clauses.append("engine = ?")
        params.append(engine)
    params.append(limit)
    sql = (
        "SELECT id, engine, action_type, narrative, status "
        "FROM pending_actions WHERE "
        + " AND ".join(clauses)
        + " ORDER BY proposed_at DESC LIMIT ?"
    )

    with queue._conn:
        rows = queue._conn.execute(sql, params).fetchall()

    # Bucket by (source_store, engine, action_type).
    buckets: dict[tuple[str, str, str], dict] = {}
    for r in rows:
        # Source-store comes from the narrative parse, not the
        # row's store_id column (that's the TARGET).
        narrative = r["narrative"] or ""
        parsed_source = parse_source_store(narrative)
        # If the narrative was malformed or the source wasn't
        # parseable, skip -- there's no key to attribute to.
        if not parsed_source:
            continue
        # Apply source filter post-parse since source isn't in
        # an indexed column.
        if source_store and parsed_source != source_store:
            continue

        # Engine + action_type come from the row's columns
        # (faster + authoritative) but fall back to narrative
        # parse if a column is somehow blank.
        row_engine = r["engine"] or ""
        row_action_type = r["action_type"] or ""
        if not row_engine or not row_action_type:
            parsed_engine, parsed_action = (
                parse_engine_action(narrative)
            )
            row_engine = row_engine or parsed_engine
            row_action_type = row_action_type or parsed_action
        if not row_engine or not row_action_type:
            continue

        key = (parsed_source, row_engine, row_action_type)
        if key not in buckets:
            buckets[key] = {
                "transfer_count": 0,
                "executed_count": 0,
                "outcomes": [],
            }
        b = buckets[key]
        b["transfer_count"] += 1

        status = (r["status"] or "").lower()
        if status != "executed":
            continue
        b["executed_count"] += 1
        try:
            outcomes = queue.get_outcomes(r["id"]) or []
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "transfer_credit get_outcomes raised: %s", exc,
            )
            outcomes = []
        b["outcomes"].extend(outcomes)

    credits: list[TransferCredit] = []
    for (src, eng, atype), b in buckets.items():
        stats = aggregate_outcomes(b["outcomes"])
        credits.append(TransferCredit(
            source_store=src,
            engine=eng,
            action_type=atype,
            transfer_count=b["transfer_count"],
            executed_count=b["executed_count"],
            positive_outcomes=stats.positive,
            negative_outcomes=stats.negative,
            revenue=stats.revenue,
            score=stats.outcome_score,
        ))

    credits.sort(key=lambda c: (
        -c.transfer_count,
        -c.positive_outcomes,
        -c.revenue,
        c.source_store, c.engine, c.action_type,
    ))
    return credits
