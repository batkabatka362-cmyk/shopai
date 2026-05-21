"""Tests for ``shopai launch``.

Operator-facing CLI for the autonomous store launch flow.
Mirrors the ``launch-audit`` CLI pattern (#466) but invokes
the WRITER side -- ``launch_store`` -- rather than the
read-only audit.

Coverage:
  - Ready_to_launch=True -> exit 0 + per-step OK list
  - Ready_to_launch=False with mixed steps -> exit 1 + breakdown
  - launch_store raises -> exit 0 with friendly unavailable
    (matches scopes-live-check convention -- a probe failure
    isn't a launch failure)
  - --json output (success + failure paths)
  - All optional kwargs propagate
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from unittest.mock import patch

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
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _full_result(ready=True):
    return {
        "policies": {"applied_count": 5, "results": []},
        "pages": {"applied_count": 4, "results": []},
        "discount": {
            "applied": True, "code": "WELCOME15",
            "percentage": 15, "error": None,
        },
        "collections": {
            "applied_count": 4, "results": [],
        },
        "checklist": [
            {"step": "policies",    "ok": True,  "applied": 5,
             "error": None},
            {"step": "pages",       "ok": True,  "applied": 4,
             "error": None},
            {"step": "discount",    "ok": True,  "applied": 1,
             "error": None},
            {"step": "collections", "ok": ready, "applied": 4,
             "error": None if ready else "rejected"},
        ],
        "ready_to_launch": ready,
    }


class TestHappyPath:

    def test_ready_exits_0_text(self, cli):
        with patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_full_result(ready=True),
        ):
            out, code = _capture(cli._cmd_launch, _ns())
        assert code == 0
        assert "Launch complete" in out
        assert "4/4" in out
        assert "ready to take orders" in out.lower()
        # Each step shows OK
        assert out.count("[OK]") == 4

    def test_ready_exits_0_json(self, cli):
        with patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_full_result(ready=True),
        ):
            out, code = _capture(cli._cmd_launch, _ns(json=True))
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is True
        assert data["ready_to_launch"] is True
        assert len(data["checklist"]) == 4
        assert data["error"] is None


class TestFailingLaunch:

    def test_partial_exits_1_text(self, cli):
        with patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_full_result(ready=False),
        ):
            out, code = _capture(cli._cmd_launch, _ns())
        assert code == 1
        assert "INCOMPLETE" in out
        # The failed step appears with FAIL marker + error
        assert "[FAIL]" in out
        assert "collections" in out
        assert "rejected" in out
        # And the operator-facing fix hint surfaces
        assert "launch-audit" in out

    def test_partial_exits_1_json(self, cli):
        with patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_full_result(ready=False),
        ):
            out, code = _capture(
                cli._cmd_launch, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["ok"] is False
        assert data["ready_to_launch"] is False


class TestResilience:

    def test_launch_raise_renders_unavailable(self, cli):
        with patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            side_effect=RuntimeError("boom"),
        ):
            out, code = _capture(cli._cmd_launch, _ns())
        # Exit 0 (not 1) -- a probe failure isn't a launch
        # failure. Matches the scopes-live-check convention.
        assert code == 0
        assert "unavailable" in out.lower()

    def test_launch_raise_json_emits_error(self, cli):
        with patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            side_effect=RuntimeError("boom"),
        ):
            out, code = _capture(
                cli._cmd_launch, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is None
        assert data["error"] == "launch_unavailable"
        assert "boom" in data["message"]


class TestKwargsPropagation:

    def test_all_kwargs_thread_through(self, cli):
        with patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_full_result(ready=True),
        ) as mock_launch:
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
        mock_launch.assert_called_once()
        kwargs = mock_launch.call_args.kwargs
        assert kwargs["store_name"] == "Acme Beauty"
        assert kwargs["niche"] == "beauty"
        assert kwargs["region"] == "eu"
        assert kwargs["founder_name"] == "Jane"
        assert kwargs["store_id"] == "store-a"
        assert kwargs["include_legal_notice"] is True
        assert kwargs["include_subscription_policy"] is True

    def test_defaults_when_minimal_args(self, cli):
        with patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value=_full_result(ready=True),
        ) as mock_launch:
            _capture(cli._cmd_launch, _ns(store_name="Acme"))
        kwargs = mock_launch.call_args.kwargs
        assert kwargs["niche"] == "general"
        assert kwargs["region"] == "us"
        assert kwargs["founder_name"] is None
        assert kwargs["store_id"] is None
        assert kwargs["include_legal_notice"] is False
        assert kwargs["include_subscription_policy"] is False
