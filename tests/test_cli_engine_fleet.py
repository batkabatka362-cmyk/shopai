"""Tests for ``shopai engine fleet <engine>`` -- empire-AGI
'where is this engine winning / losing across the fleet?'
diagnostic.

For one engine, count activity (executed / failed / pending) +
outcomes (positive / negative / revenue) per store.

Covers:

  - engine_name required
  - No activity → known stores still surface (zero rows)
  - Activity attributed to the right store
  - Outcomes rolled per store (executed actions only)
  - outcome_score = positive / (positive+negative); None when no
    polarised events
  - Ranking: most-active first; ties broken by executed >
    revenue > store_id
  - Window respected: out-of-window rows excluded
  - Queue scan failure → clean error
  - JSON envelope shape
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
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
        engine_name="loyalty",
        window_hours=168, json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_sm(store_ids):
    sm = MagicMock()
    sm.list_stores.return_value = [
        {"store_id": sid, "shop_url": f"{sid}.myshopify.com"}
        for sid in store_ids
    ]
    return sm


def _row(*, id_, store_id, status, decided_at=None,
         proposed_at=None):
    if decided_at is None and status != "pending":
        decided_at = time.time() - 3600.0
    if proposed_at is None:
        proposed_at = time.time() - 3700.0
    return {
        "id": id_,
        "store_id": store_id,
        "status": status,
        "decided_at": decided_at,
        "proposed_at": proposed_at,
    }


def _fake_queue(rows=None, outcomes=None, scan_raises=None):
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
    q.get_outcomes.side_effect = lambda aid: outcomes.get(aid, [])
    return q


# ─── Arg validation ──────────────────────────────────────────


class TestArgValidation:

    def test_missing_engine_name_fails(self, cli):
        out, code = _capture(
            cli._cmd_engine_fleet, _ns(engine_name=""),
        )
        assert code == 1
        assert "engine_name is required" in out


# ─── Empty activity ──────────────────────────────────────────


class TestEmptyActivity:

    def test_known_stores_surface_with_zero_activity(self, cli):
        """Even when no actions match the engine, every known
        fleet store should appear with zero counters -- helps
        operators see 'this engine has never run on these
        stores'."""
        sm = _fake_sm(["a", "b", "c"])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows=[]),
        ):
            out, code = _capture(
                cli._cmd_engine_fleet, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        sids = {b["store_id"] for b in data["stores"]}
        assert sids == {"a", "b", "c"}
        for b in data["stores"]:
            assert b["executed"] == 0
            assert b["outcome_score"] is None


# ─── Activity attribution ────────────────────────────────────


class TestActivityAttribution:

    def test_executed_failed_pending_split_per_store(self, cli):
        sm = _fake_sm(["a", "b"])
        rows = [
            _row(id_="x1", store_id="a", status="executed"),
            _row(id_="x2", store_id="a", status="executed"),
            _row(id_="x3", store_id="a", status="failed"),
            _row(id_="x4", store_id="b", status="executed"),
            _row(id_="x5", store_id="b", status="pending",
                 decided_at=None,
                 proposed_at=time.time() - 60.0),
        ]
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows=rows),
        ):
            out, _ = _capture(
                cli._cmd_engine_fleet, _ns(json=True),
            )
        data = json.loads(out)
        by_id = {b["store_id"]: b for b in data["stores"]}
        assert by_id["a"]["executed"] == 2
        assert by_id["a"]["failed"] == 1
        assert by_id["a"]["pending"] == 0
        assert by_id["b"]["executed"] == 1
        assert by_id["b"]["pending"] == 1

    def test_unscoped_rows_bucket_separately(self, cli):
        """Pre-#239 rows without store_id should bucket into an
        ``(unscoped)`` group rather than vanishing."""
        sm = _fake_sm([])
        rows = [
            _row(id_="x1", store_id=None, status="executed"),
        ]
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows=rows),
        ):
            out, _ = _capture(
                cli._cmd_engine_fleet, _ns(json=True),
            )
        data = json.loads(out)
        sids = {b["store_id"] for b in data["stores"]}
        assert "(unscoped)" in sids


# ─── Outcome aggregation ─────────────────────────────────────


