"""Tests for ``shopai approvals show`` outcome embedding.

The CLI ``show`` verb's JSON payload now embeds the action's
downstream outcomes inline for EXECUTED actions (the only state
that can have webhook outcomes). Operators see the full picture
in one command — "this action ran, here's its result, and here's
what customers did with it."

Default: outcomes embedded for EXECUTED actions.
``--no-outcomes``: skip the embed (compact mode for large
outcome histories).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest


def _load_cli():
    spec = importlib.util.spec_from_file_location("shopai_cli", "cli.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli():
    return _load_cli()


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue
    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


def _seed_executed_with_outcomes(queue):
    """Helper: enqueue + approve + execute + add 2 outcomes."""
    a = queue.enqueue(
        engine="cart_recovery", action_type="mint_code",
        capability="X", params={"token": "cust1"},
        narrative="test", confidence=0.85,
    )
    queue.approve(a.id, decided_by="op")
    queue.attach_result(
        a.id, success=True, result={"code": "RECOV-1"},
    )
    queue.record_outcome(
        a.id, topic="orders/create", polarity="positive",
        metrics={"revenue": 50.0}, source_event="order_1",
    )
    queue.record_outcome(
        a.id, topic="refunds/create", polarity="negative",
        metrics={"revenue": 10.0}, source_event="refund_1",
    )
    return a


class TestShowEmbedsOutcomes:

    def test_executed_action_embeds_outcomes_by_default(
        self, cli, isolated_queue,
    ):
        a = _seed_executed_with_outcomes(isolated_queue)
        out, code = _capture(
            cli._cmd_approvals_show,
            argparse.Namespace(
                action_id=a.id, no_outcomes=False,
                json=True,
            ),
        )
        assert code == 0
        data = json.loads(out)
        assert "outcomes" in data
        assert len(data["outcomes"]) == 2
        topics = {o["topic"] for o in data["outcomes"]}
        assert topics == {"orders/create", "refunds/create"}

    def test_no_outcomes_flag_skips_embedding(
        self, cli, isolated_queue,
    ):
        a = _seed_executed_with_outcomes(isolated_queue)
        out, _ = _capture(
            cli._cmd_approvals_show,
            argparse.Namespace(
                action_id=a.id, no_outcomes=True,
                json=True,
            ),
        )
        data = json.loads(out)
        assert "outcomes" not in data

    def test_pending_action_no_outcomes_field(
        self, cli, isolated_queue,
    ):
        """PENDING actions never have outcomes — the field is
        skipped entirely (not embedded as empty list)."""
        a = isolated_queue.enqueue(
            engine="x", action_type="y", capability="z",
            params={}, narrative="",
        )
        out, _ = _capture(
            cli._cmd_approvals_show,
            argparse.Namespace(
                action_id=a.id, no_outcomes=False,
                json=True,
            ),
        )
        data = json.loads(out)
        assert data["status"] == "pending"
        assert "outcomes" not in data

    def test_approved_but_not_executed_no_outcomes(
        self, cli, isolated_queue,
    ):
        a = isolated_queue.enqueue(
            engine="x", action_type="y", capability="z",
            params={}, narrative="",
        )
        isolated_queue.approve(a.id)
        out, _ = _capture(
            cli._cmd_approvals_show,
            argparse.Namespace(
                action_id=a.id, no_outcomes=False,
                json=True,
            ),
        )
        data = json.loads(out)
        assert data["status"] == "approved"
        assert "outcomes" not in data

    def test_executed_with_zero_outcomes_embeds_empty_list(
        self, cli, isolated_queue,
    ):
        """An EXECUTED action without any matched webhook
        outcomes still gets ``outcomes: []`` — callers can
        rely on the field's presence."""
        a = isolated_queue.enqueue(
            engine="x", action_type="y", capability="z",
            params={}, narrative="",
        )
        isolated_queue.approve(a.id)
        isolated_queue.attach_result(
            a.id, success=True, result={"code": "X"},
        )
        out, _ = _capture(
            cli._cmd_approvals_show,
            argparse.Namespace(
                action_id=a.id, no_outcomes=False,
                json=True,
            ),
        )
        data = json.loads(out)
        assert data["outcomes"] == []


class TestExistingBehavior:

    def test_unknown_id_exits_1(self, cli, isolated_queue):
        out, code = _capture(
            cli._cmd_approvals_show,
            argparse.Namespace(
                action_id="appr_does_not_exist",
                no_outcomes=False,
                json=True,
            ),
        )
        assert code == 1
        assert "Unknown action id" in out

    def test_outcome_lookup_failure_returns_empty(
        self, cli, isolated_queue,
    ):
        """``get_outcomes`` raising leaves outcomes=[] rather
        than failing the show command."""
        a = isolated_queue.enqueue(
            engine="x", action_type="y", capability="z",
            params={}, narrative="",
        )
        isolated_queue.approve(a.id)
        isolated_queue.attach_result(
            a.id, success=True, result={"code": "X"},
        )
        with patch.object(
            isolated_queue, "get_outcomes",
            side_effect=RuntimeError("db lock"),
        ):
            out, code = _capture(
                cli._cmd_approvals_show,
                argparse.Namespace(
                    action_id=a.id, no_outcomes=False,
                    json=True,
                ),
            )
        assert code == 0
        data = json.loads(out)
        assert data["outcomes"] == []
