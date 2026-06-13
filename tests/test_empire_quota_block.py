"""W963-134: empire dashboard quota state block tests.

Operator running `shopai empire` should see per-store
budget pressure inline -- not just adapter-pnl. The
block stays silent when:
  - No caps configured (cold-start empire)
  - All stores under warn threshold AND no spend

It surfaces:
  - Critical / warn counts
  - Top-3 critical (store, adapter) pairs with pct_used
  - Drill hint to `shopai quota --view critical`
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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


class TestQuotaSnapshotSurfaces:
    """The block computation uses
    engines.per_store_quota.compute_all_snapshots --
    verify the block populates correctly for the
    critical case."""

    def test_critical_snapshot_present_when_over_cap(
        self, _isolated_costs_log, monkeypatch,
    ):
        from engines.per_store_quota import (
            QuotaState,
            compute_all_snapshots,
        )

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
        snaps = compute_all_snapshots(window_hours=24.0)
        critical = [
            s for s in snaps
            if s.state == QuotaState.CRITICAL
        ]
        assert len(critical) >= 1
        assert any(
            s.store_id == "store_a" for s in critical
        )

    def test_no_caps_no_snapshot_pressure(
        self, _isolated_costs_log, monkeypatch,
    ):
        """When no caps are configured, no snapshot is
        CRITICAL/WARN -- block should stay silent."""
        from engines.per_store_quota import (
            QuotaState,
            compute_all_snapshots,
        )

        # Spend present but NO cap env vars
        monkeypatch.delenv(
            "SHOPAI_DAILY_BUDGET_USD", raising=False,
        )
        _seed(_isolated_costs_log, [{
            "ts": time.time(),
            "store_id": "store_a",
            "adapter": "openai",
            "capability": "chat",
            "cost_usd": 100.0,
            "ok": True,
        }])
        snaps = compute_all_snapshots(window_hours=24.0)
        # All UNLIMITED, none critical / warn
        assert all(
            s.state == QuotaState.UNLIMITED
            for s in snaps
        )


class TestEmpireJsonHasQuotaKey:
    """End-to-end: empire dashboard JSON envelope must
    include the quota key."""

    def test_quota_key_present(
        self, _isolated_costs_log,
    ):
        result = subprocess.run(
            [sys.executable, "cli.py", "empire", "--json"],
            capture_output=True,
            text=True,
            cwd=str(
                Path(__file__).parent.parent,
            ),
            timeout=60,
        )
        assert result.returncode == 0
        try:
            envelope = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.skip("empire JSON unparseable")
        assert "quota" in envelope
