"""Tests for ``shopai transfer history`` -- cross-store transfer
audit trail.

Scans ``pending_actions`` for actions whose narrative was written
by ``shopai transfer apply`` (starts with ``Transfer suggestion:``
or contains ``  ||  Transfer suggestion:`` for the operator-note
variant), parses out source store + to store + engine info, and
surfaces a chronological history.

Covers:

  - Empty queue → friendly no-history message + empty rows
  - Single row surfaces with parsed from_store
  - Operator-narrative-prefix variant still parses
  - Non-transfer actions (no narrative marker) excluded
  - --engine / --to / --from filters narrow the scan
  - --limit caps row count
  - Malformed narrative gracefully degrades (from_store="")
  - JSON envelope shape
  - Queue unavailable → clean error
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
        from_store="", to_store="", engine="",
        limit=20, json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _row(
    *, id_="appr_1", engine="loyalty",
    action_type="mint_loyalty_code",
    capability="SHOPIFY_CREATE_DISCOUNT",
    store_id="b", status="pending",
    narrative=None,
    proposed_at=None,
    decided_at=None,
    from_store="a",
):
    """Build a dict-like row matching what queue._conn returns."""
    if narrative is None:
        narrative = (
            f"Transfer suggestion: {engine}/{action_type} "
            f"from {from_store} to {store_id}. "
            f"Source had 1 prior successful run(s)."
        )
    if proposed_at is None:
        proposed_at = time.time() - 3600.0
    return {
        "id": id_,
        "engine": engine,
        "action_type": action_type,
        "capability": capability,
        "store_id": store_id,
        "status": status,
        "narrative": narrative,
        "proposed_at": proposed_at,
        "decided_at": decided_at,
    }


def _fake_queue(rows=None, raises=None):
    rows = rows or []
    q = MagicMock()
    fake_conn = MagicMock()
    fake_conn.__enter__ = lambda self: self
    fake_conn.__exit__ = lambda *a: None
    fake_cursor = MagicMock()
    if raises is not None:
        fake_conn.execute.side_effect = raises
    else:
        fake_cursor.fetchall.return_value = rows
        fake_conn.execute.return_value = fake_cursor
    q._conn = fake_conn
    return q


# ─── Narrative parser ────────────────────────────────────────


class TestNarrativeParser:

    def test_canonical_narrative_parses(self, cli):
        n = (
            "Transfer suggestion: loyalty/mint_loyalty_code "
            "from alpha to beta. Source had 2 prior successful run(s)."
        )
        assert (
            cli._parse_from_store_from_narrative(n) == "alpha"
        )

    def test_operator_prefix_narrative_parses(self, cli):
        n = (
            "black friday parity  ||  Transfer suggestion: "
            "loyalty/mint_loyalty_code from alpha to beta. "
            "Source had 1 prior successful run(s)."
        )
        assert (
            cli._parse_from_store_from_narrative(n) == "alpha"
        )

    def test_unknown_format_returns_empty(self, cli):
        assert cli._parse_from_store_from_narrative("") == ""
        assert (
            cli._parse_from_store_from_narrative("random text") == ""
        )
        # Marker present but no "from <A> to <B>"
        assert (
            cli._parse_from_store_from_narrative(
                "Transfer suggestion: loyalty/x. nothing else."
            ) == ""
        )


# ─── Empty / no-history ──────────────────────────────────────


class TestEmptyHistory:

    def test_empty_queue_renders_friendly(self, cli):
        q = _fake_queue(rows=[])
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_history, _ns(),
            )
        assert code == 0
        assert "No transfer history" in out

    def test_empty_queue_json_envelope(self, cli):
        q = _fake_queue(rows=[])
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_history, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["count"] == 0
        assert data["rows"] == []
        assert "filters" in data


# ─── Row population ──────────────────────────────────────────


class TestRowPopulation:

    def test_single_row_surfaces(self, cli):
        q = _fake_queue(rows=[_row(from_store="alpha", store_id="beta")])
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_history, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["count"] == 1
        row = data["rows"][0]
        assert row["engine"] == "loyalty"
        assert row["from_store"] == "alpha"
        assert row["to_store"] == "beta"
        assert row["status"] == "pending"

    def test_text_mode_lists_rows(self, cli):
        q = _fake_queue(rows=[
            _row(
                id_="appr_x", engine="loyalty",
                from_store="alpha", store_id="beta",
            ),
        ])
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_history, _ns(),
            )
        assert code == 0
        assert "Transfer history" in out
        assert "loyalty/mint_loyalty_code" in out
        assert "alpha -> beta" in out
        assert "[pending]" in out
        assert "appr_x" in out


# ─── Filter behaviour ────────────────────────────────────────


class TestFilters:

    def test_from_filter_narrows_clientside(self, cli):
        """``--from`` filters AFTER the narrative parse since the
        source store isn't in any indexed column."""
        q = _fake_queue(rows=[
            _row(from_store="alpha", store_id="beta", id_="A"),
            _row(from_store="gamma", store_id="beta", id_="B"),
        ])
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_history,
                _ns(from_store="alpha", json=True),
            )
        data = json.loads(out)
        assert data["count"] == 1
        assert data["rows"][0]["action_id"] == "A"

    def test_to_filter_propagates_to_sql(self, cli):
        """``--to`` matches the row's store_id (target store).
        The SQL should include the WHERE clause -- verified by
        the bound params reaching execute()."""
        q = _fake_queue(rows=[
            _row(from_store="alpha", store_id="beta"),
        ])
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            _capture(
                cli._cmd_transfer_history,
                _ns(to_store="beta", json=True),
            )
        call = q._conn.execute.call_args
        sql, params = call.args
        assert "store_id = ?" in sql
        assert "beta" in params

    def test_engine_filter_propagates_to_sql(self, cli):
        q = _fake_queue(rows=[_row(engine="loyalty")])
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            _capture(
                cli._cmd_transfer_history,
                _ns(engine="loyalty", json=True),
            )
        call = q._conn.execute.call_args
        sql, params = call.args
        assert "engine = ?" in sql
        assert "loyalty" in params

    def test_limit_propagates_to_sql(self, cli):
        q = _fake_queue(rows=[])
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            _capture(
                cli._cmd_transfer_history,
                _ns(limit=7, json=True),
            )
        call = q._conn.execute.call_args
        _, params = call.args
        # Limit is always the LAST bound param.
        assert params[-1] == 7


