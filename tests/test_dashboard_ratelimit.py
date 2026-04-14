"""Dashboard rate-limit endpoint — Option U phase 3.

Tests the ``_collect_ratelimit_snapshot`` rollup and the
``/api/ratelimit`` handler wiring.
"""
from __future__ import annotations

import pytest

from core.adapters.rate_limit import (
    RateLimit,
    RateLimiter,
    reset_rate_limiter,
)
from dashboard import app as dash
from dashboard.app import DashboardAPIHandler, _collect_ratelimit_snapshot


def _handler() -> DashboardAPIHandler:
    return object.__new__(DashboardAPIHandler)


@pytest.fixture(autouse=True)
def _reset_limiter():
    reset_rate_limiter()
    yield
    reset_rate_limiter()


class TestCollectRateLimitSnapshot:
    def test_rolls_up_totals_from_default_catalog(self):
        snap = _collect_ratelimit_snapshot()
        # Default catalog ships with real-vendor policies (openai,
        # anthropic, …). Every bucket starts full, so everything
        # should grade as "ok".
        assert "timestamp" in snap
        assert snap["totals"].get("ok", 0) >= 1
        assert snap["totals"].get("throttled", 0) == 0

    def test_rows_sorted_by_name(self, monkeypatch):
        lim = RateLimiter(policies={
            "zebra": RateLimit(requests_per_min=10),
            "alpha": RateLimit(requests_per_min=10),
        })
        monkeypatch.setattr(
            "core.adapters.rate_limit.get_rate_limiter", lambda: lim,
        )
        snap = _collect_ratelimit_snapshot()
        names = [r["adapter"] for r in snap["rows"]]
        assert names == sorted(names)

    def test_near_status_reflected_in_totals(self, monkeypatch):
        lim = RateLimiter(policies={
            "x": RateLimit(requests_per_min=10),
        })
        # Burn 9 tokens → 90% used → solidly in the "near" band
        # (80%-99%). Using 8/10 would flirt with the boundary and
        # lose to sub-token refill between call and read.
        for _ in range(9):
            lim.can_call("x")
        monkeypatch.setattr(
            "core.adapters.rate_limit.get_rate_limiter", lambda: lim,
        )
        snap = _collect_ratelimit_snapshot()
        assert snap["totals"]["near"] == 1


class TestRateLimitEndpoint:
    def test_api_ratelimit_wraps_snapshot(self, monkeypatch):
        h = _handler()
        captured: dict = {}

        def _json(status, payload):
            captured["status"] = status
            captured["payload"] = payload

        monkeypatch.setattr(h, "_json", _json)
        monkeypatch.setattr(
            dash, "_collect_ratelimit_snapshot",
            lambda: {
                "timestamp": 1.0,
                "totals": {"throttled": 0, "near": 1, "ok": 3, "idle": 0},
                "rows": [{"adapter": "x", "status": "near"}],
            },
        )
        h._api_ratelimit()
        assert captured["status"] == 200
        assert captured["payload"]["totals"]["near"] == 1

    def test_api_ratelimit_handles_collector_failure(self, monkeypatch):
        h = _handler()
        captured: dict = {}

        def _json(status, payload):
            captured["status"] = status
            captured["payload"] = payload

        monkeypatch.setattr(h, "_json", _json)

        def _boom():
            raise RuntimeError("limiter gone")

        monkeypatch.setattr(dash, "_collect_ratelimit_snapshot", _boom)
        h._api_ratelimit()
        assert captured["status"] == 200
        assert captured["payload"]["totals"] == {
            "throttled": 0, "near": 0, "ok": 0, "idle": 0,
        }
        assert "error" in captured["payload"]
