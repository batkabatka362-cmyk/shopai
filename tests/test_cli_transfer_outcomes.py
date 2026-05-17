"""Tests for ``shopai transfer outcomes`` -- empire-AGI closure.

For transferred actions that have EXECUTED on the target store,
join the action rows with their ``action_outcomes`` records and
surface a per-row + overall rollup so operators can see whether
the cross-store learning loop is actually paying off.

Covers:

  - No executed transfers → friendly empty state
  - Mixed positive / negative outcomes aggregate correctly
  - Revenue summed across outcome rows
  - Action with no outcomes → ``outcome_count=0`` (not dropped)
  - --engine / --to filters propagate to SQL
  - --from filters client-side (post narrative parse)
  - Only EXECUTED rows scanned (status filter in SQL)
  - get_outcomes raise → row still surfaces, outcomes empty
  - Queue unavailable → clean error
  - JSON envelope shape
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest


def _load_cli():
    spec = importlib.util.spec_from_file_location("shopai_cli", "cli.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli():
    return _load_cli()


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


def _ns(**kw):
    defaults = dict(
        from_store="", to_store="", engine="",
        limit=20, json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _row(
    *, id_="appr_1", engine="loyalty",
    action_type="mint_loyalty_code",
    capability="SHOPIFY_CREATE_DISCOUNT",
    store_id="b", from_store="a",
    narrative=None, decided_at=1700000000.0,
):
    if narrative is None:
        narrative = (
            f"Transfer suggestion: {engine}/{action_type} "
            f"from {from_store} to {store_id}. "
            f"Source had 1 prior successful run(s)."
        )
    return {
        "id": id_, "engine": engine,
        "action_type": action_type,
        "capability": capability,
        "store_id": store_id,
        "narrative": narrative,
        "decided_at": decided_at,
    }


def _fake_queue(rows=None, outcomes=None, scan_raises=None,
                get_outcomes_raises=None):
    rows = rows or []
    outcomes = outcomes or {}
    q = MagicMock()
    fake_conn = MagicMock()
    fake_conn.__enter__ = lambda self: self
    fake_conn.__exit__ = lambda *a: None
    fake_cursor = MagicMock()
    if scan_raises is not None:
        fake_conn.execute.side_effect = scan_raises
    else:
        fake_cursor.fetchall.return_value = rows
        fake_conn.execute.return_value = fake_cursor
    q._conn = fake_conn

    def _get(action_id):
        if get_outcomes_raises is not None:
            raise get_outcomes_raises
        return outcomes.get(action_id, [])

    q.get_outcomes.side_effect = _get
    return q


# ─── Empty state ─────────────────────────────────────────────


class TestEmptyState:

    def test_no_executed_transfers_friendly_text(self, cli):
        q = _fake_queue(rows=[])
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_outcomes, _ns(),
            )
        assert code == 0
        assert "No executed transfers" in out

    def test_no_executed_transfers_json_envelope(self, cli):
        q = _fake_queue(rows=[])
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_outcomes, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["count"] == 0
        assert data["rows"] == []
        assert data["rollup"]["positive_total"] == 0
        assert data["rollup"]["actions_with_outcomes"] == 0


# ─── Outcome aggregation ─────────────────────────────────────


class TestOutcomeAggregation:

    def test_mixed_outcomes_aggregated_per_row(self, cli):
        q = _fake_queue(
            rows=[_row(id_="x1", from_store="a", store_id="b")],
            outcomes={
                "x1": [
                    {"polarity": "positive",
                     "metrics": {"revenue": 100.0}},
                    {"polarity": "positive",
                     "metrics": {"revenue": 50.0}},
                    {"polarity": "negative",
                     "metrics": {"revenue": -25.0}},
                ],
            },
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_outcomes, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        row = data["rows"][0]
        assert row["positive_outcomes"] == 2
        assert row["negative_outcomes"] == 1
        # 100 + 50 + (-25) = 125
        assert row["revenue"] == 125.0
        assert row["outcome_count"] == 3

    def test_rollup_sums_across_rows(self, cli):
        q = _fake_queue(
            rows=[
                _row(id_="x1", from_store="a", store_id="b"),
                _row(id_="x2", from_store="a", store_id="b",
                     action_type="other_action"),
            ],
            outcomes={
                "x1": [
                    {"polarity": "positive",
                     "metrics": {"revenue": 100.0}},
                ],
                "x2": [
                    {"polarity": "negative",
                     "metrics": {"revenue": -10.0}},
                    {"polarity": "neutral", "metrics": {}},
                ],
            },
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_transfer_outcomes, _ns(json=True),
            )
        data = json.loads(out)
        rollup = data["rollup"]
        assert rollup["positive_total"] == 1
        assert rollup["negative_total"] == 1
        assert rollup["neutral_total"] == 1
        assert rollup["revenue_total"] == 90.0
        assert rollup["actions_with_outcomes"] == 2
        assert rollup["actions_without_outcomes"] == 0

    def test_action_without_outcomes_still_surfaces(self, cli):
        """A transferred + executed action that hasn't yet matched
        any downstream event is itself an important signal: 'we
        applied this transfer but the feedback loop hasn't fired
        yet'. Must surface, not drop."""
        q = _fake_queue(
            rows=[_row(id_="no_outcome", from_store="a")],
            outcomes={"no_outcome": []},
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_outcomes, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["count"] == 1
        row = data["rows"][0]
        assert row["outcome_count"] == 0
        # Rollup distinguishes "has outcomes" vs "doesn't".
        assert data["rollup"]["actions_without_outcomes"] == 1
        assert data["rollup"]["actions_with_outcomes"] == 0


# ─── Filter behaviour ────────────────────────────────────────


class TestFilters:

    def test_from_filter_narrows_clientside(self, cli):
        q = _fake_queue(
            rows=[
                _row(id_="A", from_store="alpha", store_id="b"),
                _row(id_="B", from_store="gamma", store_id="b"),
            ],
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_outcomes,
                _ns(from_store="alpha", json=True),
            )
        data = json.loads(out)
        assert data["count"] == 1
        assert data["rows"][0]["action_id"] == "A"

    def test_to_filter_propagates_to_sql(self, cli):
        q = _fake_queue(rows=[
            _row(id_="x", from_store="a", store_id="beta"),
        ])
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            _capture(
                cli._cmd_transfer_outcomes,
                _ns(to_store="beta", json=True),
            )
        call = q._conn.execute.call_args
        sql, params = call.args
        assert "store_id = ?" in sql
        assert "beta" in params

    def test_engine_filter_propagates_to_sql(self, cli):
        q = _fake_queue(rows=[
            _row(id_="x", engine="loyalty"),
        ])
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            _capture(
                cli._cmd_transfer_outcomes,
                _ns(engine="loyalty", json=True),
            )
        call = q._conn.execute.call_args
        sql, params = call.args
        assert "engine = ?" in sql
        assert "loyalty" in params

    def test_status_executed_is_in_sql(self, cli):
        """The SQL must restrict to status=EXECUTED -- the whole
        point of this view is "did the transfer pay off after it
        ran?". A PENDING transfer has no outcomes to read yet."""
        q = _fake_queue(rows=[])
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            _capture(
                cli._cmd_transfer_outcomes, _ns(json=True),
            )
        call = q._conn.execute.call_args
        sql, _ = call.args
        assert "status = 'executed'" in sql


# ─── Resilience ──────────────────────────────────────────────


class TestResilience:

    def test_get_outcomes_raise_keeps_row(self, cli):
        """If outcomes lookup raises, the row should still surface
        with outcome_count=0, not crash the whole report."""
        q = _fake_queue(
            rows=[_row(id_="x", from_store="a")],
            get_outcomes_raises=RuntimeError("outcomes table missing"),
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_outcomes, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["count"] == 1
        assert data["rows"][0]["outcome_count"] == 0

    def test_scan_failure_surfaces_clean_error(self, cli):
        q = _fake_queue(scan_raises=RuntimeError("db locked"))
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_outcomes, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["status"] == "error"
        assert "db locked" in data["error"]


# ─── JSON envelope shape ─────────────────────────────────────


class TestJsonEnvelope:

    def test_envelope_fields(self, cli):
        q = _fake_queue(
            rows=[_row(id_="x", from_store="a", store_id="b")],
            outcomes={"x": [
                {"polarity": "positive",
                 "metrics": {"revenue": 75.0}},
            ]},
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_transfer_outcomes,
                _ns(
                    from_store="a", to_store="b",
                    engine="loyalty", limit=10, json=True,
                ),
            )
        data = json.loads(out)
        for k in ("filters", "count", "rollup", "rows"):
            assert k in data
        for k in (
            "from_store", "to_store", "engine", "limit",
        ):
            assert k in data["filters"]
        for k in (
            "actions_with_outcomes",
            "actions_without_outcomes",
            "positive_total", "negative_total",
            "neutral_total", "revenue_total",
        ):
            assert k in data["rollup"]
        for k in (
            "action_id", "engine", "action_type", "capability",
            "from_store", "to_store", "decided_at",
            "outcome_count", "positive_outcomes",
            "negative_outcomes", "revenue",
        ):
            assert k in data["rows"][0]


# ─── Text mode rendering ─────────────────────────────────────


class TestTextMode:

    def test_text_mode_shows_polarity_signs(self, cli):
        q = _fake_queue(
            rows=[_row(id_="x1", from_store="alpha", store_id="beta")],
            outcomes={"x1": [
                {"polarity": "positive",
                 "metrics": {"revenue": 30.0}},
                {"polarity": "positive",
                 "metrics": {"revenue": 20.0}},
            ]},
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_outcomes, _ns(),
            )
        assert code == 0
        # "+2" polarity badge
        assert "+2" in out
        # Revenue
        assert "rev=$50" in out
        # Rollup line
        assert "Rollup:" in out

    def test_text_mode_marks_no_outcomes_yet(self, cli):
        q = _fake_queue(
            rows=[_row(id_="x1", from_store="alpha", store_id="beta")],
            outcomes={"x1": []},
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_transfer_outcomes, _ns(),
            )
        assert "no outcomes yet" in out
