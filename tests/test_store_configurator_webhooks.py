"""StoreConfigurator webhook subscription tests (Phase 2d).

Without webhook subscriptions, the OrderWebhookHandler never
fires → learning loop stays dark. This feature subscribes
ShopAI's endpoint to the reward-signal topics as part of the
configure() run, making a store T1-ready.

Env-gated: SHOPAI_WEBHOOK_CALLBACK_URL must be set (https).
Dry-run friendly. Idempotent via register_all's "exists"
status.
"""
from __future__ import annotations

import os

import pytest


def _make(dry_run: bool = False):
    from execution.store_configurator import StoreConfigurator
    return StoreConfigurator(dry_run=dry_run)


def _install_fake_client(monkeypatch):
    """The webhook feature delegates to
    core.webhooks.register.register_all — we monkey-patch
    that directly rather than the ShopifyClient."""

    class FakeClient:
        def __init__(self, *a, **kw): pass
        def get(self, path, *, params=None): return {}
        def post(self, path, *, json=None): return {}
        def put(self, path, *, json=None): return {}
        def delete(self, path): return {}

    monkeypatch.setattr(
        "execution.store_configurator.ShopifyClient",
        FakeClient,
    )


class TestWebhooksFeatureEnabled:
    def test_webhooks_in_all_features(self):
        from execution.store_configurator import ALL_FEATURES
        assert "webhooks" in ALL_FEATURES


class TestWebhooksEnvGate:
    def test_no_env_var_returns_skipped(
        self, monkeypatch,
    ):
        _install_fake_client(monkeypatch)
        monkeypatch.delenv(
            "SHOPAI_WEBHOOK_CALLBACK_URL", raising=False,
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["webhooks"],
        )
        w = result["results"]["webhooks"]
        assert w["status"] == "skipped"
        assert "SHOPAI_WEBHOOK_CALLBACK_URL" in w["reason"]

    def test_non_https_returns_error(self, monkeypatch):
        _install_fake_client(monkeypatch)
        monkeypatch.setenv(
            "SHOPAI_WEBHOOK_CALLBACK_URL",
            "http://bad.example.com/hook",
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["webhooks"],
        )
        w = result["results"]["webhooks"]
        assert w["status"] == "error"
        assert "https" in w["reason"]


class TestWebhooksDryRun:
    def test_plan_entries_created(self, monkeypatch):
        _install_fake_client(monkeypatch)
        monkeypatch.setenv(
            "SHOPAI_WEBHOOK_CALLBACK_URL",
            "https://example.com/hook",
        )
        c = _make(dry_run=True)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["webhooks"],
        )
        w = result["results"]["webhooks"]
        assert w["status"] == "dry_run"
        # Pull the canonical topic count from the live
        # register module so this assertion doesn't drift
        # whenever we add a new webhook topic (e.g. the
        # checkouts/update + customers/create additions
        # for abandoned-cart + welcome flow triggers).
        from core.webhooks.register import _TOPICS
        assert len(w["subscribed"]) == len(_TOPICS)
        topics = set(w["subscribed"])
        assert "orders/paid" in topics
        assert "orders/create" in topics


class TestWebhooksLive:
    def test_calls_register_all_and_classifies(
        self, monkeypatch,
    ):
        _install_fake_client(monkeypatch)
        monkeypatch.setenv(
            "SHOPAI_WEBHOOK_CALLBACK_URL",
            "https://example.com/hook",
        )

        captured = {}

        def fake_register_all(shop, token, url, **kw):
            captured["shop"] = shop
            captured["url"] = url
            return {
                "orders/create": "created",
                "orders/paid": "exists",
                "orders/cancelled": "created",
                "products/update": "created",
                "app/uninstalled": "error:Unauthorized",
            }

        monkeypatch.setattr(
            "core.webhooks.register.register_all",
            fake_register_all,
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["webhooks"],
        )
        w = result["results"]["webhooks"]
        assert captured["shop"] == "x.myshopify.com"
        assert captured["url"] == "https://example.com/hook"
        assert w["status"] == "partial"
        assert set(w["subscribed"]) == {
            "orders/create", "orders/cancelled",
            "products/update",
        }
        assert w["existing"] == ["orders/paid"]
        assert len(w["errors"]) == 1
        assert (
            w["errors"][0]["topic"] == "app/uninstalled"
        )

    def test_all_created_returns_success(
        self, monkeypatch,
    ):
        _install_fake_client(monkeypatch)
        monkeypatch.setenv(
            "SHOPAI_WEBHOOK_CALLBACK_URL",
            "https://example.com/hook",
        )

        def fake_register_all(shop, token, url, **kw):
            return {
                "orders/create": "created",
                "orders/paid": "created",
                "orders/cancelled": "created",
                "products/update": "created",
                "app/uninstalled": "created",
            }

        monkeypatch.setattr(
            "core.webhooks.register.register_all",
            fake_register_all,
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["webhooks"],
        )
        w = result["results"]["webhooks"]
        assert w["status"] == "success"
        assert len(w["subscribed"]) == 5
        assert w["errors"] == []

    def test_register_all_raises_handled(self, monkeypatch):
        _install_fake_client(monkeypatch)
        monkeypatch.setenv(
            "SHOPAI_WEBHOOK_CALLBACK_URL",
            "https://example.com/hook",
        )

        def fake_register_all(shop, token, url, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "core.webhooks.register.register_all",
            fake_register_all,
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["webhooks"],
        )
        w = result["results"]["webhooks"]
        assert w["status"] == "error"
        assert "boom" in w["errors"][0]["error"]
