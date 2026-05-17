"""Tests for ``shopai transfer credit`` — CLI surface for the
``core.transfer_credit`` attribution module.

Focuses on CLI-specific behaviour (argument plumbing, envelope
shape, text rendering). The underlying credit-graph computation
is covered in ``tests/test_transfer_credit.py`` +
``tests/test_transfer_credit_integration.py``.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from core.transfer_credit import TransferCredit


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
        source_store="", engine="", limit=20, json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _credit(
    *, source_store="store-a", engine="loyalty",
    action_type="mint_loyalty_code",
    transfer_count=2, executed_count=2,
    positive_outcomes=2, negative_outcomes=0,
    revenue=100.0, score=1.0,
):
    return TransferCredit(
        source_store=source_store,
        engine=engine,
        action_type=action_type,
        transfer_count=transfer_count,
        executed_count=executed_count,
        positive_outcomes=positive_outcomes,
        negative_outcomes=negative_outcomes,
        revenue=revenue,
        score=score,
    )


# ─── Empty state ─────────────────────────────────────────────


class TestEmptyState:

    def test_no_credits_text_friendly(self, cli):
        with patch(
            "core.transfer_credit.compute_transfer_credits",
            return_value=[],
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=MagicMock(),
        ):
            out, code = _capture(
                cli._cmd_transfer_credit, _ns(),
            )
        assert code == 0
        assert "No transfer credit" in out

    def test_no_credits_json_envelope(self, cli):
        with patch(
            "core.transfer_credit.compute_transfer_credits",
            return_value=[],
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=MagicMock(),
        ):
            out, code = _capture(
                cli._cmd_transfer_credit, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["total_returned"] == 0
        assert data["total_keys"] == 0
        assert data["rows"] == []
        assert "filters" in data


# ─── Rows surfaced ───────────────────────────────────────────


class TestRowsSurfaced:

    def test_credits_listed_in_json_envelope(self, cli):
        credits = [
            _credit(
                source_store="store-a", engine="loyalty",
                action_type="mint_loyalty_code",
                transfer_count=3, executed_count=3,
                positive_outcomes=2, negative_outcomes=1,
                revenue=75.0, score=2/3,
            ),
        ]
        with patch(
            "core.transfer_credit.compute_transfer_credits",
            return_value=credits,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=MagicMock(),
        ):
            out, code = _capture(
                cli._cmd_transfer_credit, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["total_returned"] == 1
        row = data["rows"][0]
        assert row["source_store"] == "store-a"
        assert row["engine"] == "loyalty"
        assert row["action_type"] == "mint_loyalty_code"
        assert row["transfer_count"] == 3
        assert row["positive_outcomes"] == 2
        assert row["negative_outcomes"] == 1
        assert row["revenue"] == 75.0
        assert row["score"] == pytest.approx(2/3)

    def test_text_mode_lists_rows(self, cli):
        credits = [
            _credit(
                source_store="store-a", engine="loyalty",
                action_type="mint_loyalty_code",
                transfer_count=2, revenue=100.0,
            ),
        ]
        with patch(
            "core.transfer_credit.compute_transfer_credits",
            return_value=credits,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=MagicMock(),
        ):
            out, code = _capture(
                cli._cmd_transfer_credit, _ns(),
            )
        assert code == 0
        assert "Transfer credit" in out
        assert "store-a/loyalty/mint_loyalty_code" in out
        assert "transfers=2" in out
        assert "rev=$100" in out


# ─── Filters ─────────────────────────────────────────────────


class TestFilters:

    def test_source_store_propagates(self, cli):
        mock_compute = MagicMock(return_value=[])
        with patch(
            "core.transfer_credit.compute_transfer_credits",
            mock_compute,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=MagicMock(),
        ):
            _capture(
                cli._cmd_transfer_credit,
                _ns(source_store="store-a", json=True),
            )
        kw = mock_compute.call_args.kwargs
        assert kw["source_store"] == "store-a"

    def test_empty_source_store_becomes_none(self, cli):
        """Operator passing the default empty string should NOT
        propagate -- otherwise the module's filter narrows to a
        ``source_store == ''`` match which surfaces nothing."""
        mock_compute = MagicMock(return_value=[])
        with patch(
            "core.transfer_credit.compute_transfer_credits",
            mock_compute,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=MagicMock(),
        ):
            _capture(
                cli._cmd_transfer_credit,
                _ns(source_store="", json=True),
            )
        kw = mock_compute.call_args.kwargs
        assert kw["source_store"] is None

    def test_engine_propagates(self, cli):
        mock_compute = MagicMock(return_value=[])
        with patch(
            "core.transfer_credit.compute_transfer_credits",
            mock_compute,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=MagicMock(),
        ):
            _capture(
                cli._cmd_transfer_credit,
                _ns(engine="loyalty", json=True),
            )
        kw = mock_compute.call_args.kwargs
        assert kw["engine"] == "loyalty"


# ─── Limit applied client-side ───────────────────────────────


class TestLimit:

    def test_limit_truncates_rows(self, cli):
        """The module returns up to 500 credits; the CLI's
        --limit narrows to the operator-requested top-N."""
        credits = [
            _credit(
                source_store=f"store-{i}", engine="loyalty",
                action_type="mint",
                transfer_count=10 - i,  # ranked desc
            )
            for i in range(8)
        ]
        with patch(
            "core.transfer_credit.compute_transfer_credits",
            return_value=credits,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=MagicMock(),
        ):
            out, _ = _capture(
                cli._cmd_transfer_credit,
                _ns(limit=3, json=True),
            )
        data = json.loads(out)
        assert data["total_returned"] == 3
        # Underlying scan saw 8 keys total.
        assert data["total_keys"] == 8


# ─── Resilience ──────────────────────────────────────────────


class TestResilience:

    def test_compute_raise_surfaces_error(self, cli):
        with patch(
            "core.transfer_credit.compute_transfer_credits",
            side_effect=RuntimeError("db locked"),
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=MagicMock(),
        ):
            out, code = _capture(
                cli._cmd_transfer_credit, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert "db locked" in data["error"]

    def test_score_none_renders_as_na(self, cli):
        """A source action with no polarised outcomes yet has
        ``score=None``; text mode should render 'n/a' rather
        than crash on the percentage format."""
        credits = [
            _credit(
                source_store="store-a", engine="loyalty",
                action_type="mint",
                positive_outcomes=0, negative_outcomes=0,
                score=None,
            ),
        ]
        with patch(
            "core.transfer_credit.compute_transfer_credits",
            return_value=credits,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=MagicMock(),
        ):
            out, code = _capture(
                cli._cmd_transfer_credit, _ns(),
            )
        assert code == 0
        assert "score=n/a" in out
