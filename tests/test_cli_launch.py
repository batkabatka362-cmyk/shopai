"""Tests for ``shopai launch``.

Flagship CLI: single command store launch. Wraps
``launch_orchestrator.launch_store`` and renders the result.

Coverage:
  - Empty store_name -> friendly error + exit 1
  - All steps OK -> READY header, exit 0, post-launch
    next-step pointer
  - Partial fail -> NOT READY + failed-steps line
  - --strict + not ready -> exit 1
  - --strict + ready -> exit 0
  - --json output
  - Args propagate to launch_store
  - launch_store raises -> friendly text, exit 0
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
        store_name="Acme",
        niche="general",
        region="us",
        founder_name=None,
        store_id=None,
        include_legal_notice=False,
        include_subscription_policy=False,
        logo_url=None,
        favicon_url=None,
        hero_url=None,
        og_image_url=None,
        strict=False,
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_sm():
    sm = MagicMock()
    sm.active_store_id = None
    return sm


def _ready_result():
    return {
        "policies": {"applied_count": 5, "results": []},
        "pages": {"applied_count": 4, "results": []},
        "checklist": [
            {"step": "policies", "ok": True, "applied": 5,
             "error": None},
            {"step": "pages", "ok": True, "applied": 4,
             "error": None},
        ],
        "ready_to_launch": True,
    }


def _partial_result():
    return {
        "policies": {"applied_count": 5, "results": []},
        "pages": {
            "applied_count": 0, "results": [],
            "error": "rejected",
        },
        "checklist": [
            {"step": "policies", "ok": True, "applied": 5,
             "error": None},
            {"step": "pages", "ok": False, "applied": 0,
             "error": "rejected"},
        ],
        "ready_to_launch": False,
    }


class TestEmptyName:

    def test_empty_name_exits_1(self, cli):
        result = {
            "policies": {"applied_count": 0, "results": []},
            "pages": {"applied_count": 0, "results": []},
            "checklist": [],
            "ready_to_launch": False,
            "error": "store_name_required",
        }
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=result,
        ):
            out, code = _capture(
                cli._cmd_launch, _ns(store_name=""),
            )
        assert code == 1
        assert "store_name is required" in out


class TestReady:

    def test_ready_header_exit_0(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_ready_result(),
        ):
            out, code = _capture(cli._cmd_launch, _ns())
        assert code == 0
        assert "READY TO LAUNCH" in out
        assert "[OK  ] policies" in out
        assert "[OK  ] pages" in out
        # Mentions the next-step command
        assert "post-launch" in out

    def test_json_output(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_ready_result(),
        ):
            out, code = _capture(
                cli._cmd_launch, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["ready_to_launch"] is True


class TestPartial:

    def test_partial_shows_failed_steps(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_partial_result(),
        ):
            out, code = _capture(cli._cmd_launch, _ns())
        # Default: informational exit 0
        assert code == 0
        assert "NOT READY" in out
        assert "[FAIL] pages" in out
        assert "error=rejected" in out
        assert "Failed steps" in out
        assert "launch-audit" in out

    def test_strict_partial_exits_1(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_partial_result(),
        ):
            out, code = _capture(
                cli._cmd_launch, _ns(strict=True),
            )
        assert code == 1

    def test_strict_ready_exits_0(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_ready_result(),
        ):
            out, code = _capture(
                cli._cmd_launch, _ns(strict=True),
            )
        assert code == 0


class TestResilience:

    def test_launch_store_raise(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            side_effect=RuntimeError("boom"),
        ):
            out, code = _capture(cli._cmd_launch, _ns())
        # Engine raise stays an exit-0 in default mode (the
        # mission is "tell the operator what happened", not
        # "blow up the cron")
        assert code == 0
        assert "failed" in out.lower()


class TestKwargPropagation:

    def test_all_kwargs_forwarded(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_ready_result(),
        ) as launch_mock:
            _capture(
                cli._cmd_launch,
                _ns(
                    store_name="Acme Beauty",
                    niche="beauty",
                    region="eu",
                    founder_name="Jane",
                    store_id="store-a",
                    include_legal_notice=True,
                    include_subscription_policy=True,
                ),
            )
        kwargs = launch_mock.call_args.kwargs
        assert kwargs["store_name"] == "Acme Beauty"
        assert kwargs["niche"] == "beauty"
        assert kwargs["region"] == "eu"
        assert kwargs["founder_name"] == "Jane"
        assert kwargs["store_id"] == "store-a"
        assert kwargs["include_legal_notice"] is True
        assert kwargs["include_subscription_policy"] is True

    def test_skipped_steps_render_distinct_mark(self, cli):
        """A skipped step renders [SKIP] not [OK  ] so the
        operator can tell "didn't attempt" from "succeeded".
        """
        result = {
            "policies": {"applied_count": 5, "results": []},
            "pages": {"applied_count": 4, "results": []},
            "discount": {"applied": True, "code": "W"},
            "collections": {"applied_count": 4, "results": []},
            "brand": {"uploaded_count": 0, "files": [],
                      "skipped": True},
            "design": {"applied": False, "skipped": True,
                       "error": "no_main_theme"},
            "checklist": [
                {"step": "policies", "ok": True, "applied": 5,
                 "error": None},
                {"step": "pages", "ok": True, "applied": 4,
                 "error": None},
                {"step": "discount", "ok": True, "applied": 1,
                 "error": None},
                {"step": "collections", "ok": True, "applied": 4,
                 "error": None},
                {"step": "brand", "ok": True, "applied": 0,
                 "skipped": True, "error": None},
                {"step": "design", "ok": True, "applied": 0,
                 "skipped": True, "error": "no_main_theme"},
            ],
            "ready_to_launch": True,
        }
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=result,
        ):
            out, code = _capture(cli._cmd_launch, _ns())
        assert code == 0
        assert "[SKIP] brand" in out
        assert "[SKIP] design" in out
        # The skip reason renders as 'reason=' (not 'error=')
        assert "reason=no_main_theme" in out
        # Mandatory steps still render [OK  ]
        assert "[OK  ] policies" in out

    def test_brand_urls_forwarded(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_ready_result(),
        ) as launch_mock:
            _capture(
                cli._cmd_launch,
                _ns(
                    logo_url="https://cdn/logo.png",
                    favicon_url="https://cdn/favicon.ico",
                    hero_url="https://cdn/hero.jpg",
                    og_image_url="https://cdn/og.jpg",
                ),
            )
        kwargs = launch_mock.call_args.kwargs
        assert kwargs["logo_url"] == "https://cdn/logo.png"
        assert kwargs["favicon_url"] == "https://cdn/favicon.ico"
        assert kwargs["hero_url"] == "https://cdn/hero.jpg"
        assert kwargs["og_image_url"] == "https://cdn/og.jpg"
