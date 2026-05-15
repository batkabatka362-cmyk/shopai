"""Regression test for the latent unknown-engine crash in
``shopai run``.

Pre-PR: ``shopai run <unknown>`` would crash with
``AttributeError: 'NoneType' object has no attribute 'run'``
because ``engines.registry.get_engine`` returns ``None`` for
unknown engine names and the handler called ``engine.run(...)``
without checking.

Now: clean error message + exit 1, pointing the operator at
``shopai engines`` for the registered list.
"""
from __future__ import annotations

import argparse
import importlib.util
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


@pytest.fixture
def stub_store_manager(monkeypatch):
    """Mock the store manager dependency so ``run`` doesn't touch
    real state."""
    mock_sm = MagicMock()
    mock_sm.active_store_id = "test_store"
    monkeypatch.setattr(
        "cli._get_store_manager", lambda: mock_sm,
    )
    return mock_sm


@pytest.fixture
def stub_data_provider(monkeypatch):
    """Mock DataProvider to return empty data without touching the
    real store."""
    class _FakeProvider:
        def __init__(self, sm):
            self.sm = sm

        def get_data_for_engine(self, task_type, store_id):
            return {"source": "test"}

    monkeypatch.setattr(
        "data_pipeline.store.data_provider.DataProvider",
        _FakeProvider,
    )


class TestRunUnknownEngine:

    def test_unknown_engine_exits_1_with_message(
        self, cli, stub_store_manager, stub_data_provider,
    ):
        """Pre-PR this crashed with AttributeError. Now: clean
        message + exit 1."""
        with patch(
            "engines.registry.get_engine",
            return_value=None,
        ):
            out, code = _capture(
                cli._cmd_run,
                argparse.Namespace(
                    task_type="definitely_not_a_real_engine",
                    store="", params="{}",
                ),
            )
        assert code == 1
        assert "unknown engine" in out.lower()
        assert "definitely_not_a_real_engine" in out
        # Helpful pointer to discoverability
        assert "shopai engines" in out

    def test_get_engine_raises_keyerror_also_handled(
        self, cli, stub_store_manager, stub_data_provider,
    ):
        """A future ``get_engine`` raising KeyError (the legacy
        contract) also routes to the clean error path."""
        with patch(
            "engines.registry.get_engine",
            side_effect=KeyError("not_registered"),
        ):
            out, code = _capture(
                cli._cmd_run,
                argparse.Namespace(
                    task_type="some_name", store="", params="{}",
                ),
            )
        assert code == 1
        assert "unknown engine" in out.lower()


class TestRunHappyPath:

    def test_known_engine_executes(
        self, cli, stub_store_manager, stub_data_provider,
    ):
        """Sanity: a real engine still runs without modifications.
        Catches "I accidentally broke the success path while
        adding the error-path check"."""
        mock_engine = MagicMock()
        mock_engine.run.return_value = {"status": "success"}
        with patch(
            "engines.registry.get_engine",
            return_value=mock_engine,
        ):
            out, code = _capture(
                cli._cmd_run,
                argparse.Namespace(
                    task_type="cart_recovery", store="", params="{}",
                ),
            )
        assert code == 0
        assert "Running cart_recovery" in out
        assert '"status": "success"' in out
        mock_engine.run.assert_called_once()
