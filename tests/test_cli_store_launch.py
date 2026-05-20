"""Tests for ``shopai store launch`` CLI command.

Thin wrapper around
``engines.store_setup.launch_orchestrator.launch_store``.
Pulls niche + display name from the store registry when not
supplied as flags; renders the per-step checklist + exits 1
when any step failed.

Coverage:
  1. Successful launch -> exit 0, LAUNCHED label, JSON envelope.
  2. Incomplete launch -> exit 1, INCOMPLETE, error rendered.
  3. Store registry fallback: name + niche from sm.get_store.
  4. Explicit flags override registry defaults.
  5. Active-store fallback when store_id arg omitted.
  6. Empty store_name -> clean error + exit 1.
  7. Optional flags (legal notice, subscription policy,
     founder name) propagate to launch_store kwargs.
  8. Module import failure -> clean error + exit 1.
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
        store_id=None,
        name=None,
        niche=None,
        region="us",
        founder_name=None,
        include_legal_notice=False,
        include_subscription_policy=False,
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _success_result():
    return {
        "policies": {"applied_count": 5, "results": []},
        "pages": {"applied_count": 4, "results": []},
        "checklist": [
            {"step": "policies", "ok": True,
             "applied": 5, "error": None},
            {"step": "pages", "ok": True,
             "applied": 4, "error": None},
        ],
        "ready_to_launch": True,
    }


def _incomplete_result():
    return {
        "policies": {
            "applied_count": 0,
            "results": [],
            "error": "router_unavailable",
        },
        "pages": {"applied_count": 4, "results": []},
        "checklist": [
            {"step": "policies", "ok": False,
             "applied": 0, "error": "router_unavailable"},
            {"step": "pages", "ok": True,
             "applied": 4, "error": None},
        ],
        "ready_to_launch": False,
    }


def _fake_sm(*, active_id=None, store_record=None):
    sm = MagicMock()
    sm.active_store_id = active_id
    sm.get_store.return_value = store_record or {}
    return sm


class TestSuccessfulLaunch:

    def test_text_says_launched(self, cli):
        with patch.object(
            cli, "_get_store_manager",
            return_value=_fake_sm(
                store_record={
                    "name": "Acme Beauty", "niche": "beauty",
                },
            ),
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "launch_store",
            return_value=_success_result(),
        ):
            out, code = _capture(
                cli._cmd_store_launch, _ns(store_id="store-a"),
            )
        assert code == 0
        assert "LAUNCHED" in out
        assert "Acme Beauty" in out
        assert "beauty" in out
        # Each checklist row rendered
        assert "policies" in out
        assert "pages" in out

    def test_json_envelope(self, cli):
        with patch.object(
            cli, "_get_store_manager",
            return_value=_fake_sm(
                store_record={
                    "name": "Acme", "niche": "general",
                },
            ),
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "launch_store",
            return_value=_success_result(),
        ):
            out, code = _capture(
                cli._cmd_store_launch,
                _ns(store_id="s", json=True),
            )
        data = json.loads(out)
        assert data["ready_to_launch"] is True
        assert len(data["checklist"]) == 2
        assert code == 0


class TestIncomplete:

    def test_incomplete_exits_one(self, cli):
        with patch.object(
            cli, "_get_store_manager",
            return_value=_fake_sm(
                store_record={"name": "Acme"},
            ),
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "launch_store",
            return_value=_incomplete_result(),
        ):
            out, code = _capture(
                cli._cmd_store_launch, _ns(store_id="s"),
            )
        assert code == 1
        assert "INCOMPLETE" in out
        assert "router_unavailable" in out
        assert "shopai store audit" in out

    def test_incomplete_json_exit_one(self, cli):
        with patch.object(
            cli, "_get_store_manager",
            return_value=_fake_sm(
                store_record={"name": "Acme"},
            ),
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "launch_store",
            return_value=_incomplete_result(),
        ):
            out, code = _capture(
                cli._cmd_store_launch,
                _ns(store_id="s", json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["ready_to_launch"] is False


class TestRegistryFallback:

    def test_name_and_niche_from_registry(self, cli):
        with patch.object(
            cli, "_get_store_manager",
            return_value=_fake_sm(
                store_record={
                    "name": "Registry Name",
                    "niche": "tech",
                },
            ),
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "launch_store",
            return_value=_success_result(),
        ) as launch_mock:
            _capture(
                cli._cmd_store_launch, _ns(store_id="s"),
            )
        kw = launch_mock.call_args.kwargs
        assert kw["store_name"] == "Registry Name"
        assert kw["niche"] == "tech"

    def test_explicit_flags_override_registry(self, cli):
        with patch.object(
            cli, "_get_store_manager",
            return_value=_fake_sm(
                store_record={
                    "name": "Registry Name",
                    "niche": "tech",
                },
            ),
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "launch_store",
            return_value=_success_result(),
        ) as launch_mock:
            _capture(
                cli._cmd_store_launch,
                _ns(
                    store_id="s",
                    name="Flag Name",
                    niche="fashion",
                ),
            )
        kw = launch_mock.call_args.kwargs
        assert kw["store_name"] == "Flag Name"
        assert kw["niche"] == "fashion"

    def test_active_store_fallback_when_no_arg(self, cli):
        with patch.object(
            cli, "_get_store_manager",
            return_value=_fake_sm(
                active_id="active-store",
                store_record={"name": "Acme"},
            ),
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "launch_store",
            return_value=_success_result(),
        ) as launch_mock:
            _capture(
                cli._cmd_store_launch,
                _ns(store_id=None),
            )
        kw = launch_mock.call_args.kwargs
        assert kw["store_id"] == "active-store"

    def test_niche_falls_back_to_general(self, cli):
        with patch.object(
            cli, "_get_store_manager",
            return_value=_fake_sm(
                store_record={"name": "Acme"},
            ),
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "launch_store",
            return_value=_success_result(),
        ) as launch_mock:
            _capture(
                cli._cmd_store_launch, _ns(store_id="s"),
            )
        assert (
            launch_mock.call_args.kwargs["niche"]
            == "general"
        )


class TestEmptyStoreName:

    def test_no_name_anywhere_exits_one(self, cli):
        # Registry returns empty record, no --name flag, store_id
        # is a number-ish string that becomes the fallback name
        # only when truthy. We pass empty store_id so all sources
        # return empty.
        with patch.object(
            cli, "_get_store_manager",
            return_value=_fake_sm(store_record={}),
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "launch_store",
        ) as launch_mock:
            out, code = _capture(
                cli._cmd_store_launch, _ns(store_id=""),
            )
        assert code == 1
        assert "store_name_required" in out
        # Orchestrator was never called
        launch_mock.assert_not_called()


class TestOptionalFlags:

    def test_legal_notice_and_subscription_forward(self, cli):
        with patch.object(
            cli, "_get_store_manager",
            return_value=_fake_sm(
                store_record={"name": "Acme"},
            ),
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "launch_store",
            return_value=_success_result(),
        ) as launch_mock:
            _capture(
                cli._cmd_store_launch,
                _ns(
                    store_id="s",
                    include_legal_notice=True,
                    include_subscription_policy=True,
                ),
            )
        kw = launch_mock.call_args.kwargs
        assert kw["include_legal_notice"] is True
        assert kw["include_subscription_policy"] is True

    def test_founder_name_forwards(self, cli):
        with patch.object(
            cli, "_get_store_manager",
            return_value=_fake_sm(
                store_record={"name": "Acme"},
            ),
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "launch_store",
            return_value=_success_result(),
        ) as launch_mock:
            _capture(
                cli._cmd_store_launch,
                _ns(
                    store_id="s",
                    founder_name="Jane Doe",
                ),
            )
        assert (
            launch_mock.call_args.kwargs["founder_name"]
            == "Jane Doe"
        )

    def test_region_propagates(self, cli):
        with patch.object(
            cli, "_get_store_manager",
            return_value=_fake_sm(
                store_record={"name": "Acme"},
            ),
        ), patch(
            "engines.store_setup.launch_orchestrator."
            "launch_store",
            return_value=_success_result(),
        ) as launch_mock:
            _capture(
                cli._cmd_store_launch,
                _ns(store_id="s", region="eu"),
            )
        assert (
            launch_mock.call_args.kwargs["region"] == "eu"
        )


class TestImportFailure:

    def test_import_error_clean_text(self, cli):
        import builtins
        real_import = builtins.__import__

        def _raise(name, *a, **kw):
            if name == (
                "engines.store_setup.launch_orchestrator"
            ):
                raise ImportError("module missing")
            return real_import(name, *a, **kw)

        with patch.object(
            cli, "_get_store_manager",
            return_value=_fake_sm(
                store_record={"name": "Acme"},
            ),
        ), patch(
            "builtins.__import__", side_effect=_raise,
        ):
            out, code = _capture(
                cli._cmd_store_launch, _ns(store_id="s"),
            )
        assert code == 1
        assert "launch_orchestrator unavailable" in out

    def test_import_error_json_envelope(self, cli):
        import builtins
        real_import = builtins.__import__

        def _raise(name, *a, **kw):
            if name == (
                "engines.store_setup.launch_orchestrator"
            ):
                raise ImportError("module missing")
            return real_import(name, *a, **kw)

        with patch.object(
            cli, "_get_store_manager",
            return_value=_fake_sm(
                store_record={"name": "Acme"},
            ),
        ), patch(
            "builtins.__import__", side_effect=_raise,
        ):
            out, code = _capture(
                cli._cmd_store_launch,
                _ns(store_id="s", json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["status"] == "error"
