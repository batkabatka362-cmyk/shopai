"""Tests for ``core.feedback.webhook_drift_fixer``.

The drift fixer takes a callback URL and registers every
missing webhook topic. This unblocks public-distribution
Shopify review by addressing the 3 GDPR-mandatory topics
(``customers/data_request`` / ``customers/redact`` /
``shop/redact``).

Coverage:
  1. Empty callback_url -> failure, no API call.
  2. ``compare_to_live`` returns None (unconfigured) ->
     drift_unavailable flag set, no create calls fired.
  3. No missing topics -> empty report (clean).
  4. Missing topics -> CREATE_WEBHOOK called for each, with
     correct callback URL + format.
  5. Adapter raises -> per-topic failure recorded, others
     proceed.
  6. Adapter returns "already subscribed" user-error ->
     treated as ``skipped_existing`` rather than failure.
  7. ``only_gdpr=True`` filters to the 3 GDPR topics.
  8. Per-topic adapter failure doesn't abort the rest of the
     loop -- partial success is still reported.
  9. ``is_clean`` reflects no-failures + drift-available.
"""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.feedback.webhook_drift_fixer import (
    WebhookRegisterReport,
    auto_register_missing_topics,
)
from core.feedback.webhook_health import WebhookHealthReport


def _ok(data=None):
    return SimpleNamespace(ok=True, data=data or {}, error=None)


def _fail(error="rejected"):
    return SimpleNamespace(ok=False, data=None, error=error)


def _drift_report(missing: list[str], gdpr_missing: list[str] | None = None):
    return WebhookHealthReport(
        registered_topics=frozenset(),
        declared_topics=frozenset(missing),
        missing_on_app=missing,
        extra_on_app=[],
        gdpr_missing=gdpr_missing or [],
        is_healthy=not missing,
    )


class TestCallbackUrlRequired:

    def test_empty_callback_url_returns_failure(self):
        report = auto_register_missing_topics(callback_url="")
        assert not report.is_clean
        assert report.failed[0]["error"] == "callback_url_required"

    def test_whitespace_callback_url_returns_failure(self):
        report = auto_register_missing_topics(callback_url="   ")
        assert not report.is_clean
        assert report.failed[0]["error"] == "callback_url_required"


class TestDriftUnavailable:

    def test_compare_returns_none_sets_drift_unavailable(self):
        adapter = MagicMock()
        with patch(
            "core.feedback.webhook_drift_fixer.compare_to_live",
            return_value=None,
        ):
            report = auto_register_missing_topics(
                callback_url="https://app.shopai.com/webhooks",
                webhooks_adapter=adapter,
            )
        assert report.drift_unavailable is True
        # The fixer must NOT have attempted any create call
        adapter.execute.assert_not_called()


class TestNoMissingTopics:

    def test_clean_install_returns_empty_report(self):
        drift = _drift_report(missing=[])
        adapter = MagicMock()
        with patch(
            "core.feedback.webhook_drift_fixer.compare_to_live",
            return_value=drift,
        ):
            report = auto_register_missing_topics(
                callback_url="https://app.shopai.com/webhooks",
                webhooks_adapter=adapter,
            )
        assert report.is_clean is True
        assert report.registered == []
        assert report.failed == []
        # No create calls -- there was nothing to do
        adapter.execute.assert_not_called()


class TestMissingTopicsRegistered:

    def test_each_missing_topic_creates_webhook(self):
        drift = _drift_report(missing=[
            "customers/data_request",
            "customers/redact",
            "shop/redact",
            "orders/create",
        ])
        adapter = MagicMock()
        adapter.execute.return_value = _ok({
            "webhook": {"id": "gid://shopify/WebhookSubscription/1"},
        })

        with patch(
            "core.feedback.webhook_drift_fixer.compare_to_live",
            return_value=drift,
        ):
            report = auto_register_missing_topics(
                callback_url="https://app.shopai.com/webhooks",
                webhooks_adapter=adapter,
            )

        assert report.is_clean is True
        assert set(report.registered) == {
            "customers/data_request",
            "customers/redact",
            "shop/redact",
            "orders/create",
        }
        # 4 create calls fired
        assert adapter.execute.call_count == 4
        # Each call carries the callback URL + JSON format
        first_call = adapter.execute.call_args_list[0]
        params = first_call.args[1]
        assert params["callback_url"] == "https://app.shopai.com/webhooks"
        assert params["format"] == "JSON"

    def test_only_gdpr_filters_to_three(self):
        drift = _drift_report(missing=[
            "customers/data_request",
            "customers/redact",
            "shop/redact",
            "orders/create",
            "refunds/create",
        ])
        adapter = MagicMock()
        adapter.execute.return_value = _ok({
            "webhook": {"id": "gid://x"},
        })

        with patch(
            "core.feedback.webhook_drift_fixer.compare_to_live",
            return_value=drift,
        ):
            report = auto_register_missing_topics(
                callback_url="https://app.shopai.com/webhooks",
                only_gdpr=True,
                webhooks_adapter=adapter,
            )

        assert set(report.target_topics) == {
            "customers/data_request",
            "customers/redact",
            "shop/redact",
        }
        assert set(report.registered) == {
            "customers/data_request",
            "customers/redact",
            "shop/redact",
        }
        # Operational topics weren't touched
        assert adapter.execute.call_count == 3


