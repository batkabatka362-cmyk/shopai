"""Tests for the Pattern Y capability coverage audit + CLI.

Pattern Y mirrors Pattern K (PR #157 dispatcher coverage): every
``Capability.SHOPIFY_*`` enum value should be claimed by at
least one registered adapter. Catches two regression classes:

  1. Enum value added without an adapter wireup → engines
     routing to it hit AdapterNotConfigured.
  2. Adapter declares a "capability" string that doesn't exist
     on the enum → module load crash (defensive belt-and-braces).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from unittest.mock import patch

import pytest

from core.adapters.base import Capability
from core.adapters.shopify._base import ShopifyBaseAdapter


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
    defaults = dict(json=False, show_multi_claimed=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── Synthetic adapter fixtures ────────────────────────────────


class _OrdersOnlyAdapter(ShopifyBaseAdapter):
    name = "fake_orders_only"
    capabilities = {Capability.SHOPIFY_LIST_ORDERS}

    def __init__(self) -> None:
        pass


class _OrdersAlsoAdapter(ShopifyBaseAdapter):
    """Claims the same capability as _OrdersOnlyAdapter — used
    to exercise multi_claimed reporting."""
    name = "fake_orders_also"
    capabilities = {Capability.SHOPIFY_LIST_ORDERS}

    def __init__(self) -> None:
        pass


class _OrphanClaimsAdapter(ShopifyBaseAdapter):
    """Claims a string that's not a Capability enum value —
    exercises the orphan-claims detection."""
    name = "fake_orphan"
    capabilities = {"not_a_real_capability"}

    def __init__(self) -> None:
        pass


# ─── audit_capability_coverage() ───────────────────────────────


class TestAuditCoverage:

    def test_live_audit_passes(self):
        """The actual bootstrap state must pass the audit —
        regression guard. If this fails, a new SHOPIFY_*
        enum value landed without a matching adapter."""
        from core.adapters.coverage_audit import (
            audit_capability_coverage,
        )
        report = audit_capability_coverage()
        assert report.has_gaps is False
        assert report.unclaimed == []
        assert report.orphan_claims == []

    def test_single_adapter_claims_subset(self):
        from core.adapters.coverage_audit import (
            audit_capability_coverage,
        )
        report = audit_capability_coverage(
            adapter_classes=(_OrdersOnlyAdapter,),
        )
        # 380 SHOPIFY_* enum values; only one claimed
        assert report.total_shopify_capabilities > 1
        assert report.claimed_count == 1
        assert "SHOPIFY_LIST_ORDERS" not in report.unclaimed
        # Most other capabilities are unclaimed
        assert len(report.unclaimed) > 100
        assert report.has_gaps is True

    def test_multi_claimed_detected(self):
        from core.adapters.coverage_audit import (
            audit_capability_coverage,
        )
        report = audit_capability_coverage(
            adapter_classes=(_OrdersOnlyAdapter, _OrdersAlsoAdapter),
        )
        # Reported with enum NAME (uppercase) — same form as
        # unclaimed; keeps the audit output self-consistent.
        assert "SHOPIFY_LIST_ORDERS" in report.multi_claimed
        # Sorted alphabetically
        assert report.multi_claimed["SHOPIFY_LIST_ORDERS"] == [
            "fake_orders_also", "fake_orders_only",
        ]

    def test_orphan_claims_detected(self):
        from core.adapters.coverage_audit import (
            audit_capability_coverage,
        )
        report = audit_capability_coverage(
            adapter_classes=(_OrphanClaimsAdapter,),
        )
        assert "not_a_real_capability" in report.orphan_claims
        assert report.has_gaps is True

    def test_empty_adapter_tuple(self):
        from core.adapters.coverage_audit import (
            audit_capability_coverage,
        )
        report = audit_capability_coverage(adapter_classes=())
        # Every shopify capability unclaimed
        assert len(report.unclaimed) == (
            report.total_shopify_capabilities
        )
        assert report.has_gaps is True


# ─── Synthetic regression scenario ─────────────────────────────


class _UnclaimedEnumAdapter(ShopifyBaseAdapter):
    """Doesn't claim everything — leaves SHOPIFY_LIST_ORDERS
    unclaimed (used to assert the unclaimed-list is populated)."""

    name = "fake_partial"
    capabilities = {Capability.SHOPIFY_GET_ORDER}

    def __init__(self) -> None:
        pass


class TestUnclaimedRegression:

    def test_unwired_enum_value_surfaces(self):
        """Simulate a new SHOPIFY_X added without a matching
        adapter — the audit must surface it in the unclaimed
        list. Bootstrap patching exercises the real chain."""
        from core.adapters import coverage_audit
        from core.adapters.shopify import bootstrap

        # Patch bootstrap to a minimal set that leaves most
        # enum values unclaimed
        with patch.object(
            bootstrap, "_SHOPIFY_ADAPTER_CLASSES",
            (_UnclaimedEnumAdapter,),
        ):
            report = coverage_audit.audit_capability_coverage()
        # SHOPIFY_GET_ORDER is claimed
        assert "SHOPIFY_GET_ORDER" not in report.unclaimed
        # SHOPIFY_LIST_ORDERS isn't — surfaces in unclaimed
        assert "SHOPIFY_LIST_ORDERS" in report.unclaimed
        assert report.has_gaps is True


# ─── CLI ───────────────────────────────────────────────────────


class TestCli:

    def test_live_audit_exits_0(self, cli):
        """The live registry passes the audit today."""
        out, code = _capture(
            cli._cmd_capabilities_audit, _ns(),
        )
        assert code == 0
        assert "Capability coverage OK" in out

    def test_gap_exits_1(self, cli):
        from core.adapters import coverage_audit
        from core.adapters.shopify import bootstrap

        with patch.object(
            bootstrap, "_SHOPIFY_ADAPTER_CLASSES",
            (_OrdersOnlyAdapter,),
        ):
            out, code = _capture(
                cli._cmd_capabilities_audit, _ns(),
            )
        assert code == 1
        assert "FAILED" in out
        assert "unclaimed" in out.lower()
        # Remediation hint surfaces
        assert "core/adapters/shopify" in out

    def test_orphan_claim_in_output(self, cli):
        from core.adapters.shopify import bootstrap
        with patch.object(
            bootstrap, "_SHOPIFY_ADAPTER_CLASSES",
            (_OrphanClaimsAdapter,),
        ):
            out, code = _capture(
                cli._cmd_capabilities_audit, _ns(),
            )
        assert code == 1
        assert "orphan" in out.lower()
        assert "not_a_real_capability" in out

    def test_json_pass(self, cli):
        out, code = _capture(
            cli._cmd_capabilities_audit, _ns(json=True),
        )
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is True
        assert data["unclaimed"] == []
        assert data["orphan_claims"] == []

    def test_json_fail_exits_1(self, cli):
        from core.adapters.shopify import bootstrap
        with patch.object(
            bootstrap, "_SHOPIFY_ADAPTER_CLASSES",
            (_OrdersOnlyAdapter,),
        ):
            out, code = _capture(
                cli._cmd_capabilities_audit,
                _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["ok"] is False
        assert len(data["unclaimed"]) > 0

    def test_show_multi_claimed_text(self, cli):
        """--show-multi-claimed surfaces the multi-claim list
        in the OK path."""
        out, _ = _capture(
            cli._cmd_capabilities_audit,
            _ns(show_multi_claimed=True),
        )
        # Live registry has no multi-claimed currently
        assert "Multi-claimed" in out or "No multi-claimed" in out

    def test_show_multi_claimed_json(self, cli):
        """JSON mode + --show-multi-claimed includes the field."""
        out, _ = _capture(
            cli._cmd_capabilities_audit,
            _ns(json=True, show_multi_claimed=True),
        )
        data = json.loads(out)
        assert "multi_claimed" in data

    def test_json_default_omits_multi_claimed(self, cli):
        """Without --show-multi-claimed, the json envelope
        doesn't include the field — keeps the CI consumer clean."""
        out, _ = _capture(
            cli._cmd_capabilities_audit, _ns(json=True),
        )
        data = json.loads(out)
        assert "multi_claimed" not in data

    def test_module_failure_renders_text_unavailable(self, cli):
        with patch(
            "core.adapters.coverage_audit.audit_capability_coverage",
            side_effect=RuntimeError("module broken"),
        ):
            out, code = _capture(
                cli._cmd_capabilities_audit, _ns(),
            )
        assert code == 0
        assert "unavailable" in out.lower()
