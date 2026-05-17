"""End-to-end integration test: empire-AGI cross-store flow
exercised against a real (temp-file) SQLite-backed
``ApprovalQueue``.

Most empire-AGI tests use mocked queues. This test uses the
canonical SQLite path -- same schema, same triggers, same row
shape -- so:

  - Schema migrations actually apply (catches regressions on
    PR #239's idempotent ALTER TABLE if it's ever changed).
  - The narrative LIKE filter is exercised against real SQLite
    (not just an in-memory connection).
  - The full chain runs through the canonical APIs the
    autonomous loop + webhook bridge use.

The chain under test:

    enqueue(narrative=Transfer suggestion: ...) →
    mark executed →
    record_outcome →
    list_recent_outcomes(store_id=target) →
    aggregate_outcomes()
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.approval.outcome_aggregator import aggregate_outcomes
from core.approval.queue import (
    ApprovalQueue,
    ApprovalStatus,
)
from core.transfer_narrative import (
    SQL_LIKE_CLAUSE,
    format_narrative,
    parse_engine_action,
    parse_source_store,
    parse_target_store,
)


@pytest.fixture
def temp_queue(tmp_path: Path):
    """Yield a fresh ApprovalQueue backed by a temp SQLite
    file. Each test gets its own DB so state doesn't bleed."""
    db_path = tmp_path / "test_approval_queue.db"
    queue = ApprovalQueue(db_path=db_path)
    yield queue
    # Cleanup happens automatically when tmp_path goes out of
    # scope; we just need to release any file handles.
    try:
        queue._conn.close()
    except Exception:  # noqa: BLE001
        pass


def _enqueue_transfer(
    queue: ApprovalQueue,
    *,
    engine: str,
    action_type: str,
    from_store: str,
    to_store: str,
    source_run_count: int = 2,
) -> str:
    """Enqueue a transfer-applied action on the target store,
    matching what ``shopai transfer apply`` would write."""
    narrative = format_narrative(
        engine=engine,
        action_type=action_type,
        from_store=from_store,
        to_store=to_store,
        source_run_count=source_run_count,
    )
    action = queue.enqueue(
        engine=engine,
        action_type=action_type,
        capability="SHOPIFY_CREATE_DISCOUNT",
        params={"customer_id": "gid://X/1", "demo": True},
        narrative=narrative,
        store_id=to_store,
    )
    return action.id


def _mark_executed(queue: ApprovalQueue, action_id: str) -> None:
    """Approve + execute path -- shortcut via direct UPDATE
    since the lifecycle test isn't the focus here."""
    import time
    with queue._conn:
        queue._conn.execute(
            "UPDATE pending_actions SET status=?, "
            "decided_at=?, decided_by=? WHERE id=?",
            (
                ApprovalStatus.EXECUTED.value,
                time.time(),
                "integration_test",
                action_id,
            ),
        )


# ─── Full empire-AGI chain ───────────────────────────────────


class TestEmpireAGIChain:

    def test_full_chain_apply_executed_outcome_aggregated(
        self, temp_queue,
    ):
        # 1. Enqueue a transfer-applied action on store-b
        action_id = _enqueue_transfer(
            temp_queue,
            engine="loyalty",
            action_type="mint_loyalty_code",
            from_store="store-a",
            to_store="store-b",
            source_run_count=3,
        )
        assert action_id

        # 2. Verify narrative parsers recover the source store
        action = temp_queue.get(action_id)
        assert action is not None
        assert parse_source_store(action.narrative) == "store-a"
        assert action.store_id == "store-b"

        # 3. Mark executed (operator approval + write happens)
        _mark_executed(temp_queue, action_id)

        # 4. Webhook lands an outcome
        recorded = temp_queue.record_outcome(
            action_id,
            topic="orders/create",
            polarity="positive",
            metrics={"revenue": 50.0},
            source_event="integration_test",
        )
        assert recorded is True

        # 5. Per-store outcome stream surfaces it
        outcomes = temp_queue.list_recent_outcomes(
            store_id="store-b", limit=10,
        )
        assert len(outcomes) == 1
        assert outcomes[0]["polarity"] == "positive"
        assert outcomes[0]["metrics"]["revenue"] == 50.0

        # 6. Aggregate via shared rollup utility
        stats = aggregate_outcomes(outcomes)
        assert stats.positive == 1
        assert stats.negative == 0
        assert stats.revenue == 50.0
        assert stats.outcome_score == 1.0

    def test_all_parsers_round_trip_through_real_queue(
        self, temp_queue,
    ):
        """Every narrative parser recovers what the format
        helper put in, on a row that round-tripped through
        real SQLite (catches any sqlite TEXT mangling)."""
        action_id = _enqueue_transfer(
            temp_queue,
            engine="cart_recovery",
            action_type="mint_cart_recovery_code",
            from_store="store-alpha",
            to_store="store-beta",
        )
        action = temp_queue.get(action_id)
        narrative = action.narrative
        assert parse_source_store(narrative) == "store-alpha"
        assert parse_target_store(narrative) == "store-beta"
        engine, action_type = parse_engine_action(narrative)
        assert engine == "cart_recovery"
        assert action_type == "mint_cart_recovery_code"