class TestAlreadySubscribedTreatedAsSkipped:

    def test_user_error_already_lands_in_skipped_existing(self):
        drift = _drift_report(missing=["orders/create"])
        adapter = MagicMock()
        adapter.execute.return_value = _fail(
            "Topic is already subscribed at this callback URL",
        )

        with patch(
            "core.feedback.webhook_drift_fixer.compare_to_live",
            return_value=drift,
        ):
            report = auto_register_missing_topics(
                callback_url="https://app.shopai.com/webhooks",
                webhooks_adapter=adapter,
            )

        # The system is in the right state -- this isn't a
        # failure, it's a no-op
        assert report.skipped_existing == ["orders/create"]
        assert report.failed == []
        assert report.is_clean is True

    def test_user_error_duplicate_treated_as_skipped(self):
        drift = _drift_report(missing=["orders/paid"])
        adapter = MagicMock()
        adapter.execute.return_value = _fail("duplicate subscription")

        with patch(
            "core.feedback.webhook_drift_fixer.compare_to_live",
            return_value=drift,
        ):
            report = auto_register_missing_topics(
                callback_url="https://app.shopai.com/webhooks",
                webhooks_adapter=adapter,
            )

        assert report.skipped_existing == ["orders/paid"]
        assert report.is_clean is True


class TestPartialFailure:

    def test_per_topic_raises_dont_abort_loop(self):
        drift = _drift_report(missing=["a/b", "c/d", "e/f"])
        call_count = {"n": 0}

        def _exec(cap, params):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("transient network")
            return _ok({"webhook": {"id": "x"}})

        adapter = MagicMock()
        adapter.execute.side_effect = _exec

        with patch(
            "core.feedback.webhook_drift_fixer.compare_to_live",
            return_value=drift,
        ):
            report = auto_register_missing_topics(
                callback_url="https://app.shopai.com/webhooks",
                webhooks_adapter=adapter,
            )

        # 2 succeeded + 1 failed; loop did not abort
        assert len(report.registered) == 2
        assert len(report.failed) == 1
        assert "transient network" in report.failed[0]["error"]
        assert report.is_clean is False

    def test_per_topic_not_ok_response_recorded(self):
        drift = _drift_report(missing=["x/y", "z/w"])

        def _exec(cap, params):
            if params["topic"] == "x/y":
                return _fail("invalid topic")
            return _ok({"webhook": {"id": "ok"}})

        adapter = MagicMock()
        adapter.execute.side_effect = _exec

        with patch(
            "core.feedback.webhook_drift_fixer.compare_to_live",
            return_value=drift,
        ):
            report = auto_register_missing_topics(
                callback_url="https://app.shopai.com/webhooks",
                webhooks_adapter=adapter,
            )
        assert report.registered == ["z/w"]
        assert len(report.failed) == 1
        assert report.failed[0]["topic"] == "x/y"
        assert "invalid topic" in report.failed[0]["error"]
        assert report.is_clean is False


class TestIsCleanFlag:

    def test_clean_when_all_registered(self):
        drift = _drift_report(missing=["orders/create"])
        adapter = MagicMock()
        adapter.execute.return_value = _ok({"webhook": {}})
        with patch(
            "core.feedback.webhook_drift_fixer.compare_to_live",
            return_value=drift,
        ):
            report = auto_register_missing_topics(
                callback_url="https://app.shopai.com/webhooks",
                webhooks_adapter=adapter,
            )
        assert report.is_clean is True

    def test_dirty_when_any_failed(self):
        report = WebhookRegisterReport(
            callback_url="x",
            target_topics=["a"],
            registered=[],
            failed=[{"topic": "a", "error": "x"}],
        )
        assert report.is_clean is False

    def test_dirty_when_drift_unavailable(self):
        report = WebhookRegisterReport(
            callback_url="x",
            drift_unavailable=True,
        )
        assert report.is_clean is False
