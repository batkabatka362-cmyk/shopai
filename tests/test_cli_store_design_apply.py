"""Tests for ``shopai store design-apply``.

Writer-side CLI for the store_design lane. Mirrors ``store
design`` (preview) but pipes the engine output through
``apply_design`` to write tokens + snippet files into a live
Shopify theme.

Coverage:
  - Successful apply -> exit 0 + file list
  - Engine returns non-success -> exit 1
  - apply_design returns applied=False -> exit 1
  - Engine raise -> exit 1 with friendly message
  - apply_design raise -> exit 1
  - --json output (success + failure paths)
  - --theme-id is required by argparse
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
    defaults = dict(
        json=False,
        store_id=None,
        theme_id="gid://shopify/OnlineStoreTheme/1",
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_sm():
    sm = MagicMock()
    sm.active_store_id = None
    sm.get_stats = MagicMock(return_value={})
    return sm


def _engine_success():
    return {
        "status": "success",
        "data": {
            "layout_recommendations": [{"section": "hero"}],
            "color_palette": {"primary": "#000"},
            "navigation": {"main": []},
            "mobile_optimizations": [],
            "estimated_conversion_lift": 0.12,
        },
        "meta": {},
        "error": None,
    }


class TestHappyPath:

    def test_apply_success_exits_0_text(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as engine_cls, patch(
            "engines.store_design.design_applier.apply_design",
            return_value={
                "applied": True,
                "theme_id": (
                    "gid://shopify/OnlineStoreTheme/1"
                ),
                "files_written": [
                    "assets/shopai-design-tokens.json",
                    "snippets/shopai-design.liquid",
                ],
                "error": None,
            },
        ):
            engine_cls.return_value.run.return_value = (
                _engine_success()
            )
            out, code = _capture(
                cli._cmd_store_design_apply,
                _ns(theme_id=(
                    "gid://shopify/OnlineStoreTheme/1"
                )),
            )
        assert code == 0
        assert "Design applied" in out
        assert "shopai-design-tokens.json" in out
        assert "shopai-design.liquid" in out

    def test_apply_success_exits_0_json(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as engine_cls, patch(
            "engines.store_design.design_applier.apply_design",
            return_value={
                "applied": True,
                "theme_id": (
                    "gid://shopify/OnlineStoreTheme/1"
                ),
                "files_written": [
                    "assets/shopai-design-tokens.json",
                ],
                "error": None,
            },
        ):
            engine_cls.return_value.run.return_value = (
                _engine_success()
            )
            out, code = _capture(
                cli._cmd_store_design_apply,
                _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["applied"] is True
        assert data["files_written"] == [
            "assets/shopai-design-tokens.json"
        ]
        assert data["error"] is None


class TestFailurePaths:

    def test_engine_not_success_exits_1(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as engine_cls:
            engine_cls.return_value.run.return_value = {
                "status": "error",
                "data": {},
                "meta": {},
                "error": "missing_brand",
            }
            out, code = _capture(
                cli._cmd_store_design_apply, _ns(),
            )
        assert code == 1
        assert "no recommendations" in out.lower()

    def test_apply_returns_failure_exits_1(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as engine_cls, patch(
            "engines.store_design.design_applier.apply_design",
            return_value={
                "applied": False,
                "theme_id": (
                    "gid://shopify/OnlineStoreTheme/1"
                ),
                "files_written": [],
                "error": "adapter_rejected: ACCESS_DENIED",
            },
        ):
            engine_cls.return_value.run.return_value = (
                _engine_success()
            )
            out, code = _capture(
                cli._cmd_store_design_apply, _ns(),
            )
        assert code == 1
        assert "FAILED" in out
        assert "ACCESS_DENIED" in out

    def test_engine_raise_exits_1(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as engine_cls:
            engine_cls.return_value.run.side_effect = (
                RuntimeError("engine broken")
            )
            out, code = _capture(
                cli._cmd_store_design_apply, _ns(),
            )
        assert code == 1
        assert "engine unavailable" in out.lower()

    def test_apply_raise_exits_1(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as engine_cls, patch(
            "engines.store_design.design_applier.apply_design",
            side_effect=RuntimeError("apply broken"),
        ):
            engine_cls.return_value.run.return_value = (
                _engine_success()
            )
            out, code = _capture(
                cli._cmd_store_design_apply, _ns(),
            )
        assert code == 1
        assert "unavailable" in out.lower()

    def test_apply_failure_json_includes_error(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as engine_cls, patch(
            "engines.store_design.design_applier.apply_design",
            return_value={
                "applied": False,
                "theme_id": (
                    "gid://shopify/OnlineStoreTheme/1"
                ),
                "files_written": [],
                "error": "router_unavailable",
            },
        ):
            engine_cls.return_value.run.return_value = (
                _engine_success()
            )
            out, code = _capture(
                cli._cmd_store_design_apply,
                _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["applied"] is False
        assert data["error"] == "router_unavailable"


class TestThemeIdHandling:

    def test_theme_id_passed_to_apply_design(self, cli):
        target_theme = "gid://shopify/OnlineStoreTheme/42"
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as engine_cls, patch(
            "engines.store_design.design_applier.apply_design",
            return_value={
                "applied": True,
                "theme_id": target_theme,
                "files_written": [],
                "error": None,
            },
        ) as apply_mock:
            engine_cls.return_value.run.return_value = (
                _engine_success()
            )
            _capture(
                cli._cmd_store_design_apply,
                _ns(theme_id=target_theme),
            )
        apply_mock.assert_called_once()
        kwargs = apply_mock.call_args.kwargs
        assert kwargs["theme_id"] == target_theme

    def test_store_id_passed_to_apply_design(self, cli):
        sm = _fake_sm()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as engine_cls, patch(
            "engines.store_design.design_applier.apply_design",
            return_value={
                "applied": True,
                "theme_id": (
                    "gid://shopify/OnlineStoreTheme/1"
                ),
                "files_written": [],
                "error": None,
            },
        ) as apply_mock:
            engine_cls.return_value.run.return_value = (
                _engine_success()
            )
            _capture(
                cli._cmd_store_design_apply,
                _ns(store_id="store-a"),
            )
        kwargs = apply_mock.call_args.kwargs
        assert kwargs["store_id"] == "store-a"

    def test_falls_back_to_active_store_id(self, cli):
        sm = _fake_sm()
        sm.active_store_id = "active-store"
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "engines.store_design.flow.StoreDesignEngine",
        ) as engine_cls, patch(
            "engines.store_design.design_applier.apply_design",
            return_value={
                "applied": True,
                "theme_id": (
                    "gid://shopify/OnlineStoreTheme/1"
                ),
                "files_written": [],
                "error": None,
            },
        ) as apply_mock:
            engine_cls.return_value.run.return_value = (
                _engine_success()
            )
            _capture(
                cli._cmd_store_design_apply,
                _ns(store_id=None),
            )
        kwargs = apply_mock.call_args.kwargs
        assert kwargs["store_id"] == "active-store"