class TestOutcomes:

    def test_outcome_score_computed_per_store(self, cli):
        sm = _fake_sm(["a", "b"])
        rows = [
            _row(id_="x1", store_id="a", status="executed"),
            _row(id_="x2", store_id="b", status="executed"),
        ]
        outcomes = {
            "x1": [
                {"polarity": "positive",
                 "metrics": {"revenue": 100.0}},
                {"polarity": "positive",
                 "metrics": {"revenue": 50.0}},
                {"polarity": "negative", "metrics": {}},
            ],
            "x2": [
                {"polarity": "negative",
                 "metrics": {"revenue": -25.0}},
                {"polarity": "negative", "metrics": {}},
            ],
        }
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows=rows, outcomes=outcomes),
        ):
            out, _ = _capture(
                cli._cmd_engine_fleet, _ns(json=True),
            )
        data = json.loads(out)
        by_id = {b["store_id"]: b for b in data["stores"]}
        # Store-a: 2 pos / (2 pos + 1 neg) = 66.67%
        assert by_id["a"]["positive_outcomes"] == 2
        assert by_id["a"]["negative_outcomes"] == 1
        assert by_id["a"]["outcome_score"] == pytest.approx(2 / 3)
        # Store-b: 0 pos / (0+2) = 0%
        assert by_id["b"]["outcome_score"] == 0.0
        # Revenue: store-a = 150, store-b = -25
        assert by_id["a"]["revenue"] == 150.0
        assert by_id["b"]["revenue"] == -25.0

    def test_outcome_score_none_when_no_polarised_events(self, cli):
        """A store with executions but no recorded outcomes
        should produce score=None, not a divide-by-zero."""
        sm = _fake_sm(["a"])
        rows = [_row(id_="x", store_id="a", status="executed")]
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows=rows, outcomes={}),
        ):
            out, _ = _capture(
                cli._cmd_engine_fleet, _ns(json=True),
            )
        data = json.loads(out)
        a = next(b for b in data["stores"] if b["store_id"] == "a")
        assert a["outcome_score"] is None

    def test_failed_rows_do_not_poll_outcomes(self, cli):
        """Only EXECUTED rows contribute to polarity counts;
        FAILED rows count toward failed only."""
        sm = _fake_sm(["a"])
        rows = [_row(id_="x", store_id="a", status="failed")]
        # Outcomes dict has an entry but it shouldn't be read.
        outcomes = {"x": [
            {"polarity": "positive", "metrics": {"revenue": 9999}},
        ]}
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows=rows, outcomes=outcomes),
        ):
            out, _ = _capture(
                cli._cmd_engine_fleet, _ns(json=True),
            )
        data = json.loads(out)
        a = next(b for b in data["stores"] if b["store_id"] == "a")
        # Polarity counters stay at zero -- proves we didn't
        # poll outcomes for the failed row.
        assert a["positive_outcomes"] == 0
        assert a["revenue"] == 0.0
        assert a["failed"] == 1


# ─── Ranking ─────────────────────────────────────────────────


class TestRanking:

    def test_most_active_store_first(self, cli):
        sm = _fake_sm(["quiet", "active", "medium"])
        rows = (
            [_row(id_=f"a{i}", store_id="active", status="executed")
             for i in range(5)]
            + [_row(id_=f"m{i}", store_id="medium", status="executed")
               for i in range(2)]
        )
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows=rows),
        ):
            out, _ = _capture(
                cli._cmd_engine_fleet, _ns(json=True),
            )
        data = json.loads(out)
        ranked = [b["store_id"] for b in data["stores"]]
        assert ranked.index("active") < ranked.index("medium")
        assert ranked.index("medium") < ranked.index("quiet")


# ─── Rollup ──────────────────────────────────────────────────


class TestRollup:

    def test_rollup_totals_match_per_store_sum(self, cli):
        sm = _fake_sm(["a", "b"])
        rows = [
            _row(id_="x1", store_id="a", status="executed"),
            _row(id_="x2", store_id="b", status="executed"),
            _row(id_="x3", store_id="a", status="failed"),
        ]
        outcomes = {
            "x1": [
                {"polarity": "positive",
                 "metrics": {"revenue": 75.0}},
            ],
            "x2": [
                {"polarity": "negative",
                 "metrics": {"revenue": -10.0}},
            ],
        }
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows=rows, outcomes=outcomes),
        ):
            out, _ = _capture(
                cli._cmd_engine_fleet, _ns(json=True),
            )
        data = json.loads(out)
        r = data["rollup"]
        assert r["total_executed"] == 2
        assert r["total_failed"] == 1
        assert r["total_positive"] == 1
        assert r["total_negative"] == 1
        assert r["total_revenue"] == 65.0
        assert r["stores_with_activity"] == 2


# ─── Resilience ──────────────────────────────────────────────


class TestResilience:

    def test_scan_failure_surfaces_clean_error(self, cli):
        sm = _fake_sm(["a"])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(
                scan_raises=RuntimeError("db locked"),
            ),
        ):
            out, code = _capture(
                cli._cmd_engine_fleet, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["status"] == "error"
        assert "db locked" in data["error"]

    def test_get_outcomes_raise_keeps_row(self, cli):
        sm = _fake_sm(["a"])
        rows = [_row(id_="x", store_id="a", status="executed")]
        q = _fake_queue(rows=rows)
        q.get_outcomes.side_effect = RuntimeError("outcomes table missing")
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_engine_fleet, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        a = next(b for b in data["stores"] if b["store_id"] == "a")
        # Row still counted as executed; outcomes stay zero.
        assert a["executed"] == 1
        assert a["positive_outcomes"] == 0


# ─── JSON envelope ───────────────────────────────────────────


class TestJsonEnvelope:

    def test_envelope_shape(self, cli):
        sm = _fake_sm(["a"])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows=[]),
        ):
            out, _ = _capture(
                cli._cmd_engine_fleet,
                _ns(engine_name="loyalty", window_hours=48,
                    json=True),
            )
        data = json.loads(out)
        assert data["engine"] == "loyalty"
        assert data["window_hours"] == 48
        for k in (
            "stores_with_activity", "total_executed",
            "total_failed", "total_pending", "total_positive",
            "total_negative", "total_revenue",
        ):
            assert k in data["rollup"]
        for k in (
            "store_id", "executed", "failed", "pending",
            "positive_outcomes", "negative_outcomes",
            "outcome_score", "revenue",
        ):
            assert k in data["stores"][0]
