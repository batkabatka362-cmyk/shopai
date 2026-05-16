"""Tests for ``shopai store verify`` -- the read-only drift audit
that runs the configurator in dry_run mode and reports the plan
as drift.

Covers:

  - Empty plan = clean, exit 0
  - Non-empty plan = drift, exit 1
  - Plan entries bucket correctly by feature path
  - --json envelope shape (clean and drift cases)
  - Error paths (no store, no creds) route through both modes
  - --only narrows the feature set
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
        only="",
        niche="",
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_store_manager(
    *,
    active="test-store",
    shop_url="example.myshopify.com",
    api_key="shpat_token",
    niche="beauty",
):
    sm = MagicMock()
    sm.active_store_id = active
    sm.get_credentials.return_value = {
        "shop_url": shop_url,
        "api_key": api_key,
    }
    sm.db.get_store.return_value = {
        "name": active,
        "niche": niche,
    }
    return sm


def _fake_configurator_result(plan):
    """Return a fake configurator result with the given plan."""
    return {
        "status": "planned",
        "niche": "beauty",
        "features": ["collections", "discounts"],
        "results": {},
        "plan": plan,
    }


# ─── Plan-bucket classifier ──────────────────────────────────


class TestClassifyPlanEntry:

    @pytest.mark.parametrize("path,expected", [
        ("smart_collections.json", "collections"),
        ("custom_collections.json", "collections"),
        ("price_rules.json", "discounts"),
        ("price_rules/123/discount_codes.json", "discounts"),
        ("shipping_zones.json", "shipping"),
        ("pages.json", "content"),
        ("blogs/1/articles.json", "content"),
        ("products/123/metafields.json", "ai_config"),
        ("metafields.json?namespace=shopai.gifts", "gifts"),
        ("metafields.json?namespace=shopai.loyalty", "loyalty"),
        ("metafields.json?namespace=shopai.referral", "referral"),
        ("metafields.json?namespace=shopai.shipping", "shipping"),
        ("metafields.json?namespace=shopai.payments", "payments"),
        ("products/123.json", "product_tags"),
        ("orders.json", "other"),
    ])
    def test_buckets_match_expected(self, cli, path, expected):
        assert cli._classify_plan_entry(path) == expected


# ─── Clean (no drift) ────────────────────────────────────────


class TestCleanCase:

    def test_empty_plan_exits_0(self, cli):
        sm = _fake_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            configurator_cls.return_value.configure.return_value = (
                _fake_configurator_result(plan=[])
            )
            out, code = _capture(cli._cmd_store_verify, _ns())
        assert code == 0
        assert "fully aligned" in out

    def test_clean_features_listed(self, cli):
        sm = _fake_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            configurator_cls.return_value.configure.return_value = (
                _fake_configurator_result(plan=[])
            )
            out, _ = _capture(cli._cmd_store_verify, _ns())
        assert "Clean (" in out
        assert "[ok]" in out


# ─── Drift cases ─────────────────────────────────────────────


class TestDriftCase:

    def test_non_empty_plan_exits_1(self, cli):
        sm = _fake_store_manager()
        plan = [
            {"method": "POST", "path": "smart_collections.json",
             "description": "Create 'Best Sellers'", "body_preview": {}},
        ]
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            configurator_cls.return_value.configure.return_value = (
                _fake_configurator_result(plan=plan)
            )
            out, code = _capture(cli._cmd_store_verify, _ns())
        assert code == 1
        assert "drift detected" in out

    def test_drift_buckets_by_feature(self, cli):
        sm = _fake_store_manager()
        plan = [
            {"method": "POST", "path": "smart_collections.json",
             "description": "c1", "body_preview": {}},
            {"method": "POST", "path": "smart_collections.json",
             "description": "c2", "body_preview": {}},
            {"method": "POST", "path": "price_rules.json",
             "description": "d1", "body_preview": {}},
        ]
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            configurator_cls.return_value.configure.return_value = (
                _fake_configurator_result(plan=plan)
            )
            out, _ = _capture(cli._cmd_store_verify, _ns())
        # Collections bucket should show 2 writes, discounts 1
        assert "collections" in out
        assert "2 write(s)" in out
        assert "discounts" in out
        assert "1 write(s)" in out

    def test_drift_summary_trims_long_lists(self, cli):
        """Each feature shows at most 3 writes inline; the rest
        collapse into 'and N more'."""
        sm = _fake_store_manager()
        plan = [
            {"method": "POST", "path": "smart_collections.json",
             "description": f"c{i}", "body_preview": {}}
            for i in range(8)
        ]
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            configurator_cls.return_value.configure.return_value = (
                _fake_configurator_result(plan=plan)
            )
            out, _ = _capture(cli._cmd_store_verify, _ns())
        assert "and 5 more" in out


# ─── --json envelope ─────────────────────────────────────────


class TestJsonEnvelope:

    def test_json_clean_envelope_shape(self, cli):
        sm = _fake_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            configurator_cls.return_value.configure.return_value = (
                _fake_configurator_result(plan=[])
            )
            out, code = _capture(
                cli._cmd_store_verify, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["store_id"] == "test-store"
        assert data["shop_url"] == "example.myshopify.com"
        assert data["niche"] == "beauty"
        assert data["has_drift"] is False
        assert data["total_planned_writes"] == 0
        assert data["drift_features"] == []
        # All 11 standard features verified by default
        assert len(data["clean_features"]) == 11

    def test_json_drift_envelope_shape(self, cli):
        sm = _fake_store_manager()
        plan = [
            {"method": "POST", "path": "smart_collections.json",
             "description": "Create X", "body_preview": {}},
        ]
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            configurator_cls.return_value.configure.return_value = (
                _fake_configurator_result(plan=plan)
            )
            out, code = _capture(
                cli._cmd_store_verify, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["has_drift"] is True
        assert data["total_planned_writes"] == 1
        assert "collections" in data["drift_features"]
        assert data["drift_by_feature"]["collections"]["count"] == 1


# ─── --only filter ───────────────────────────────────────────


class TestOnlyFilter:

    def test_only_filter_narrows_feature_set(self, cli):
        sm = _fake_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            configurator_cls.return_value.configure.return_value = (
                _fake_configurator_result(plan=[])
            )
            out, _ = _capture(
                cli._cmd_store_verify,
                _ns(only="collections,discounts", json=True),
            )
        data = json.loads(out)
        assert set(data["checked_features"]) == {"collections", "discounts"}


# ─── Error paths ─────────────────────────────────────────────


class TestErrorPaths:

    def test_no_active_store_text(self, cli):
        sm = MagicMock()
        sm.active_store_id = None
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out, code = _capture(cli._cmd_store_verify, _ns())
        assert code == 1
        assert "No store specified" in out

    def test_no_active_store_json(self, cli):
        sm = MagicMock()
        sm.active_store_id = None
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out, code = _capture(
                cli._cmd_store_verify, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["status"] == "error"
        assert "No store specified" in data["error"]

    def test_no_credentials_text(self, cli, monkeypatch):
        sm = MagicMock()
        sm.active_store_id = "ghost"

        def _gated_get_credentials(_store_id):
            return None

        monkeypatch.setattr(sm, "get_credentials", _gated_get_credentials)
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out, code = _capture(cli._cmd_store_verify, _ns())
        assert code == 1
        assert "not found" in out or "shop_url" in out
