"""Tests for ``core.transfer_credit`` — the credit graph that
attributes downstream transfer outcomes back to source actions.

The data flow under test:
    [source action] → [transfer apply → target action] →
    [executed → outcome row] → attributed to source

Tests verify:
  - Empty / no-transfer rows → empty credit list
  - Source attribution: narratives parsed correctly to find source
  - Filters: --source-store + --engine post-parse
  - Aggregation: outcomes summed across all transfers from one source
  - Executed-only outcome attribution (pending transfers contribute 0)
  - Ranking: transfer_count desc, then positive, then revenue
  - Frozen TransferCredit dataclass
  - Malformed narratives skipped (no key to attribute to)
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.transfer_credit import (
    TransferCredit,
    compute_transfer_credits,
)
from core.transfer_narrative import format_narrative


def _fake_queue(*, rows=None, outcomes=None):
    rows = rows or []
    outcomes = outcomes or {}
    q = MagicMock()
    fake_conn = MagicMock()
    fake_conn.__enter__ = lambda self: self
    fake_conn.__exit__ = lambda *a: None
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    fake_conn.execute.return_value = cursor
    q._conn = fake_conn
    q.get_outcomes.side_effect = lambda aid: outcomes.get(aid, [])
    return q


def _target_row(
    *, id_, engine, action_type, from_store, to_store,
    status="executed", source_run_count=1,
):
    """Build a target-side row matching what
    ``transfer apply`` would have enqueued."""
    return {
        "id": id_,
        "engine": engine,
        "action_type": action_type,
        "narrative": format_narrative(
            engine=engine, action_type=action_type,
            from_store=from_store, to_store=to_store,
            source_run_count=source_run_count,
        ),
        "status": status,
    }


# ─── Empty state ─────────────────────────────────────────────


class TestEmptyState:

    def test_no_rows_returns_empty(self):
        q = _fake_queue(rows=[])
        assert compute_transfer_credits(q) == []

    def test_only_non_transfer_rows_returns_empty(self):
        """The SQL LIKE filter at the module's source means we
        only ever see transfer-applied rows here. But if a
        narrative parses with empty source_store (malformed),
        skip it."""
        q = _fake_queue(rows=[{
            "id": "x", "engine": "loyalty",
            "action_type": "mint",
            "narrative": (
                "Transfer suggestion: loyalty/mint. "
                "Malformed -- no from/to."
            ),
            "status": "executed",
        }])
        assert compute_transfer_credits(q) == []


# ─── Single-source aggregation ───────────────────────────────


class TestSingleSourceAggregation:

    def test_one_source_one_action_aggregated(self):
        rows = [
            _target_row(
                id_="t1", engine="loyalty",
                action_type="mint_loyalty_code",
                from_store="store-a", to_store="store-b",
            ),
            _target_row(
                id_="t2", engine="loyalty",
                action_type="mint_loyalty_code",
                from_store="store-a", to_store="store-c",
            ),
        ]
        outcomes = {
            "t1": [
                {"polarity": "positive", "metrics": {"revenue": 50.0}},
                {"polarity": "positive", "metrics": {"revenue": 25.0}},
            ],
            "t2": [
                {"polarity": "negative", "metrics": {"revenue": -10.0}},
            ],
        }
        q = _fake_queue(rows=rows, outcomes=outcomes)
        result = compute_transfer_credits(q)
        assert len(result) == 1
        c = result[0]
        assert isinstance(c, TransferCredit)
        assert c.source_store == "store-a"
        assert c.engine == "loyalty"
        assert c.action_type == "mint_loyalty_code"
        assert c.transfer_count == 2
        assert c.executed_count == 2
        # 2 positive (t1) + 0 (t2 had only negative) = 2
        assert c.positive_outcomes == 2
        assert c.negative_outcomes == 1
        # 50 + 25 + (-10) = 65
        assert c.revenue == 65.0
        # 2 / (2+1) = 0.667
        assert c.score == pytest.approx(2 / 3)

    def test_pending_target_contributes_zero_outcomes(self):
        """A transfer applied but not yet executed contributes
        to transfer_count but NOT executed_count or outcomes
        (PENDING/APPROVED/FAILED have no outcomes by
        contract -- record_outcome rejects non-executed)."""
        rows = [
            _target_row(
                id_="t1", engine="loyalty",
                action_type="mint",
                from_store="a", to_store="b",
                status="pending",
            ),
            _target_row(
                id_="t2", engine="loyalty",
                action_type="mint",
                from_store="a", to_store="c",
                status="executed",
            ),
        ]
        outcomes = {
            "t2": [
                {"polarity": "positive", "metrics": {"revenue": 30.0}},
            ],
        }
        q = _fake_queue(rows=rows, outcomes=outcomes)
        result = compute_transfer_credits(q)
        assert len(result) == 1
        c = result[0]
        assert c.transfer_count == 2  # both counted
        assert c.executed_count == 1  # only t2
        assert c.positive_outcomes == 1
        assert c.revenue == 30.0


# ─── Multi-source ranking ────────────────────────────────────


class TestRanking:

    def test_transfer_count_first_then_positive_then_revenue(self):
        rows = (
            # store-a/loyalty: 3 transfers, 1 positive
            [_target_row(
                id_=f"a{i}", engine="loyalty",
                action_type="mint",
                from_store="store-a", to_store="store-b",
            ) for i in range(3)]
            # store-c/cart: 3 transfers (same count), 0 positive
            + [_target_row(
                id_=f"c{i}", engine="cart_recovery",
                action_type="recover",
                from_store="store-c", to_store="store-d",
            ) for i in range(3)]
            # store-e/email: 1 transfer
            + [_target_row(
                id_="e1", engine="email_marketing",
                action_type="campaign",
                from_store="store-e", to_store="store-f",
            )]
        )
        outcomes = {
            "a0": [
                {"polarity": "positive", "metrics": {"revenue": 10.0}},
            ],
            "e1": [
                {"polarity": "positive", "metrics": {"revenue": 1000.0}},
            ],
        }
        q = _fake_queue(rows=rows, outcomes=outcomes)
        result = compute_transfer_credits(q)
        # Three buckets. store-a + store-c both have count=3;
        # store-a wins tiebreak via positive_outcomes (1 > 0).
        # store-e has count=1 -> last.
        assert len(result) == 3
        assert result[0].source_store == "store-a"
        assert result[1].source_store == "store-c"
        assert result[2].source_store == "store-e"


# ─── Filters ─────────────────────────────────────────────────


class TestFilters:

    def test_source_store_filter_post_parse(self):
        """--source-store filters AFTER parsing narratives
        since source isn't in any indexed column."""
        rows = [
            _target_row(
                id_=f"a{i}", engine="loyalty",
                action_type="mint",
                from_store="want", to_store="b",
            ) for i in range(2)
        ] + [
            _target_row(
                id_=f"b{i}", engine="loyalty",
                action_type="mint",
                from_store="skip", to_store="b",
            ) for i in range(3)
        ]
        q = _fake_queue(rows=rows)
        result = compute_transfer_credits(q, source_store="want")
        assert len(result) == 1
        assert result[0].source_store == "want"
        assert result[0].transfer_count == 2

    def test_engine_filter_propagates_to_sql(self):
        """--engine filter passes to the SQL WHERE clause
        (indexed column)."""
        q = _fake_queue(rows=[])
        compute_transfer_credits(q, engine="loyalty")
        call = q._conn.execute.call_args
        sql, params = call.args
        assert "engine = ?" in sql
        assert "loyalty" in params


