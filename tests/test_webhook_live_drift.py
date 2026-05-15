"""Tests for the live webhook drift check + CLI surface.

Mirrors ``test_shopify_scopes_live_check.py`` for the webhook
surface. The check calls Shopify's
``webhookSubscriptions`` via the webhooks adapter, compares
registered topics vs the registry's declared set, and reports
drift. Catches outcome-attribution drift + GDPR review-blocking
gaps before they reach production.
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


def _mock_adapter(webhooks_payload: list[dict], ok: bool = True):
    """Build a mock webhooks adapter whose ``execute`` returns
    a result envelope with the given webhooks list."""
    adapter = MagicMock()
    adapter.is_configured.return_value = True
    result = MagicMock()
    result.ok = ok
    result.data = {"webhooks": webhooks_payload} if ok else {}
    result.error = "fake error" if not ok else None
    adapter.execute.return_value = result
    return adapter


def _wh(topic_enum: str) -> dict:
    """Build a fake webhook list entry matching the adapter's
    normalised shape (topic field is GraphQL enum form)."""
    return {"topic": topic_enum}


# ─── _enum_to_rest helper ──────────────────────────────────────


class TestEnumToRest:

    def test_basic_orders_create(self):
        from core.feedback.webhook_health import _enum_to_rest
        assert _enum_to_rest("ORDERS_CREATE") == "orders/create"

    def test_multi_underscore_preserved(self):
        from core.feedback.webhook_health import _enum_to_rest
        # customers/data_request → only first underscore is
        # the resource separator; rest stays joined
        assert (
            _enum_to_rest("CUSTOMERS_DATA_REQUEST")
            == "customers/data_request"
        )

    def test_no_underscore_returns_lowercase(self):
        from core.feedback.webhook_health import _enum_to_rest
        assert _enum_to_rest("APPCHARGE") == "appcharge"

    def test_empty_string_returns_empty(self):
        from core.feedback.webhook_health import _enum_to_rest
        assert _enum_to_rest("") == ""

    def test_non_string_returns_empty(self):
        from core.feedback.webhook_health import _enum_to_rest
        assert _enum_to_rest(None) == ""  # type: ignore[arg-type]


# ─── compare_to_live() ─────────────────────────────────────────


class TestCompareToLive:

    def test_healthy_when_registered_matches_declared(self):
        from core.feedback.webhook_health import compare_to_live
        from core.feedback.webhook_registry import all_topics
        # Build webhook payloads in the enum form Shopify returns
        topics_rest = list(all_topics())
        enum_payloads = [
            _wh(topic.upper().replace("/", "_"))
            for topic in topics_rest
        ]
        adapter = _mock_adapter(enum_payloads)
        report = compare_to_live(adapter=adapter)
        assert report is not None
        assert report.is_healthy is True
        assert report.missing_on_app == []
        assert report.extra_on_app == []
        assert report.gdpr_missing == []

    def test_missing_when_registered_subset(self):
        from core.feedback.webhook_health import compare_to_live
        # Only orders/create registered → other topics missing
        adapter = _mock_adapter([_wh("ORDERS_CREATE")])
        report = compare_to_live(adapter=adapter)
        assert report is not None
        assert report.is_healthy is False
        assert "orders/create" not in report.missing_on_app
        assert len(report.missing_on_app) > 0

    def test_gdpr_missing_surfaces_specifically(self):
        """GDPR topics get their own list — surfaced as a
        higher-priority alert in the CLI."""
        from core.feedback.webhook_health import compare_to_live
        # Register only the outcome topics; GDPR ones missing
        outcome_only = [
            _wh("ORDERS_CREATE"), _wh("ORDERS_PAID"),
            _wh("ORDERS_CANCELLED"), _wh("REFUNDS_CREATE"),
            _wh("APP_UNINSTALLED"),
        ]
        adapter = _mock_adapter(outcome_only)
        report = compare_to_live(adapter=adapter)
        assert report is not None
        assert "customers/data_request" in report.gdpr_missing
        assert "customers/redact" in report.gdpr_missing
        assert "shop/redact" in report.gdpr_missing

    def test_extra_when_registered_has_unknown(self):
        from core.feedback.webhook_health import compare_to_live
        from core.feedback.webhook_registry import all_topics
        declared_payloads = [
            _wh(t.upper().replace("/", "_"))
            for t in all_topics()
        ]
        # Add an extra topic not in the registry
        payloads = declared_payloads + [_wh("PRODUCTS_DELETE")]
        adapter = _mock_adapter(payloads)
        report = compare_to_live(adapter=adapter)
        assert report is not None
        assert report.is_healthy is True
        assert "products/delete" in report.extra_on_app

    def test_returns_none_on_adapter_failure(self):
        from core.feedback.webhook_health import compare_to_live
        adapter = _mock_adapter([], ok=False)
        report = compare_to_live(adapter=adapter)
        assert report is None

    def test_returns_none_on_unconfigured(self):
        from core.feedback.webhook_health import compare_to_live
        adapter = MagicMock()
        adapter.is_configured.return_value = False
        report = compare_to_live(adapter=adapter)
        assert report is None

    def test_returns_none_on_adapter_exception(self):
        from core.feedback.webhook_health import compare_to_live
        adapter = MagicMock()
        adapter.is_configured.return_value = True
        adapter.execute.side_effect = RuntimeError("network")
        report = compare_to_live(adapter=adapter)
        assert report is None

    def test_returns_none_on_malformed_data(self):
        from core.feedback.webhook_health import compare_to_live
        adapter = MagicMock()
        adapter.is_configured.return_value = True
        result = MagicMock()
        result.ok = True
        result.data = {"wrong_key": []}
        adapter.execute.return_value = result
        report = compare_to_live(adapter=adapter)
        assert report is None


# ─── CLI ───────────────────────────────────────────────────────


class TestCli:

    def test_no_live_data_exits_0(self, cli):
        with patch(
            "core.feedback.webhook_health.compare_to_live",
            return_value=None,
        ):
            out, code = _capture(
                cli._cmd_shopify_webhooks_live_check, _ns(),
            )
        assert code == 0
        assert "unavailable" in out.lower()

    def test_no_live_data_json(self, cli):
        with patch(
            "core.feedback.webhook_health.compare_to_live",
            return_value=None,
        ):
            out, _ = _capture(
                cli._cmd_shopify_webhooks_live_check,
                _ns(json=True),
            )
        data = json.loads(out)
        assert data["ok"] is None
        assert data["error"] == "live_data_unavailable"

    def test_healthy_exits_0(self, cli):
        from core.feedback.webhook_health import WebhookHealthReport
        report = WebhookHealthReport(
            registered_topics=frozenset({"orders/create"}),
            declared_topics=frozenset({"orders/create"}),
            missing_on_app=[],
            extra_on_app=[],
            gdpr_missing=[],
            is_healthy=True,
        )
        with patch(
            "core.feedback.webhook_health.compare_to_live",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_shopify_webhooks_live_check, _ns(),
            )
        assert code == 0
        assert "OK" in out

    def test_missing_exits_1(self, cli):
        from core.feedback.webhook_health import WebhookHealthReport
        report = WebhookHealthReport(
            registered_topics=frozenset({"orders/create"}),
            declared_topics=frozenset({
                "orders/create", "refunds/create",
            }),
            missing_on_app=["refunds/create"],
            extra_on_app=[],
            gdpr_missing=[],
            is_healthy=False,
        )
        with patch(
            "core.feedback.webhook_health.compare_to_live",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_shopify_webhooks_live_check, _ns(),
            )
        assert code == 1
        assert "FAILED" in out
        assert "refunds/create" in out
        # Fix instruction surfaces
        assert "shopify-webhook-manifest" in out

    def test_gdpr_missing_surfaces_alert(self, cli):
        from core.feedback.webhook_health import WebhookHealthReport
        report = WebhookHealthReport(
            registered_topics=frozenset(),
            declared_topics=frozenset({"shop/redact"}),
            missing_on_app=["shop/redact"],
            extra_on_app=[],
            gdpr_missing=["shop/redact"],
            is_healthy=False,
        )
        with patch(
            "core.feedback.webhook_health.compare_to_live",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_shopify_webhooks_live_check, _ns(),
            )
        assert code == 1
        assert "GDPR ALERT" in out
        assert "[GDPR-mandatory]" in out

    def test_extras_only_exits_0_with_warning(self, cli):
        from core.feedback.webhook_health import WebhookHealthReport
        report = WebhookHealthReport(
            registered_topics=frozenset({
                "orders/create", "products/delete",
            }),
            declared_topics=frozenset({"orders/create"}),
            missing_on_app=[],
            extra_on_app=["products/delete"],
            gdpr_missing=[],
            is_healthy=True,
        )
        with patch(
            "core.feedback.webhook_health.compare_to_live",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_shopify_webhooks_live_check, _ns(),
            )
        assert code == 0
        assert "warning" in out.lower()
        assert "products/delete" in out

    def test_exception_renders_unavailable(self, cli):
        with patch(
            "core.feedback.webhook_health.compare_to_live",
            side_effect=RuntimeError("boom"),
        ):
            out, code = _capture(
                cli._cmd_shopify_webhooks_live_check, _ns(),
            )
        assert code == 0
        assert "unavailable" in out.lower()


# ─── shopify-doctor integration ────────────────────────────────


class TestDoctorIntegration:

    def test_doctor_includes_webhook_section(self, cli):
        """The doctor's text render must include the new
        webhook-drift section."""
        out, code = _capture(
            cli._cmd_shopify_doctor,
            argparse.Namespace(json=False, skip_live=True),
        )
        assert code == 0
        assert "Live webhook drift" in out
        assert "[skip] Live webhook drift" in out

    def test_doctor_json_includes_webhook_section(self, cli):
        out, _ = _capture(
            cli._cmd_shopify_doctor,
            argparse.Namespace(json=True, skip_live=True),
        )
        data = json.loads(out)
        assert "live_webhook_drift" in data["sections"]

    def test_doctor_webhook_failure_fails_overall(self, cli):
        """A webhook drift failure on its own fails the doctor."""
        from core.feedback.webhook_health import WebhookHealthReport
        bad = WebhookHealthReport(
            registered_topics=frozenset(),
            declared_topics=frozenset({"orders/create"}),
            missing_on_app=["orders/create"],
            extra_on_app=[],
            gdpr_missing=[],
            is_healthy=False,
        )
        # Patch both scope (clean) and webhook (bad) checks
        from core.adapters.shopify.scope_health import ScopeHealthReport
        scope_clean = ScopeHealthReport(
            granted_scopes=frozenset(),
            required_scopes=frozenset(),
            missing_from_app=[],
            extra_in_app=[],
            is_healthy=True,
        )
        with patch(
            "core.adapters.shopify.scope_health.compare_to_live",
            return_value=scope_clean,
        ), patch(
            "core.feedback.webhook_health.compare_to_live",
            return_value=bad,
        ):
            out, code = _capture(
                cli._cmd_shopify_doctor,
                argparse.Namespace(json=False, skip_live=False),
            )
        assert code == 1
        assert "[FAIL] Live webhook drift" in out