# ─── Malformed narrative ─────────────────────────────────────


class TestMalformedNarrative:

    def test_narrative_without_from_to_keeps_row(self, cli):
        """A row that matched the SQL LIKE but parses badly should
        still surface (with from_store='') -- losing the row entirely
        would hide a real audit-trail entry from the operator."""
        q = _fake_queue(rows=[
            _row(
                from_store="ignored",
                narrative=(
                    "Transfer suggestion: loyalty/x. malformed end."
                ),
            ),
        ])
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_history, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["count"] == 1
        assert data["rows"][0]["from_store"] == ""


# ─── Resilience ──────────────────────────────────────────────


class TestResilience:

    def test_queue_scan_failure_surfaces_error(self, cli):
        q = _fake_queue(raises=RuntimeError("db locked"))
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_history, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["status"] == "error"
        assert "db locked" in data["error"]

    def test_queue_import_failure_surfaces_error(self, cli):
        """``get_approval_queue`` import path missing should produce
        a clean error envelope, not a stack trace."""
        with patch(
            "core.approval.queue.get_approval_queue",
            side_effect=ImportError("core.approval.queue missing"),
        ):
            out, code = _capture(
                cli._cmd_transfer_history, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["status"] == "error"


# ─── JSON envelope shape ─────────────────────────────────────


class TestJsonEnvelope:

    def test_envelope_fields(self, cli):
        q = _fake_queue(rows=[
            _row(from_store="alpha", store_id="beta"),
        ])
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_transfer_history,
                _ns(
                    from_store="alpha", to_store="beta",
                    engine="loyalty", limit=5, json=True,
                ),
            )
        data = json.loads(out)
        for key in ("filters", "count", "rows"):
            assert key in data
        for key in ("from_store", "to_store", "engine", "limit"):
            assert key in data["filters"]
        assert data["filters"]["from_store"] == "alpha"
        assert data["filters"]["limit"] == 5
        for key in (
            "action_id", "engine", "action_type", "capability",
            "from_store", "to_store", "status", "proposed_at",
            "narrative",
        ):
            assert key in data["rows"][0]
