"""Tests for ``shopai approvals outcome`` -- manual outcome
recording for actions whose Shopify webhooks missed or for
retroactive corrections.

Verifies:

  - Unknown action_id surfaces a clean error
  - Happy path: queue.record_outcome called with correct args
  - Revenue + metrics envelope shape
  - record_outcome returning False surfaces an error
  - JSON envelope shape
  - Queue lookup failure surfaces clean error
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
        action_id="appr_1",
        polarity="positive",
        revenue=0.0,
        topic="manual",
        source_event="operator",
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_queue(*, action=None, record_returns=True,
                record_raises=None, get_raises=None):
    q = MagicMock()
    if get_raises is not None:
        q.get.side_effect = get_raises
    else:
        q.get.return_value = action
    if record_raises is not None:
        q.record_outcome.side_effect = record_raises
    else:
        q.record_outcome.return_value = record_returns
    return q


def _action(*, id_="appr_1", engine="loyalty",
            action_type="mint_loyalty_code"):
    a = MagicMock()
    a.id = id_
    a.engine = engine
    a.action_type = action_type
    return a


# ─── Unknown action ──────────────────────────────────────────


class TestUnknownAction:

    def test_missing_action_surfaces_error(self, cli):
        q = _fake_queue(action=None)
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_approvals_outcome,
                _ns(action_id="appr_missing"),
            )
        assert code == 1
        assert "not found" in out
        # record_outcome must NOT be called when action is missing.
        q.record_outcome.assert_not_called()


# ─── Happy path ──────────────────────────────────────────────


class TestHappyPath:

    def test_basic_outcome_recorded(self, cli):
        a = _action(id_="appr_x", engine="loyalty",
                    action_type="mint_loyalty_code")
        q = _fake_queue(action=a)
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_approvals_outcome,
                _ns(
                    action_id="appr_x",
                    polarity="positive",
                    revenue=42.5,
                    topic="orders/create",
                    source_event="operator-1",
                    json=True,
                ),
            )
        assert code == 0
        data = json.loads(out)
        assert data["status"] == "ok"
        assert data["action_id"] == "appr_x"
        assert data["polarity"] == "positive"
        assert data["topic"] == "orders/create"
        assert data["source_event"] == "operator-1"
        # Engine + action_type populated from the looked-up action.
        assert data["engine"] == "loyalty"
        assert data["action_type"] == "mint_loyalty_code"
        # Metrics carries revenue + manual marker.
        assert data["metrics"]["revenue"] == 42.5
        assert data["metrics"]["manually_recorded"] is True
        # record_outcome was called with the expected args.
        kwargs = q.record_outcome.call_args.kwargs
        assert kwargs["polarity"] == "positive"
        assert kwargs["topic"] == "orders/create"
        assert kwargs["metrics"]["revenue"] == 42.5
        assert kwargs["source_event"] == "operator-1"

    def test_zero_revenue_omitted_from_metrics(self, cli):
        """When revenue is 0 (the default), it shouldn't pollute
        metrics — only the ``manually_recorded`` flag should be
        there."""
        a = _action()
        q = _fake_queue(action=a)
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_approvals_outcome,
                _ns(revenue=0.0, json=True),
            )
        data = json.loads(out)
        assert "revenue" not in data["metrics"]
        assert data["metrics"]["manually_recorded"] is True

    def test_negative_revenue_supported(self, cli):
        """Refund-like outcomes have negative revenue."""
        a = _action()
        q = _fake_queue(action=a)
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_approvals_outcome,
                _ns(
                    polarity="negative",
                    revenue=-25.0,
                    json=True,
                ),
            )
        data = json.loads(out)
        assert data["metrics"]["revenue"] == -25.0
        assert data["polarity"] == "negative"

    def test_text_mode_prints_summary(self, cli):
        a = _action(engine="cart_recovery",
                    action_type="mint_cart_recovery_code")
        q = _fake_queue(action=a)
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_approvals_outcome,
                _ns(
                    action_id="appr_xyz",
                    polarity="positive",
                    revenue=15.0,
                ),
            )
        assert code == 0
        assert "Outcome recorded" in out
        assert "cart_recovery/mint_cart_recovery_code" in out
        assert "polarity=positive" in out
        assert "rev" in out.lower()


# ─── Failure paths ───────────────────────────────────────────


class TestFailurePaths:

    def test_get_raises_surfaces_error(self, cli):
        q = _fake_queue(get_raises=RuntimeError("db locked"))
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_approvals_outcome, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert "db locked" in data["error"]

    def test_record_outcome_raises_surfaces_error(self, cli):
        a = _action()
        q = _fake_queue(
            action=a,
            record_raises=RuntimeError("constraint failed"),
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_approvals_outcome, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert "record_outcome failed" in data["error"]

    def test_record_outcome_returns_false_surfaces_error(self, cli):
        """``queue.record_outcome`` returns False when the action
        isn't in a state to accept outcomes (e.g. not executed).
        Surface that to the operator instead of silently
        succeeding."""
        a = _action()
        q = _fake_queue(action=a, record_returns=False)
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_approvals_outcome, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert (
            "returned falsy" in data["error"]
            or "not be executed" in data["error"]
        )
