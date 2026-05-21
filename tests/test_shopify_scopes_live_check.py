"""Tests for the live scope health check + CLI.

The check calls Shopify's ``currentAppInstallation { accessScopes }``
API via the apps adapter, compares granted scopes vs the
registry's declared scopes, and reports any drift. Catches
install-time misconfiguration before individual adapters start
failing with ACCESS_DENIED.

Tests use a mock adapter to inject synthetic granted-scopes
sets and exercise every branch of the comparison.
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
    defaults = dict(json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _mock_adapter(scopes: list[str], ok: bool = True):
    """Build a mock adapter whose ``execute`` returns a result
    with the given access_scopes."""
    adapter = MagicMock()
    adapter.is_configured.return_value = True
    result = MagicMock()
    result.ok = ok
    result.data = {"access_scopes": scopes} if ok else {}
    result.error = "fake error" if not ok else None
    adapter.execute.return_value = result
    return adapter


# ─── compare_to_live() ─────────────────────────────────────────


class TestCompareToLive:

    def test_healthy_when_granted_matches_required(self):
        from core.adapters.shopify.scope_health import compare_to_live
        from core.adapters.shopify.scope_registry import all_required_scopes
        live = sorted(all_required_scopes())
        adapter = _mock_adapter(live)
        report = compare_to_live(adapter=adapter)
        assert report is not None
        assert report.is_healthy is True
        assert report.missing_from_app == []
        assert report.extra_in_app == []

    def test_missing_when_granted_is_subset(self):
        from core.adapters.shopify.scope_health import compare_to_live
        # Grant only a subset → missing_from_app populated
        adapter = _mock_adapter(["read_orders"])
        report = compare_to_live(adapter=adapter)
        assert report is not None
        assert report.is_healthy is False
        assert len(report.missing_from_app) > 0
        # read_orders was granted, so it shouldn't appear missing
        assert "read_orders" not in report.missing_from_app

    def test_extra_when_granted_has_unknown_scopes(self):
        from core.adapters.shopify.scope_health import compare_to_live
        from core.adapters.shopify.scope_registry import all_required_scopes
        granted = sorted(all_required_scopes()) + [
            "read_some_unknown_thing",
        ]
        adapter = _mock_adapter(granted)
        report = compare_to_live(adapter=adapter)
        assert report is not None
        # Extras don't break health
        assert report.is_healthy is True
        assert "read_some_unknown_thing" in report.extra_in_app

    def test_both_missing_and_extra(self):
        """Comprehensive drift: some required scopes not granted,
        some granted scopes not in the registry."""
        from core.adapters.shopify.scope_health import compare_to_live
        adapter = _mock_adapter([
            "read_orders", "read_some_extra_scope",
        ])
        report = compare_to_live(adapter=adapter)
        assert report is not None
        assert report.is_healthy is False
        assert "read_some_extra_scope" in report.extra_in_app
        assert len(report.missing_from_app) > 0

    def test_returns_none_on_adapter_failure(self):
        from core.adapters.shopify.scope_health import compare_to_live
        adapter = _mock_adapter([], ok=False)
        report = compare_to_live(adapter=adapter)
        assert report is None

    def test_returns_none_on_unconfigured_adapter(self):
        from core.adapters.shopify.scope_health import compare_to_live
        adapter = MagicMock()
        adapter.is_configured.return_value = False
        report = compare_to_live(adapter=adapter)
        assert report is None

    def test_returns_none_on_adapter_exception(self):
        from core.adapters.shopify.scope_health import compare_to_live
        adapter = MagicMock()
        adapter.is_configured.return_value = True
        adapter.execute.side_effect = RuntimeError("network down")
        report = compare_to_live(adapter=adapter)
        assert report is None

    def test_returns_none_on_malformed_data(self):
        """If the apps adapter returns ok=True but missing the
        access_scopes key, fail to None rather than guessing."""
        from core.adapters.shopify.scope_health import compare_to_live
        adapter = MagicMock()
        adapter.is_configured.return_value = True
        result = MagicMock()
        result.ok = True
        result.data = {"wrong_key": []}
        adapter.execute.return_value = result
        report = compare_to_live(adapter=adapter)
        assert report is None

    def test_empty_strings_in_granted_filtered_out(self):
        """Defensive: empty / whitespace-only scope strings in
        the response don't poison the comparison."""
        from core.adapters.shopify.scope_health import compare_to_live
        from core.adapters.shopify.scope_registry import all_required_scopes
        granted = sorted(all_required_scopes()) + ["", "  ", ""]
        adapter = _mock_adapter(granted)
        report = compare_to_live(adapter=adapter)
        assert report is not None
        assert "" not in report.granted_scopes
        assert "  " not in report.granted_scopes


# ─── CLI ───────────────────────────────────────────────────────


