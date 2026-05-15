"""Tests for the enriched ``shopai engine-info <name>`` command.

Earlier `engine-info` showed name + class + brain stack. The
enriched version adds:

  - Writeback wiring status (wired / advisory / partial) +
    writer files + opt-in flags (from `engines._writeback_audit`)
  - Action chain emitted by this engine (from
    `core.approval.catalog`): action_type, capability,
    claiming adapter, required scopes

Both fields are best-effort — if the underlying audits fail, the
engine-info section just omits them rather than crashing.

Tests cover:
  - Wired engine renders writeback + action sections
  - Advisory engine renders writeback section only
  - JSON envelope includes writeback + actions fields
  - Unknown engine still exits 1
"""
from __future__ import annotations

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


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


# ─── Wired engine ──────────────────────────────────────────────


class TestWiredEngine:

    def test_loyalty_renders_writeback_section(self, cli):
        out, code = _capture(
            cli._cmd_engine_info, "loyalty", False,
        )
        assert code == 0
        assert "Engine: loyalty" in out
        assert "Writeback:" in out
        assert "wired" in out
        assert "discount_minter.py" in out
        # Opt-in flag surfaces
        assert "apply_rewards" in out

    def test_loyalty_renders_action_chain(self, cli):
        out, _ = _capture(
            cli._cmd_engine_info, "loyalty", False,
        )
        # Full chain rendered: action_type, capability, adapter,
        # scopes
        assert "Actions emitted" in out
        assert "mint_loyalty_code" in out
        assert "SHOPIFY_CREATE_DISCOUNT" in out
        assert "shopify_discount" in out
        assert "write_discounts" in out

    def test_dynamic_pricing_renders_chain(self, cli):
        """Different engine, different capability — confirm the
        chain is rendered correctly regardless of engine."""
        out, _ = _capture(
            cli._cmd_engine_info, "dynamic_pricing", False,
        )
        assert "apply_price_change" in out
        assert "SHOPIFY_UPDATE_VARIANTS" in out


# ─── Advisory engine ──────────────────────────────────────────


class TestAdvisoryEngine:

    def test_advisory_engine_renders_status(self, cli):
        out, code = _capture(
            cli._cmd_engine_info, "auto_research", False,
        )
        assert code == 0
        assert "Writeback:" in out
        assert "advisory" in out
        # No actions section for advisory engines
        assert "Actions emitted" not in out


# ─── JSON envelope ────────────────────────────────────────────


class TestJsonEnvelope:

    def test_json_includes_writeback_and_actions(self, cli):
        out, code = _capture(
            cli._cmd_engine_info, "loyalty", True,
        )
        assert code == 0
        data = json.loads(out)
        assert data["name"] == "loyalty"
        # Writeback section
        assert "writeback" in data
        assert data["writeback"]["status"] == "wired"
        assert "discount_minter.py" in data["writeback"]["writer_files"]
        # Actions section
        assert "actions" in data
        assert len(data["actions"]) >= 1
        action = data["actions"][0]
        assert action["action_type"] == "mint_loyalty_code"
        assert action["capability"] == "SHOPIFY_CREATE_DISCOUNT"
        assert action["adapter"] == "shopify_discount"

    def test_json_advisory_engine_no_actions_key(self, cli):
        out, _ = _capture(
            cli._cmd_engine_info, "auto_research", True,
        )
        data = json.loads(out)
        # Advisory engine — writeback present but no actions
        assert "writeback" in data
        assert data["writeback"]["status"] == "advisory"
        assert "actions" not in data


# ─── Error handling ───────────────────────────────────────────


class TestErrorHandling:

    def test_unknown_engine_exits_1(self, cli):
        out, code = _capture(
            cli._cmd_engine_info, "totally_fake_engine_name", False,
        )
        assert code == 1
        assert "Unknown engine" in out

    def test_audit_failure_omits_writeback_section(self, cli):
        """If the writeback audit module raises, engine-info
        should degrade silently — render the basic fields and
        skip the writeback / actions sections."""
        with patch(
            "engines._writeback_audit.audit_writeback_coverage",
            side_effect=RuntimeError("audit broken"),
        ):
            out, code = _capture(
                cli._cmd_engine_info, "loyalty", False,
            )
        assert code == 0
        # Basic fields still rendered
        assert "Engine: loyalty" in out
        # Writeback section skipped (graceful)
        assert "Writeback:" not in out

    def test_catalog_failure_omits_action_chain(self, cli):
        """Symmetric: if the catalog build raises, the actions
        section is silently skipped."""
        with patch(
            "core.approval.catalog.build_catalog",
            side_effect=RuntimeError("catalog broken"),
        ):
            out, code = _capture(
                cli._cmd_engine_info, "loyalty", False,
            )
        assert code == 0
        # Basic fields still rendered
        assert "Engine: loyalty" in out
        # Action chain section skipped (graceful)
        assert "Actions emitted" not in out
