"""Dashboard scheduler controls — Option G.

Exercises the operator-facing scheduler plumbing:

* ``AutoScheduler.run_once_async`` — background thread dispatch + busy
  lock, so two rapid clicks from the dashboard cannot overlap two
  real cycles against the same store.
* ``get_status`` exposes ``busy`` + ``last_error`` so the Cycles tab
  can surface in-flight state.
* ``_handle_scheduler_{start,stop,run_once}`` — payload validation,
  interval clamping, empty-store rejection, fail-soft on exceptions.
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

from core.system.auto_scheduler import AutoScheduler
from dashboard.app import DashboardAPIHandler


def _handler() -> DashboardAPIHandler:
    h = object.__new__(DashboardAPIHandler)
    # Capture responses in-memory so we don't need real sockets.
    h._captured = []

    def _json(status, data):
        h._captured.append((status, data))

    h._json = _json
    return h


# ---------------------------------------------------------------------------
# AutoScheduler.run_once_async + busy lock
# ---------------------------------------------------------------------------


class TestRunOnceAsync:
    def test_queued_when_idle(self, monkeypatch):
        s = AutoScheduler()
        # Stub _run_cycle so the worker thread does something harmless.
        monkeypatch.setattr(
            s, "_run_cycle",
            staticmethod(lambda sid: {"cycle_id": "c1", "store_id": sid,
                                      "duration_s": 0.01}),
        )
        out = s.run_once_async("acme")
        assert out == {"status": "queued", "store_id": "acme"}
        # Let the worker finish.
        for _ in range(100):
            if not s._cycle_busy:
                break
            time.sleep(0.01)
        assert s._cycle_busy is False
        assert s._cycles_run == 1

    def test_second_call_while_busy_returns_busy(self, monkeypatch):
        s = AutoScheduler()
        gate = threading.Event()

        def _slow_cycle(store_id):
            gate.wait(timeout=2.0)
            return {"cycle_id": "c1", "store_id": store_id, "duration_s": 0.01}

        monkeypatch.setattr(s, "_run_cycle", staticmethod(_slow_cycle))

        first = s.run_once_async("acme")
        assert first == {"status": "queued", "store_id": "acme"}
        # While the worker is blocked on ``gate``, the second call must
        # see the busy flag and bail.
        second = s.run_once_async("acme")
        assert second == {"status": "busy", "store_id": "acme"}
        # Release the worker and let it finish.
        gate.set()
        for _ in range(100):
            if not s._cycle_busy:
                break
            time.sleep(0.01)
        assert s._cycle_busy is False

    def test_worker_exception_records_last_error(self, monkeypatch):
        s = AutoScheduler()

        def _boom(store_id):
            raise RuntimeError("shopify offline")

        monkeypatch.setattr(s, "_run_cycle", staticmethod(_boom))
        s.run_once_async("acme")
        for _ in range(100):
            if not s._cycle_busy:
                break
            time.sleep(0.01)
        assert s._cycle_busy is False
        assert "shopify offline" in s._last_error

    def test_get_status_surfaces_busy_and_error(self, monkeypatch):
        s = AutoScheduler()
        s._last_error = "prior failure"
        status = s.get_status()
        assert status["busy"] is False
        assert status["last_error"] == "prior failure"
        assert "running" in status
        assert "cycles_run" in status


# ---------------------------------------------------------------------------
# POST /api/scheduler/start
# ---------------------------------------------------------------------------


class TestSchedulerStartEndpoint:
    def test_start_with_defaults(self, monkeypatch):
        h = _handler()
        fake = MagicMock()
        fake.start.return_value = {
            "status": "started", "stores": ["deguar"], "interval": 600,
        }
        monkeypatch.setattr(
            "core.system.auto_scheduler.get_scheduler", lambda: fake,
        )
        h._handle_scheduler_start({})
        _status, data = h._captured[-1]
        assert data["status"] == "started"
        fake.start.assert_called_once()
        # Default path: stores=None, interval=600.
        kwargs = fake.start.call_args.kwargs
        assert kwargs.get("stores") is None
        assert kwargs.get("interval_seconds") == 600

    def test_start_respects_valid_payload(self, monkeypatch):
        h = _handler()
        fake = MagicMock()
        fake.start.return_value = {"status": "started",
                                   "stores": ["acme"], "interval": 300}
        monkeypatch.setattr(
            "core.system.auto_scheduler.get_scheduler", lambda: fake,
        )
        h._handle_scheduler_start({"stores": ["acme"], "interval": 300})
        kwargs = fake.start.call_args.kwargs
        assert kwargs["stores"] == ["acme"]
        assert kwargs["interval_seconds"] == 300

    def test_start_rejects_malformed_stores(self, monkeypatch):
        h = _handler()
        fake = MagicMock()
        fake.start.return_value = {"status": "started",
                                   "stores": ["deguar"], "interval": 600}
        monkeypatch.setattr(
            "core.system.auto_scheduler.get_scheduler", lambda: fake,
        )
        # stores must be a list of non-empty strings.
        for bad in ("acme", ["", 1], [""], 42, {"s": 1}):
            h._handle_scheduler_start({"stores": bad})
        for call in fake.start.call_args_list:
            assert call.kwargs.get("stores") is None

    def test_start_clamps_interval(self, monkeypatch):
        h = _handler()
        fake = MagicMock()
        fake.start.return_value = {"status": "started",
                                   "stores": ["deguar"], "interval": 0}
        monkeypatch.setattr(
            "core.system.auto_scheduler.get_scheduler", lambda: fake,
        )
        # Too low → clamped to 60.
        h._handle_scheduler_start({"interval": 5})
        assert fake.start.call_args.kwargs["interval_seconds"] == 60
        # Too high → clamped to 24h.
        h._handle_scheduler_start({"interval": 10_000_000})
        assert fake.start.call_args.kwargs["interval_seconds"] == 24 * 3600
        # Non-integer → default 600.
        h._handle_scheduler_start({"interval": "fast"})
        assert fake.start.call_args.kwargs["interval_seconds"] == 600

    def test_start_fails_soft(self, monkeypatch):
        h = _handler()

        def _boom():
            raise RuntimeError("scheduler broken")

        monkeypatch.setattr(
            "core.system.auto_scheduler.get_scheduler", _boom,
        )
        h._handle_scheduler_start({})
        status, data = h._captured[-1]
        assert status == 200  # fail-soft, no 500
        assert data["status"] == "error"
        assert "scheduler broken" in data["error"]


# ---------------------------------------------------------------------------
# POST /api/scheduler/stop
# ---------------------------------------------------------------------------


class TestSchedulerStopEndpoint:
    def test_stop_forwards(self, monkeypatch):
        h = _handler()
        fake = MagicMock()
        fake.stop.return_value = {"status": "stopped", "cycles_run": 7}
        monkeypatch.setattr(
            "core.system.auto_scheduler.get_scheduler", lambda: fake,
        )
        h._handle_scheduler_stop({})
        _status, data = h._captured[-1]
        assert data["status"] == "stopped"
        assert data["cycles_run"] == 7

    def test_stop_fails_soft(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr(
            "core.system.auto_scheduler.get_scheduler",
            lambda: (_ for _ in ()).throw(RuntimeError("nope")),
        )
        h._handle_scheduler_stop({})
        status, data = h._captured[-1]
        assert status == 200
        assert data["status"] == "error"


# ---------------------------------------------------------------------------
# POST /api/scheduler/run-once
# ---------------------------------------------------------------------------


class TestSchedulerRunOnceEndpoint:
    def test_queued_returns_202(self, monkeypatch):
        h = _handler()
        fake = MagicMock()
        fake.run_once_async.return_value = {"status": "queued",
                                            "store_id": "acme"}
        monkeypatch.setattr(
            "core.system.auto_scheduler.get_scheduler", lambda: fake,
        )
        h._handle_scheduler_run_once({"store_id": "acme"})
        status, data = h._captured[-1]
        assert status == 202
        assert data == {"status": "queued", "store_id": "acme"}
        fake.run_once_async.assert_called_once_with("acme")

    def test_busy_returns_200(self, monkeypatch):
        h = _handler()
        fake = MagicMock()
        fake.run_once_async.return_value = {"status": "busy",
                                            "store_id": "acme"}
        monkeypatch.setattr(
            "core.system.auto_scheduler.get_scheduler", lambda: fake,
        )
        h._handle_scheduler_run_once({"store_id": "acme"})
        status, data = h._captured[-1]
        assert status == 200
        assert data["status"] == "busy"

    def test_default_store_when_missing(self, monkeypatch):
        h = _handler()
        fake = MagicMock()
        fake.run_once_async.return_value = {"status": "queued",
                                            "store_id": "deguar"}
        monkeypatch.setattr(
            "core.system.auto_scheduler.get_scheduler", lambda: fake,
        )
        h._handle_scheduler_run_once({})
        fake.run_once_async.assert_called_once_with("deguar")

    def test_rejects_empty_store_id(self, monkeypatch):
        h = _handler()
        fake = MagicMock()
        monkeypatch.setattr(
            "core.system.auto_scheduler.get_scheduler", lambda: fake,
        )
        # Empty string after strip → 400, scheduler not touched.
        h._handle_scheduler_run_once({"store_id": "   "})
        status, data = h._captured[-1]
        assert status == 400
        assert data["status"] == "error"
        fake.run_once_async.assert_not_called()

    def test_rejects_non_string_store_id(self, monkeypatch):
        h = _handler()
        fake = MagicMock()
        monkeypatch.setattr(
            "core.system.auto_scheduler.get_scheduler", lambda: fake,
        )
        # ``None`` falls back to default; ``42`` is rejected.
        h._handle_scheduler_run_once({"store_id": 42})
        status, data = h._captured[-1]
        assert status == 400

    def test_trims_whitespace(self, monkeypatch):
        h = _handler()
        fake = MagicMock()
        fake.run_once_async.return_value = {"status": "queued",
                                            "store_id": "acme"}
        monkeypatch.setattr(
            "core.system.auto_scheduler.get_scheduler", lambda: fake,
        )
        h._handle_scheduler_run_once({"store_id": "  acme  "})
        fake.run_once_async.assert_called_once_with("acme")

    def test_fails_soft(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr(
            "core.system.auto_scheduler.get_scheduler",
            lambda: (_ for _ in ()).throw(RuntimeError("lol")),
        )
        h._handle_scheduler_run_once({"store_id": "acme"})
        status, data = h._captured[-1]
        assert status == 200
        assert data["status"] == "error"