class TestCli:

    def test_no_live_data_exits_0_text(self, cli):
        with patch(
            "core.adapters.shopify.scope_health.compare_to_live",
            return_value=None,
        ):
            out, code = _capture(
                cli._cmd_shopify_scopes_live_check, _ns(),
            )
        assert code == 0
        assert "unavailable" in out.lower()

    def test_no_live_data_exits_0_json(self, cli):
        with patch(
            "core.adapters.shopify.scope_health.compare_to_live",
            return_value=None,
        ):
            out, code = _capture(
                cli._cmd_shopify_scopes_live_check,
                _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is None
        assert data["error"] == "live_data_unavailable"

    def test_healthy_exits_0(self, cli):
        from core.adapters.shopify.scope_health import ScopeHealthReport
        report = ScopeHealthReport(
            granted_scopes=frozenset({"read_orders"}),
            required_scopes=frozenset({"read_orders"}),
            missing_from_app=[],
            extra_in_app=[],
            is_healthy=True,
        )
        with patch(
            "core.adapters.shopify.scope_health.compare_to_live",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_shopify_scopes_live_check, _ns(),
            )
        assert code == 0
        assert "OK" in out

    def test_missing_scopes_exits_1(self, cli):
        from core.adapters.shopify.scope_health import ScopeHealthReport
        report = ScopeHealthReport(
            granted_scopes=frozenset({"read_orders"}),
            required_scopes=frozenset({
                "read_orders", "write_orders",
            }),
            missing_from_app=["write_orders"],
            extra_in_app=[],
            is_healthy=False,
        )
        with patch(
            "core.adapters.shopify.scope_health.compare_to_live",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_shopify_scopes_live_check, _ns(),
            )
        assert code == 1
        assert "FAILED" in out
        assert "write_orders" in out
        # Fix instruction surfaces
        assert "shopify-install-manifest" in out

    def test_missing_scopes_json_exits_1(self, cli):
        from core.adapters.shopify.scope_health import ScopeHealthReport
        report = ScopeHealthReport(
            granted_scopes=frozenset({"read_orders"}),
            required_scopes=frozenset({
                "read_orders", "write_orders",
            }),
            missing_from_app=["write_orders"],
            extra_in_app=[],
            is_healthy=False,
        )
        with patch(
            "core.adapters.shopify.scope_health.compare_to_live",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_shopify_scopes_live_check,
                _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["ok"] is False
        assert "write_orders" in data["missing_from_app"]

    def test_extras_only_exits_0_with_warning(self, cli):
        """is_healthy=True + extras → warning, not fatal.
        Over-requesting is a code-review issue, not a runtime
        failure."""
        from core.adapters.shopify.scope_health import ScopeHealthReport
        report = ScopeHealthReport(
            granted_scopes=frozenset({
                "read_orders", "read_unused_scope",
            }),
            required_scopes=frozenset({"read_orders"}),
            missing_from_app=[],
            extra_in_app=["read_unused_scope"],
            is_healthy=True,
        )
        with patch(
            "core.adapters.shopify.scope_health.compare_to_live",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_shopify_scopes_live_check, _ns(),
            )
        assert code == 0
        assert "warning" in out.lower()
        assert "read_unused_scope" in out
        # Over-requesting fix points at the manifest regen
        assert "install-manifest" in out

    def test_missing_and_extras_renders_both(self, cli):
        from core.adapters.shopify.scope_health import ScopeHealthReport
        report = ScopeHealthReport(
            granted_scopes=frozenset({
                "read_orders", "read_unused",
            }),
            required_scopes=frozenset({
                "read_orders", "write_orders",
            }),
            missing_from_app=["write_orders"],
            extra_in_app=["read_unused"],
            is_healthy=False,
        )
        with patch(
            "core.adapters.shopify.scope_health.compare_to_live",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_shopify_scopes_live_check, _ns(),
            )
        assert code == 1
        assert "write_orders" in out
        assert "read_unused" in out

    def test_exception_in_check_renders_unavailable(self, cli):
        """A raised exception from compare_to_live (rather than
        returning None) still falls through to the unavailable
        path — CLI never crashes on a live-data failure."""
        with patch(
            "core.adapters.shopify.scope_health.compare_to_live",
            side_effect=RuntimeError("boom"),
        ):
            out, code = _capture(
                cli._cmd_shopify_scopes_live_check, _ns(),
            )
        assert code == 0
        assert "unavailable" in out.lower()

    def test_successful_check_writes_cache(self, cli):
        """After a successful comparison the CLI must call
        save_report_to_cache so daily-brief can read it later."""
        from core.adapters.shopify.scope_health import ScopeHealthReport
        report = ScopeHealthReport(
            granted_scopes=frozenset({"read_orders"}),
            required_scopes=frozenset({"read_orders"}),
            missing_from_app=[],
            extra_in_app=[],
            is_healthy=True,
        )
        with patch(
            "core.adapters.shopify.scope_health.compare_to_live",
            return_value=report,
        ), patch(
            "core.adapters.shopify.scope_health.save_report_to_cache",
        ) as save:
            _capture(cli._cmd_shopify_scopes_live_check, _ns())
        save.assert_called_once_with(report)

    def test_check_unavailable_does_not_write_cache(self, cli):
        """When compare_to_live returns None there's nothing to
        cache; save_report_to_cache must NOT be called."""
        with patch(
            "core.adapters.shopify.scope_health.compare_to_live",
            return_value=None,
        ), patch(
            "core.adapters.shopify.scope_health.save_report_to_cache",
        ) as save:
            _capture(cli._cmd_shopify_scopes_live_check, _ns())
        save.assert_not_called()
