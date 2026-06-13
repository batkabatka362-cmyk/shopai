"""W963-140: per-store quota probe in earn-readiness
composer.

A 20-store empire about to fire its first cycle needs
to know if any store is already at CRITICAL/EXHAUSTED
budget BEFORE launching. The cycle would autopause that
store on first iteration -- forewarned operator can
either raise caps or enable autopause explicitly.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engines.earn_readiness.composer import (
    _check_per_store_quota,
    build_readiness,
)
from engines.per_store_costs import recorder as cost_recorder


@pytest.fixture(autouse=True)
def _isolated_costs_log(tmp_path, monkeypatch):
    live = tmp_path / "per_store_costs.jsonl"
    archive = (
        tmp_path / "per_store_costs.archive.jsonl"
    )
    monkeypatch.setattr(cost_recorder, "DATA_PATH", live)
    monkeypatch.setattr(
        cost_recorder, "ARCHIVE_PATH", archive,
    )
    from engines.per_store_costs import query as qmod
    monkeypatch.setattr(qmod, "DATA_PATH", live)
    monkeypatch.setattr(qmod, "ARCHIVE_PATH", archive)
    yield live


def _seed(live: Path, events: list[dict]) -> None:
    live.parent.mkdir(parents=True, exist_ok=True)
    with open(live, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


class TestPerStoreQuotaProbe:
    def test_no_pressure_returns_ok(
        self, _isolated_costs_log,
    ):
        # No spend at all
        check = _check_per_store_quota()
        assert check.cls == "ok"
        assert check.name == "per_store_quota"

    def test_critical_store_returns_warn(
        self, _isolated_costs_log, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "5",
        )
        _seed(_isolated_costs_log, [{
            "ts": time.time(),
            "store_id": "store_a",
            "adapter": "openai",
            "capability": "chat",
            "cost_usd": 50.0,
            "ok": True,
        }])
        check = _check_per_store_quota()
        assert check.cls == "warn"
        assert "over budget cap" in check.headline
        # detail names the offender
        assert "store_a" in check.detail
        # fix points operator to the right CLI
        assert "shopai quota --view critical" in check.fix

    def test_warn_only_returns_warn(
        self, _isolated_costs_log, monkeypatch,
    ):
        """Only WARN stores (no critical) -> still warn
        cls but different headline + fix."""
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "10",
        )
        _seed(_isolated_costs_log, [{
            "ts": time.time(),
            "store_id": "store_a",
            "adapter": "openai",
            "capability": "chat",
            "cost_usd": 8.0,  # 80% used at default
                              # warn_ratio=0.7 -> WARN
            "ok": True,
        }])
        check = _check_per_store_quota()
        assert check.cls == "warn"
        assert "approaching" in check.headline
        assert "shopai quota --view warn" in check.fix

    def test_probe_failure_returns_warn(
        self, monkeypatch,
    ):
        """When the per-store substrate is unavailable
        the probe degrades to WARN, not crash."""
        with patch(
            "engines.per_store_quota.critical_stores",
            side_effect=RuntimeError("test: substrate down"),
        ):
            check = _check_per_store_quota()
        assert check.cls == "warn"
        assert "unavailable" in check.headline.lower()


class TestComposerIncludesQuotaCheck:
    """build_readiness must include the new check in its
    output -- 6 slices instead of 5."""

    def test_check_appears_in_report(
        self, _isolated_costs_log, monkeypatch,
    ):
        # Mock out the other 5 probes so they don't slow
        # the test or depend on environmental state
        from engines.earn_readiness import composer as c
        with patch.object(
            c, "_check_api_inventory",
            return_value=c.CheckSlice(
                name="api_inventory", cls="ok",
                headline="ok",
            ),
        ), patch.object(
            c, "_check_wired_engines",
            return_value=c.CheckSlice(
                name="wired_engines", cls="ok",
                headline="ok",
            ),
        ), patch.object(
            c, "_check_go_live",
            return_value=c.CheckSlice(
                name="go_live", cls="ok",
                headline="ok",
            ),
        ), patch.object(
            c, "_check_autonomy_doctor",
            return_value=c.CheckSlice(
                name="autonomy_doctor", cls="ok",
                headline="ok",
            ),
        ), patch.object(
            c, "_check_cycle_history",
            return_value=c.CheckSlice(
                name="cycle_history", cls="ok",
                headline="ok",
            ),
        ):
            report = build_readiness()

        check_names = [
            c.name for c in report.checks
        ]
        assert "per_store_quota" in check_names
        assert len(report.checks) == 6
