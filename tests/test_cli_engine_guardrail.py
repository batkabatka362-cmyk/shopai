"""Tests for ``shopai engine guardrail`` -- the operator
visibility surface for the AGI v2 guardrail rollout.

Reads env-var state per engine + scans pending_actions for
``decision_reason LIKE 'agi_guardrail_blocked:%'`` to count
recent blocks per engine.
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
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit:
        pass
    return buf.getvalue()


def _ns(**kw):
    defaults = dict(window_hours=24, json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── State rendering ─────────────────────────────────────────


class TestStateRender:

    def test_all_off_default(self, cli, monkeypatch):
        for engine in (
            "loyalty", "cart_recovery", "browse_recovery",
            "email_marketing", "wholesale_b2b", "discount_strategy",
        ):
            monkeypatch.delenv(
                f"SHOPAI_{engine.upper()}_AGI_GUARDRAIL",
                raising=False,
            )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=MagicMock(_conn=MagicMock()),
        ):
            out = _capture(cli._cmd_engine_guardrail, _ns())
        assert "0/6 engine(s) enabled" in out
        # Hint shown when all off
        assert "Enable any engine via env var" in out

    def test_enabled_engines_marked(self, cli, monkeypatch):
        monkeypatch.setenv("SHOPAI_LOYALTY_AGI_GUARDRAIL", "1")
        monkeypatch.setenv("SHOPAI_CART_RECOVERY_AGI_GUARDRAIL", "1")
        for other in (
            "browse_recovery", "email_marketing",
            "wholesale_b2b", "discount_strategy",
        ):
            monkeypatch.delenv(
                f"SHOPAI_{other.upper()}_AGI_GUARDRAIL",
                raising=False,
            )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=MagicMock(_conn=MagicMock()),
        ):
            out = _capture(cli._cmd_engine_guardrail, _ns())
        assert "2/6 engine(s) enabled" in out
        assert "*loyalty" in out
        assert "*cart_recovery" in out
        # Disabled engines are NOT prefixed with *
        assert "*browse_recovery" not in out


# ─── Block-count window ──────────────────────────────────────


class TestBlockCount:

    def test_block_counts_grouped_by_engine(self, cli, monkeypatch):
        monkeypatch.setenv("SHOPAI_LOYALTY_AGI_GUARDRAIL", "1")
        # Fake queue row response: 3 loyalty blocks, 1 cart_recovery
        rows = [
            {"engine": "loyalty", "n": 3},
            {"engine": "cart_recovery", "n": 1},
        ]
        fake_conn = MagicMock()
        # Context manager protocol for ``with queue._conn:``
        fake_conn.__enter__ = lambda self: self
        fake_conn.__exit__ = lambda *a: None
        fake_cursor = MagicMock()
        fake_cursor.fetchall.return_value = rows
        fake_conn.execute.return_value = fake_cursor
        queue = MagicMock()
        queue._conn = fake_conn
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=queue,
        ):
            out = _capture(
                cli._cmd_engine_guardrail, _ns(json=True),
            )
        data = json.loads(out)
        by_engine = {e["engine"]: e for e in data["engines"]}
        assert by_engine["loyalty"]["blocks_in_window"] == 3
        assert by_engine["cart_recovery"]["blocks_in_window"] == 1
        # Untouched engines stay at 0
        assert by_engine["browse_recovery"]["blocks_in_window"] == 0


# ─── JSON envelope ───────────────────────────────────────────


class TestJsonShape:

    def test_envelope_includes_window_and_per_engine(
        self, cli, monkeypatch,
    ):
        monkeypatch.setenv("SHOPAI_LOYALTY_AGI_GUARDRAIL", "1")
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=MagicMock(_conn=MagicMock()),
        ):
            out = _capture(
                cli._cmd_engine_guardrail,
                _ns(window_hours=48, json=True),
            )
        data = json.loads(out)
        assert data["window_hours"] == 48
        # All 6 engines surface
        engines = {e["engine"] for e in data["engines"]}
        assert engines == {
            "loyalty", "cart_recovery", "browse_recovery",
            "email_marketing", "wholesale_b2b", "discount_strategy",
        }
        # Each entry has all 4 fields
        for e in data["engines"]:
            assert "engine" in e
            assert "guardrail_enabled" in e
            assert "blocks_in_window" in e
            assert "env_var" in e


# ─── Resilience ──────────────────────────────────────────────


class TestResilience:

    def test_queue_unavailable_still_renders(self, cli, monkeypatch):
        """If the queue is unavailable, block counts default to 0
        but the env-var state still renders."""
        monkeypatch.setenv("SHOPAI_LOYALTY_AGI_GUARDRAIL", "1")
        with patch(
            "core.approval.queue.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            out = _capture(cli._cmd_engine_guardrail, _ns(json=True))
        data = json.loads(out)
        # State still surfaced; blocks fall back to 0
        loyalty = next(
            e for e in data["engines"] if e["engine"] == "loyalty"
        )
        assert loyalty["guardrail_enabled"] is True
        assert loyalty["blocks_in_window"] == 0