# ─── TransferCredit interface ────────────────────────────────


class TestTransferCreditInterface:

    def test_is_frozen(self):
        rows = [
            _target_row(
                id_="t1", engine="loyalty",
                action_type="mint",
                from_store="a", to_store="b",
            ),
        ]
        q = _fake_queue(rows=rows)
        result = compute_transfer_credits(q)
        c = result[0]
        with pytest.raises(Exception):
            c.transfer_count = 999  # type: ignore[misc]

    def test_score_none_when_no_polarised(self):
        rows = [
            _target_row(
                id_="t1", engine="loyalty",
                action_type="mint",
                from_store="a", to_store="b",
            ),
        ]
        # No outcomes attached.
        q = _fake_queue(rows=rows)
        result = compute_transfer_credits(q)
        assert result[0].score is None


# ─── Resilience ──────────────────────────────────────────────


class TestResilience:

    def test_get_outcomes_raise_skips_outcomes_only(self):
        """A queue.get_outcomes raise on one row shouldn't crash
        the whole computation -- that row contributes to
        transfer_count + executed_count but zero outcomes."""
        rows = [
            _target_row(
                id_="t1", engine="loyalty",
                action_type="mint",
                from_store="a", to_store="b",
            ),
        ]
        q = _fake_queue(rows=rows)
        q.get_outcomes.side_effect = RuntimeError("outcomes table")
        result = compute_transfer_credits(q)
        assert len(result) == 1
        assert result[0].transfer_count == 1
        assert result[0].executed_count == 1
        # No outcomes attributed -- but the run didn't crash.
        assert result[0].positive_outcomes == 0
        assert result[0].negative_outcomes == 0
