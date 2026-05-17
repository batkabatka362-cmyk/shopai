"""End-to-end integration test for ``core.transfer_credit``
against a real (temp-file) SQLite-backed ``ApprovalQueue``.

The unit tests (``tests/test_transfer_credit.py``) use mocked
queues -- catches interface drift but not real SQLite LIKE
quirks, JOIN behaviour, or column coercion. This file
exercises the credit-graph computation on rows that round-
tripped through the canonical schema.

Scenario under test:
  1. Two source-store actions (store-A) inspire two target-side
     transfers (one to store-B, one to store-C).
  2. Both target actions execute + record outcomes.
  3. ``compute_transfer_credits`` walks the chain backward and
     attributes the downstream outcomes to the source action's
     (engine, action_type) tuple.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.approval.queue import ApprovalQueue, ApprovalStatus
from core.transfer_credit import compute_transfer_credits
from core.transfer_narrative import format_narrative


@pytest.fixture
def temp_queue(tmp_path: Path):
    db_path = tmp_path / "test_transfer_credit.db"
    queue = ApprovalQueue(db_path=db_path)
    yield queue
    try:
        queue._conn.close()
    except Exception:  # noqa: BLE001
        pass


def _enqueue_target_transfer(
    queue: ApprovalQueue,
    *,
    engine: str,
    action_type: str,
    from_store: str,
    to_store: str,
    source_run_count: int = 2,
) -> str:
    """Enqueue a target-side transfer-applied action, matching
    what ``shopai transfer apply`` would write on the target
    store."""
    narrative = format_narrative(
        engine=engine, action_type=action_type,
        from_store=from_store, to_store=to_store,
        source_run_count=source_run_count,
    )
    action = queue.enqueue(
        engine=engine, action_type=action_type,
        capability="SHOPIFY_CREATE_DISCOUNT",
        params={"customer_id": "gid://X/1"},
        narrative=narrative,
        store_id=to_store,
    )
    return action.id


def _mark_executed(queue: ApprovalQueue, action_id: str) -> None:
    import time
    with queue._conn:
        queue._conn.execute(
            "UPDATE pending_actions SET status=?, decided_at=?, "
            "decided_by=? WHERE id=?",
            (
                ApprovalStatus.EXECUTED.value,
                time.time(), "integration_test", action_id,
            ),
        )


# ─── Full chain ──────────────────────────────────────────────


class TestTransferCreditChain:

    def test_two_transfers_one_source_aggregated(self, temp_queue):
        """One source action inspires two target transfers; the
        downstream outcomes aggregate up to one TransferCredit
        row keyed on (store-A, loyalty, mint_loyalty_code)."""
        # Two transfers from store-A: one to store-B, one to
        # store-C, both for loyalty/mint_loyalty_code
        id_b = _enqueue_target_transfer(
            temp_queue,
            engine="loyalty",
            action_type="mint_loyalty_code",
            from_store="store-a", to_store="store-b",
        )
        id_c = _enqueue_target_transfer(
            temp_queue,
            engine="loyalty",
            action_type="mint_loyalty_code",
            from_store="store-a", to_store="store-c",
        )
        for aid in (id_b, id_c):
            _mark_executed(temp_queue, aid)

        # Outcomes: store-B positive, store-C also positive
        temp_queue.record_outcome(
            id_b, topic="orders/create", polarity="positive",
            metrics={"revenue": 100.0},
            source_event="integration",
        )
        temp_queue.record_outcome(
            id_c, topic="orders/create", polarity="positive",
            metrics={"revenue": 50.0},
            source_event="integration",
        )

        # Walk the credit graph
        credits = compute_transfer_credits(temp_queue)
        assert len(credits) == 1
        credit = credits[0]
        assert credit.source_store == "store-a"
        assert credit.engine == "loyalty"
        assert credit.action_type == "mint_loyalty_code"
        assert credit.transfer_count == 2
        assert credit.executed_count == 2
        assert credit.positive_outcomes == 2
        assert credit.negative_outcomes == 0
        assert credit.revenue == 150.0
        assert credit.score == 1.0

    def test_source_store_filter_narrows(self, temp_queue):
        """``--source-store`` filters AFTER parsing narratives
        (source isn't an indexed column on real SQLite either)."""
        _enqueue_target_transfer(
            temp_queue, engine="loyalty", action_type="mint",
            from_store="store-want", to_store="store-x",
        )
        _enqueue_target_transfer(
            temp_queue, engine="loyalty", action_type="mint",
            from_store="store-skip", to_store="store-x",
        )

        credits = compute_transfer_credits(
            temp_queue, source_store="store-want",
        )
        assert len(credits) == 1
        assert credits[0].source_store == "store-want"
        assert credits[0].transfer_count == 1

    def test_engine_filter_propagates_to_sql(self, temp_queue):
        """``--engine`` filter uses the indexed column at the
        SQL layer. Verify the filter actually narrows the
        result set on real SQLite (catches LIKE / engine column
        interaction regressions)."""
        _enqueue_target_transfer(
            temp_queue, engine="loyalty", action_type="mint",
            from_store="store-a", to_store="store-b",
        )
        _enqueue_target_transfer(
            temp_queue, engine="cart_recovery",
            action_type="recover",
            from_store="store-a", to_store="store-b",
        )

        loyalty_only = compute_transfer_credits(
            temp_queue, engine="loyalty",
        )
        assert len(loyalty_only) == 1
        assert loyalty_only[0].engine == "loyalty"

    def test_pending_transfer_counted_but_no_outcomes(
        self, temp_queue,
    ):
        """A PENDING transfer contributes to ``transfer_count``
        but NOT ``executed_count`` (the contract from the unit
        tests holds on real SQLite too)."""
        id_pending = _enqueue_target_transfer(
            temp_queue, engine="loyalty", action_type="mint",
            from_store="store-a", to_store="store-b",
        )
        id_exec = _enqueue_target_transfer(
            temp_queue, engine="loyalty", action_type="mint",
            from_store="store-a", to_store="store-c",
        )
        _mark_executed(temp_queue, id_exec)
        temp_queue.record_outcome(
            id_exec, topic="orders/create", polarity="positive",
            metrics={"revenue": 30.0}, source_event="t",
        )

        credits = compute_transfer_credits(temp_queue)
        assert len(credits) == 1
        c = credits[0]
        assert c.transfer_count == 2
        assert c.executed_count == 1
        # Only the executed one contributed outcomes.
        assert c.positive_outcomes == 1
        assert c.revenue == 30.0

    def test_empty_when_no_transfer_rows(self, temp_queue):
        """A queue with only non-transfer narratives returns []
        on real SQLite -- catches LIKE pattern regressions."""
        temp_queue.enqueue(
            engine="loyalty", action_type="mint",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params={},
            narrative="Plain engine recommendation, no transfer.",
            store_id="store-x",
        )
        credits = compute_transfer_credits(temp_queue)
        assert credits == []
