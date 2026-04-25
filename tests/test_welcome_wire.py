"""Welcome-flow webhook wire tests.

Covers:
  * Email + first_name extractors with fallback chain
  * ``_accepts_marketing`` — legacy bool, 2024+ consent dict,
    default policy
  * ``handle_customer_create`` happy path + every skip reason
    (has orders, no email, opted-out, unsubscribed,
    unavailable engine, engine exception)
  * Idempotency on repeat webhooks
  * Context populated from env
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.engines.email_campaigns import (
    EmailCampaignEngine, ScheduleQueue,
    reset_singleton_for_tests as _reset_ec,
)
from core.webhooks.customer_handler import (
    _accepts_marketing, _extract_email, _extract_first_name,
    handle_customer_create,
)


@pytest.fixture
def email_engine(tmp_path, monkeypatch):
    _reset_ec()
    q = ScheduleQueue(
        db_path=str(tmp_path / "email.db"),
        now_fn=lambda: 1_700_000_000.0,
    )
    e = EmailCampaignEngine(
        queue=q, from_email="hello@deguar.com",
        now_fn=lambda: 1_700_000_000.0,
    )
    # Register as singleton so handler picks up OUR engine
    import core.engines.email_campaigns.engine as ec_mod
    ec_mod._SINGLETON = e
    monkeypatch.setenv(
        "SHOPAI_SHOPIFY_URL", "deguar.myshopify.com",
    )
    monkeypatch.setenv("SHOPAI_STORE_NAME", "Deguar")
    yield e
    _reset_ec()


def _customer(**over):
    base = {
        "id": 42,
        "email": "new@example.com",
        "first_name": "Mai",
        "orders_count": 0,
        "accepts_marketing": True,
    }
    base.update(over)
    return base


# ── Extractors ───────────────────────────────────────────


class TestExtractors:
    def test_email_top_level(self):
        assert _extract_email(
            {"email": "UP@CASE.com"},
        ) == "up@case.com"

    def test_email_missing(self):
        assert _extract_email({}) == ""

    def test_first_name_direct(self):
        assert _extract_first_name(
            {"first_name": "Mai"}, "a@b.c",
        ) == "Mai"

    def test_first_name_from_address(self):
        assert _extract_first_name({
            "addresses": [
                {"first_name": "Addr"},
            ],
        }, "a@b.c") == "Addr"

    def test_first_name_from_email(self):
        """No name anywhere — derive from email local-part."""
        assert _extract_first_name(
            {}, "jane.doe@example.com",
        ) == "Jane Doe"

    def test_first_name_fallback(self):
        assert _extract_first_name({}, "") == "there"


# ── _accepts_marketing ──────────────────────────────────


class TestAcceptsMarketing:
    def test_legacy_bool_true(self):
        assert _accepts_marketing({"accepts_marketing": True})

    def test_legacy_bool_false(self):
        assert not _accepts_marketing({
            "accepts_marketing": False,
        })

    def test_2024_consent_subscribed(self):
        assert _accepts_marketing({
            "email_marketing_consent": {
                "state": "subscribed",
            },
        })

    def test_2024_consent_unsubscribed(self):
        assert not _accepts_marketing({
            "email_marketing_consent": {
                "state": "unsubscribed",
            },
        })

    def test_2024_consent_not_subscribed(self):
        assert not _accepts_marketing({
            "email_marketing_consent": {
                "state": "not_subscribed",
            },
        })

    def test_empty_payload_default_true(self):
        """No marketing signal at all — default to accept +
        let per-recipient unsubscribe list handle opt-outs."""
        assert _accepts_marketing({})


# ── handle_customer_create ──────────────────────────────


class TestHandler:
    def test_happy_path_enrolls_welcome(self, email_engine):
        result = handle_customer_create(_customer())
        assert result["enrolled"] is True
        rows = email_engine.list_for_recipient(
            "new@example.com",
        )
        # Welcome flow has 3 steps
        assert len(rows) == 3
        assert all(r.flow_id == "welcome" for r in rows)

    def test_context_populated_from_env(self, email_engine):
        handle_customer_create(_customer())
        rows = email_engine.list_for_recipient(
            "new@example.com",
        )
        ctx = rows[0].context
        assert ctx["first_name"] == "Mai"
        assert ctx["store_name"] == "Deguar"
        assert "deguar.myshopify.com" in ctx["store_url"]
        assert ctx["discount_code"] == "WELCOME15"
        # Fallback top_products when env unset
        assert ctx["top_products"]

    def test_skip_when_has_orders(self, email_engine):
        """orders_count > 0 → post_purchase owns this
        journey, not welcome."""
        result = handle_customer_create(
            _customer(orders_count=2),
        )
        assert result["enrolled"] is False
        assert "post_purchase" in result["skipped_reason"]
        assert not email_engine.list_for_recipient(
            "new@example.com",
        )

    def test_skip_when_no_email(self, email_engine):
        result = handle_customer_create(
            _customer(email=""),
        )
        assert result["enrolled"] is False
        assert "email" in result["skipped_reason"]

    def test_skip_when_opted_out(self, email_engine):
        result = handle_customer_create(_customer(
            accepts_marketing=False,
        ))
        assert result["enrolled"] is False
        assert "marketing" in result["skipped_reason"]

    def test_skip_when_unsubscribed(self, email_engine):
        """Even if Shopify says accepts_marketing=True, our
        local unsubscribe list (e.g. owner manually opted
        someone out) wins."""
        email_engine.unsubscribe(
            "new@example.com", source="manual",
        )
        result = handle_customer_create(_customer())
        assert result["enrolled"] is False
        assert "unsubscribe" in result["skipped_reason"]

    def test_idempotent_on_repeat(self, email_engine):
        """Same customer webhook fires twice (Shopify retry
        storm) — second enrollment is a no-op."""
        handle_customer_create(_customer())
        handle_customer_create(_customer())
        rows = email_engine.list_for_recipient(
            "new@example.com",
        )
        assert len(rows) == 3  # not 6


# ── 2024 consent path (end-to-end) ──────────────────────


class Test2024ConsentE2E:
    def test_subscribed_state_enrolls(self, email_engine):
        customer = _customer()
        del customer["accepts_marketing"]
        customer["email_marketing_consent"] = {
            "state": "subscribed",
            "opt_in_level": "confirmed_opt_in",
        }
        result = handle_customer_create(customer)
        assert result["enrolled"] is True

    def test_not_subscribed_skips(self, email_engine):
        customer = _customer()
        del customer["accepts_marketing"]
        customer["email_marketing_consent"] = {
            "state": "not_subscribed",
        }
        result = handle_customer_create(customer)
        assert result["enrolled"] is False
        assert "marketing" in result["skipped_reason"]


# ── Engine exception isolation ──────────────────────────


class TestEngineErrors:
    def test_enroll_exception_caught(self, email_engine):
        with patch.object(
            email_engine, "enroll",
            side_effect=RuntimeError("db locked"),
        ):
            result = handle_customer_create(_customer())
        assert result["enrolled"] is False
        assert "db locked" in result["skipped_reason"]

    def test_engine_import_failure(self, monkeypatch):
        """If email_campaigns can't import (reduced-dep
        deploy), handler returns cleanly."""
        _reset_ec()
        # Simulate import failure by injecting an engine that
        # raises on enroll. The handler's fallback to
        # ``get_engine()`` fires only when email_engine is None,
        # so we test the passed-None path explicitly.
        import core.engines.email_campaigns.engine as ec_mod
        ec_mod._SINGLETON = None

        # Monkey-patch the import site
        import core.webhooks.customer_handler as mod

        def raising_get():
            raise ImportError("optional dep missing")

        with patch(
            "core.engines.email_campaigns.get_engine",
            side_effect=raising_get,
        ):
            result = handle_customer_create(
                _customer(), email_engine=None,
            )
        # Handler reported unavailable cleanly — no crash
        assert result["enrolled"] is False
        assert "unavailable" in result["skipped_reason"]
        _reset_ec()


# ── Payload shape resilience ────────────────────────────


class TestPayloadShapes:
    def test_non_dict_payload_clean_skip(self, email_engine):
        """Pathological input — a non-dict webhook body
        shouldn't crash."""
        result = handle_customer_create("not a dict")  # type: ignore[arg-type]
        assert result["enrolled"] is False

    def test_orders_count_string(self, email_engine):
        """Shopify sometimes sends orders_count as a string
        (older API)."""
        result = handle_customer_create(_customer(
            orders_count="3",
        ))
        assert result["enrolled"] is False
        assert "post_purchase" in result["skipped_reason"]

    def test_orders_count_garbage(self, email_engine):
        """Garbage value → treat as zero → still enroll."""
        result = handle_customer_create(_customer(
            orders_count="not a number",
        ))
        assert result["enrolled"] is True
