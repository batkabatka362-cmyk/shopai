"""Tests for the ``--json`` mode + final summary line added to
``shopai store configure``.

The configurator itself already had thorough coverage in
``test_store_configurator.py``. This file covers the CLI layer's
new behavior:

  - ``--json`` emits an envelope including store_id, niche,
    dry_run, feature_count, and the full configurator result.
  - Text mode includes a final ``Summary:`` line for at-a-glance
    verdict.
  - Error paths (no store, no creds) route through both render
    modes cleanly.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from unittest.mock import patch, MagicMock

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
        store_id=None,
        dry_run=False,
        only="",
        niche="",
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_store_manager(
    *,
    active_store="test-store",
    shop_url="example.myshopify.com",
    api_key="shpat_token",
    niche="beauty",
):
    """Build a MagicMock that quacks like the StoreManager
    surface the configurator command consumes."""
    sm = MagicMock()
    sm.active_store_id = active_store
    sm.get_credentials.return_value = {
        "shop_url": shop_url,
        "api_key": api_key,
    }
    sm.db.get_store.return_value = {
        "name": active_store,
        "niche": niche,
    }
    return sm


def _fake_configurator_result(
    *,
    status="planned",
    niche="beauty",
    features=None,
    results=None,
    plan=None,
):
    return {
        "status": status,
        "niche": niche,
        "features": features or ["collections"],
        "results": results or {
            "collections": {"created": 5, "existing": 0},
        },
        "plan": plan or [
            {
                "method": "POST",
                "path": "smart_collections.json",
                "description": "Create 'Best Sellers'",
            },
        ],
    }


# ─── --json mode ────────────────────────────────────────────


class TestJsonMode:

    def test_json_emits_envelope_with_context_fields(self, cli):
        sm = _fake_store_manager()
        result = _fake_configurator_result()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            configurator_cls.return_value.configure.return_value = result
            out, code = _capture(
                cli._cmd_store_configure,
                _ns(dry_run=True, only="collections", json=True),
            )
        assert code == 0
        data = json.loads(out)
        # Envelope context
        assert data["store_id"] == "test-store"
        assert data["niche"] == "beauty"
        assert data["dry_run"] is True
        assert data["feature_count"] == 1
        # Full configurator result is preserved
        assert data["status"] == "planned"
        assert "collections" in data["results"]
        assert data["plan"][0]["method"] == "POST"

    def test_json_first_char_is_brace(self, cli):
        """JSON output must be jq-parseable -- first non-whitespace
        char is ``{``."""
        sm = _fake_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            configurator_cls.return_value.configure.return_value = (
                _fake_configurator_result()
            )
            out, _ = _capture(
                cli._cmd_store_configure,
                _ns(dry_run=True, json=True),
            )
        assert out.lstrip()[0] == "{"
        # No human-readable banner before the JSON
        assert "Dry-run:" not in out
        assert "Status:" not in out

    def test_json_dry_run_flag_carries_through(self, cli):
        """The dry_run flag in the envelope mirrors the CLI flag."""
        sm = _fake_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            configurator_cls.return_value.configure.return_value = (
                _fake_configurator_result()
            )
            out, _ = _capture(
                cli._cmd_store_configure,
                _ns(dry_run=False, json=True),
            )
        data = json.loads(out)
        assert data["dry_run"] is False


# ─── Text-mode summary line ─────────────────────────────────


class TestTextSummary:

    def test_dry_run_summary_shows_plan_count(self, cli):
        sm = _fake_store_manager()
        result = _fake_configurator_result(
            results={
                "collections": {"created": 5},
                "discounts": {"created": 3},
            },
            plan=[
                {"method": "POST", "path": "p", "description": "d"}
                for _ in range(8)
            ],
        )
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            configurator_cls.return_value.configure.return_value = result
            out, _ = _capture(
                cli._cmd_store_configure,
                _ns(dry_run=True),
            )
        assert "Summary: 2 feature(s) planned, 8 write(s) staged" in out

    def test_applied_summary_shows_status(self, cli):
        sm = _fake_store_manager()
        result = _fake_configurator_result(
            status="applied",
            results={"collections": {"created": 5}},
        )
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            configurator_cls.return_value.configure.return_value = result
            out, _ = _capture(
                cli._cmd_store_configure,
                _ns(dry_run=False),
            )
        assert "Summary: 1 feature(s) applied" in out
        assert "status=applied" in out

    def test_summary_hints_json_flag(self, cli):
        """The summary line nudges operators toward --json for
        scripting -- a small UX affordance."""
        sm = _fake_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            configurator_cls.return_value.configure.return_value = (
                _fake_configurator_result()
            )
            out, _ = _capture(
                cli._cmd_store_configure,
                _ns(dry_run=True),
            )
        assert "--json" in out


# ─── Error paths route through both modes ────────────────────


class TestErrorPaths:

    def test_no_active_store_text(self, cli):
        sm = MagicMock()
        sm.active_store_id = None
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out, code = _capture(
                cli._cmd_store_configure, _ns(),
            )
        # Returns cleanly without crashing
        assert "No store specified" in out
        # Text mode -- not JSON
        assert not out.lstrip().startswith("{")

    def test_no_active_store_json(self, cli):
        sm = MagicMock()
        sm.active_store_id = None
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out, code = _capture(
                cli._cmd_store_configure, _ns(json=True),
            )
        data = json.loads(out)
        assert data["status"] == "error"
        assert "No store specified" in data["error"]

    def test_missing_credentials_json(self, cli):
        sm = MagicMock()
        sm.active_store_id = "test-store"
        sm.get_credentials.return_value = {"shop_url": "x"}
        # token missing, no client_id
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out, code = _capture(
                cli._cmd_store_configure, _ns(json=True),
            )
        data = json.loads(out)
        assert data["status"] == "error"
        assert "credentials" in data["error"].lower()

    def test_no_creds_text_mode_unchanged(self, cli):
        """Default text mode still prints the human-readable
        error line -- no regression for existing operators."""
        sm = MagicMock()
        sm.active_store_id = "test-store"
        sm.get_credentials.return_value = None
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out, _ = _capture(
                cli._cmd_store_configure, _ns(),
            )
        assert "not found" in out or "shop_url" in out
