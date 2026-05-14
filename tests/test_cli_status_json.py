"""Tests for ``shopai status --json`` and the underlying
``_build_status_dict`` helper.

The default text view is operator-friendly but monitoring tools
need a parseable representation. The --json flag swaps the table
render for ``json.dumps`` of the same payload, so a single
command works for both human and machine consumers.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
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


def _capture(fn, *args, **kwargs) -> str:
    buf = StringIO()
    with patch("sys.stdout", buf):
        fn(*args, **kwargs)
    return buf.getvalue()


# ─── _build_status_dict ──────────────────────────────────────────


class TestBuildStatusDict:

    def test_returns_known_shape(self, cli):
        """Payload exposes the top-level keys downstream consumers
        will depend on. Schema is part of the contract."""
        payload = cli._build_status_dict()
        for key in (
            "engines",
            "stores_count",
            "active_store",
            "stores",
            "auto_sync_running",
            "sync_stores",
        ):
            assert key in payload, f"missing key: {key}"

    def test_engines_is_int(self, cli):
        payload = cli._build_status_dict()
        assert isinstance(payload["engines"], int)
        assert payload["engines"] > 0

    def test_stores_is_list_of_dicts(self, cli):
        payload = cli._build_status_dict()
        assert isinstance(payload["stores"], list)
        for s in payload["stores"]:
            for key in (
                "store_id", "active", "products",
                "orders", "customers", "total_revenue",
            ):
                assert key in s

    def test_sync_age_computed(self, cli):
        """When a store has a last_sync timestamp, the payload
        includes the age in seconds — saves consumers from
        re-computing now()-last_sync."""
        payload = cli._build_status_dict()
        for si in payload["sync_stores"]:
            if si["last_sync"] is not None:
                assert si["last_sync_age_seconds"] is not None
                assert si["last_sync_age_seconds"] >= 0


# ─── _cmd_status JSON mode ──────────────────────────────────────


class TestStatusJsonMode:

    def test_json_flag_emits_valid_json(self, cli):
        ns = argparse.Namespace(json=True)
        out = _capture(cli._cmd_status, ns)
        # Must round-trip cleanly
        data = json.loads(out)
        assert "engines" in data
        assert "stores" in data

    def test_json_flag_no_table_text(self, cli):
        """JSON mode emits ONLY JSON — no human-readable headers
        before/after. A monitoring tool piping the output to jq
        must not get garbage prefix."""
        ns = argparse.Namespace(json=True)
        out = _capture(cli._cmd_status, ns)
        # First non-whitespace char is '{' (or '[')
        first_char = out.strip()[0]
        assert first_char in ("{", "[")
        # No human banner text
        assert "ShopAI System Status" not in out
        assert "Store Data:" not in out

    def test_json_flag_explicit_false_falls_to_text(self, cli):
        ns = argparse.Namespace(json=False)
        out = _capture(cli._cmd_status, ns)
        # Human table view
        assert "ShopAI System Status" in out


# ─── _cmd_status text mode ──────────────────────────────────────


class TestStatusTextMode:

    def test_no_args_renders_table(self, cli):
        """Default invocation with no args still works — backward
        compat with callers that don't pass a Namespace."""
        out = _capture(cli._cmd_status)
        assert "ShopAI System Status" in out

    def test_text_view_unchanged(self, cli):
        """Text view's headers + format should match the
        original output."""
        out = _capture(cli._cmd_status, None)
        # Key sections still present
        assert "Engines:" in out
        assert "Stores:" in out
        assert "Active:" in out
        assert "Auto-sync:" in out
