"""Tests for ``shopai store setup`` -- end-to-end orchestration
that adds + connects + plans + (optionally) applies in one
command.

Covers:

  - All five stages render in the default plan-only run.
  - --apply executes the final apply stage.
  - --json envelope shape (success + each failure mode).
  - Pre-flight credential validation rejects missing creds.
  - Add / connect / plan / apply failure modes each bail at the
    right stage and exit 1.
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
        store_id="test-store",
        shop_url="example.myshopify.com",
        api_key="shpat_token",
        client_id="",
        client_secret="",
        name="",
        niche="general",
        store_type="dropshipping",
        only="",
        apply=False,
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _good_store_manager():
    sm = MagicMock()
    sm.add_store.return_value = {"ok": True}
    sm.test_connection.return_value = {
        "connected": True,
        "shop": "example.myshopify.com",
    }
    sm.get_credentials.return_value = {
        "shop_url": "example.myshopify.com",
        "api_key": "shpat_token",
    }
    return sm


def _good_plan_result(plan_count=8):
    return {
        "status": "planned",
        "niche": "general",
        "features": ["collections", "discounts"],
        "results": {"collections": {"created": 5}, "discounts": {}},
        "plan": [
            {"method": "POST", "path": "smart_collections.json",
             "description": "c", "body_preview": {}}
            for _ in range(plan_count)
        ],
    }


def _good_apply_result():
    return {
        "status": "configured",
        "niche": "general",
        "features": ["collections", "discounts"],
        "results": {"collections": {"created": 5}, "discounts": {}},
        "plan": None,
    }


# ─── Pre-flight credential validation ────────────────────────


class TestCredentialValidation:

    def test_no_credentials_fails(self, cli):
        out, code = _capture(
            cli._cmd_store_setup,
            _ns(api_key="", client_id="", client_secret=""),
        )
        assert code == 1
        assert "Must supply" in out

    def test_partial_oauth_fails(self, cli):
        """client_id alone (without client_secret) is rejected."""
        out, code = _capture(
            cli._cmd_store_setup,
            _ns(api_key="", client_id="cid", client_secret=""),
        )
        assert code == 1
        assert "Must supply" in out

    def test_api_key_alone_is_valid(self, cli):
        sm = _good_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            configurator_cls.return_value.configure.return_value = (
                _good_plan_result()
            )
            _, code = _capture(cli._cmd_store_setup, _ns())
        assert code == 0

    def test_full_oauth_pair_is_valid(self, cli):
        sm = _good_store_manager()
        sm.get_credentials.return_value = {
            "shop_url": "example.myshopify.com",
            "client_id": "cid",
            "client_secret": "csec",
        }
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls, patch(
            "core.auth.shopify_auth.ShopifyAuth",
        ) as auth_cls:
            auth_cls.return_value.get_token.return_value = "shpat_resolved"
            configurator_cls.return_value.configure.return_value = (
                _good_plan_result()
            )
            _, code = _capture(
                cli._cmd_store_setup,
                _ns(api_key="", client_id="cid", client_secret="csec"),
            )
        assert code == 0


# ─── Happy path (plan-only) ──────────────────────────────────


class TestPlanOnlyHappyPath:

    def test_renders_five_stages(self, cli):
        sm = _good_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            configurator_cls.return_value.configure.return_value = (
                _good_plan_result()
            )
            out, code = _capture(cli._cmd_store_setup, _ns())
        assert code == 0
        # Default flow: add + connect + plan + apply-skipped (4 stages)
        assert "Store added" in out
        assert "Connection verified" in out
        assert "Configurator planned" in out
        assert "Apply skipped" in out
        assert "Re-run with --apply" in out

    def test_does_not_call_configurator_apply(self, cli):
        sm = _good_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            configurator_cls.return_value.configure.return_value = (
                _good_plan_result()
            )
            _capture(cli._cmd_store_setup, _ns())
        # Without --apply, configurator is only instantiated once
        # (the dry-run pass) -- never with dry_run=False.
        for call in configurator_cls.call_args_list:
            kwargs = call.kwargs
            args_list = call.args
            # dry_run is the keyword arg
            assert kwargs.get("dry_run") is True or (
                args_list and args_list[0] is True
            )


# ─── --apply flow ─────────────────────────────────────────────


class TestApplyFlow:

    def test_apply_calls_configurator_twice(self, cli):
        sm = _good_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            # Two passes: first dry, then real
            inst = configurator_cls.return_value
            inst.configure.side_effect = [
                _good_plan_result(),
                _good_apply_result(),
            ]
            out, code = _capture(
                cli._cmd_store_setup, _ns(apply=True),
            )
        assert code == 0
        assert "Configurator planned" in out
        assert "status=configured" in out
        assert "Setup complete" in out

    def test_apply_failure_exits_1(self, cli):
        sm = _good_store_manager()
        bad_apply = dict(_good_apply_result())
        bad_apply["status"] = "error"
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            inst = configurator_cls.return_value
            inst.configure.side_effect = [
                _good_plan_result(), bad_apply,
            ]
            out, code = _capture(
                cli._cmd_store_setup, _ns(apply=True),
            )
        assert code == 1
        assert "Setup failed" in out


# ─── Per-stage failure modes ─────────────────────────────────


class TestStageFailures:

    def test_add_failure_exits_1(self, cli):
        sm = _good_store_manager()
        sm.add_store.side_effect = RuntimeError("db locked")
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out, code = _capture(cli._cmd_store_setup, _ns())
        assert code == 1
        assert "Store add failed" in out
        # Subsequent stages should not have run
        assert "Connection verified" not in out

    def test_connect_failure_exits_1(self, cli):
        sm = _good_store_manager()
        sm.test_connection.return_value = {
            "connected": False, "error": "401 Unauthorized",
        }
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out, code = _capture(cli._cmd_store_setup, _ns())
        assert code == 1
        assert "Connection failed" in out
        assert "401 Unauthorized" in out
        # Plan stage should not have run
        assert "Configurator planned" not in out

    def test_plan_raise_exits_1(self, cli):
        sm = _good_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            configurator_cls.return_value.configure.side_effect = (
                RuntimeError("configurator broke")
            )
            out, code = _capture(cli._cmd_store_setup, _ns())
        assert code == 1
        assert "Configurator dry-run raised" in out


# ─── --json envelope ─────────────────────────────────────────


class TestJsonEnvelope:

    def test_json_success_envelope(self, cli):
        sm = _good_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            configurator_cls.return_value.configure.return_value = (
                _good_plan_result(plan_count=5)
            )
            out, code = _capture(
                cli._cmd_store_setup, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["store_id"] == "test-store"
        assert data["shop_url"] == "example.myshopify.com"
        assert data["success"] is True
        assert data["applied"] is False
        stages = {s["stage"]: s for s in data["stages"]}
        assert "add" in stages
        assert "connect" in stages
        assert "plan" in stages
        assert "apply" in stages
        assert stages["apply"]["skipped"] is True
        assert stages["plan"]["plan_count"] == 5

    def test_json_apply_envelope(self, cli):
        sm = _good_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            inst = configurator_cls.return_value
            inst.configure.side_effect = [
                _good_plan_result(), _good_apply_result(),
            ]
            out, _ = _capture(
                cli._cmd_store_setup, _ns(json=True, apply=True),
            )
        data = json.loads(out)
        assert data["applied"] is True
        stages = {s["stage"]: s for s in data["stages"]}
        assert stages["apply"].get("ok") is True

    def test_json_credential_failure_envelope(self, cli):
        out, code = _capture(
            cli._cmd_store_setup,
            _ns(api_key="", json=True),
        )
        assert code == 1
        data = json.loads(out)
        assert data["success"] is False
        assert "Must supply" in data["error"]

    def test_json_first_char_is_brace(self, cli):
        sm = _good_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "execution.store_configurator.StoreConfigurator",
        ) as configurator_cls:
            configurator_cls.return_value.configure.return_value = (
                _good_plan_result()
            )
            out, _ = _capture(
                cli._cmd_store_setup, _ns(json=True),
            )
        # No human-readable header before the JSON
        assert out.lstrip()[0] == "{"
        assert "Setting up" not in out