# ─── SQL LIKE clause works on real SQLite ────────────────────


class TestSqlLikeAgainstRealQueue:

    def test_clause_filters_transfer_rows_only(self, temp_queue):
        """Mix transfer-applied + non-transfer rows; the
        SQL_LIKE_CLAUSE filter should return only the transfers.
        Catches regressions on the LIKE pattern with real SQLite
        (which has slightly different LIKE semantics than the
        in-memory MagicMock fakes used elsewhere)."""
        # Transfer-applied row
        transfer_id = _enqueue_transfer(
            temp_queue,
            engine="loyalty",
            action_type="mint",
            from_store="a", to_store="b",
        )
        # Non-transfer row (engine-direct enqueue, no narrative)
        regular = temp_queue.enqueue(
            engine="loyalty",
            action_type="mint",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params={},
            narrative="Plain engine recommendation, no transfer marker.",
            store_id="b",
        )

        with temp_queue._conn:
            rows = temp_queue._conn.execute(
                f"SELECT id FROM pending_actions WHERE {SQL_LIKE_CLAUSE}",
            ).fetchall()
        ids = {r["id"] for r in rows}
        assert transfer_id in ids
        assert regular.id not in ids


# ─── Per-store filter on list_recent_outcomes ────────────────


class TestPerStoreOutcomeFilter:
    """``list_recent_outcomes(store_id=...)`` (PR #280) was tested
    with mocked queues. Exercise it against the real SQLite to
    verify the JOIN-based filter actually narrows correctly."""

    def test_outcomes_filtered_to_target_store(self, temp_queue):
        # Two transfers: one to store-b, one to store-c
        id_b = _enqueue_transfer(
            temp_queue,
            engine="loyalty", action_type="mint",
            from_store="a", to_store="store-b",
        )
        id_c = _enqueue_transfer(
            temp_queue,
            engine="loyalty", action_type="mint",
            from_store="a", to_store="store-c",
        )
        for aid in (id_b, id_c):
            _mark_executed(temp_queue, aid)

        # Outcome on each
        temp_queue.record_outcome(
            id_b, topic="orders/create", polarity="positive",
            metrics={"revenue": 25.0}, source_event="t",
        )
        temp_queue.record_outcome(
            id_c, topic="orders/create", polarity="positive",
            metrics={"revenue": 30.0}, source_event="t",
        )

        # Filter to store-b only
        b_outcomes = temp_queue.list_recent_outcomes(
            store_id="store-b", limit=10,
        )
        assert len(b_outcomes) == 1
        assert b_outcomes[0]["action_id"] == id_b

        # Filter to store-c only
        c_outcomes = temp_queue.list_recent_outcomes(
            store_id="store-c", limit=10,
        )
        assert len(c_outcomes) == 1
        assert c_outcomes[0]["action_id"] == id_c

        # No filter -> both surface
        all_outcomes = temp_queue.list_recent_outcomes(limit=10)
        assert len(all_outcomes) == 2
