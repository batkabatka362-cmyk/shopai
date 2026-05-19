"""Tests for the Quarantine & alerts block on engine pages.

This block surfaces -- per engine -- the operator-relevant
fragments of ``core.approval.quarantine.QuarantineState`` plus
the recent ``core.approval.alert_history`` log so an operator
reviewing an Obsidian engine page immediately sees:

  * whether the engine is exempt / released / alert-paused;
  * which stores are paused (when scope is per-store);
  * a 7-day alert-streak count;
  * the last 5 ``AlertEvent`` rows (newest first).

Each line is omitted independently; an engine with no state
produces no section.

Coverage:
  1. Renderer-level (``_render_quarantine_block``) -- direct
     calls covering each independent line.
  2. Exporter-level -- end-to-end through ``.export()`` with
     real ``QuarantineState`` and ``alert_history`` modules.
  3. Source-failure isolation -- a quarantine / alert-history
     read that raises does NOT abort the export.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core.knowledge import ObsidianExporter
from core.knowledge.exporter import _render_quarantine_block


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    return tmp_path / "vault"


@pytest.fixture
def isolated_data(tmp_path: Path, monkeypatch):
    """Point quarantine state + alert history at a private dir."""
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    return tmp_path


def _write_quarantine_state(
    data_dir: Path,
    *,
    exemptions=(),
    released=(),
    alert_paused=(),
) -> None:
    payload = {
        "exemptions": list(exemptions),
        "released": list(released),
        "alert_paused": [list(p) for p in alert_paused],
    }
    (data_dir / "quarantine_state.json").write_text(
        json.dumps(payload), encoding="utf-8",
    )


def _alert_event(
    *, engine: str = "loyalty",
    drop: float = 0.40,
    recent_score: float = 1.5,
    baseline_score: float = 3.0,
    store_id: str | None = None,
    recorded_at: float | None = None,
):
    """Build an AlertEvent dataclass instance."""
    from core.approval.alert_history import AlertEvent
    return AlertEvent(
        engine=engine,
        recorded_at=recorded_at or time.time(),
        drop=drop,
        recent_score=recent_score,
        baseline_score=baseline_score,
        store_id=store_id,
    )


# --- Renderer-level coverage ----------------------------------


class TestRenderQuarantineBlock:

    def test_empty_inputs_produce_empty_list(self):
        assert _render_quarantine_block(None, None) == []
        assert _render_quarantine_block({}, {}) == []

    def test_exempt_line(self):
        lines = _render_quarantine_block(
            {"exempt": True}, None,
        )
        assert any("Exempt" in line for line in lines)

    def test_released_line(self):
        lines = _render_quarantine_block(
            {"released": True}, None,
        )
        assert any("Released" in line for line in lines)

    def test_fleet_pause_line(self):
        lines = _render_quarantine_block(
            {"fleet_paused": True}, None,
        )
        assert any("Alert-paused (fleet)" in line for line in lines)

    def test_per_store_pause_lists_each_store(self):
        lines = _render_quarantine_block(
            {"stores_paused": ["store_a", "store_b"]}, None,
        )
        assert any(
            "Alert-paused (per-store)" in line for line in lines
        )
        assert any("`store_a`" in line for line in lines)
        assert any("`store_b`" in line for line in lines)

    def test_streak_days_line(self):
        lines = _render_quarantine_block(
            None, {"streak_days": 4},
        )
        assert any("4 day(s)" in line for line in lines)

    def test_recent_alerts_bullets(self):
        event = _alert_event(
            engine="loyalty",
            drop=0.55,
            recent_score=1.20,
            baseline_score=2.80,
            store_id="store_a",
        )
        lines = _render_quarantine_block(
            None, {"recent": [event], "streak_days": 0},
        )
        joined = "\n".join(lines)
        assert "Recent alerts:" in joined
        assert "@store_a" in joined
        assert "55% drop" in joined
        assert "recent=1.20" in joined
        assert "baseline=2.80" in joined

    def test_fleet_event_renders_fleet_scope(self):
        event = _alert_event(store_id=None)
        lines = _render_quarantine_block(
            None, {"recent": [event], "streak_days": 0},
        )
        assert any("(fleet)" in line for line in lines)

    def test_recent_capped_at_five(self):
        events = [
            _alert_event(recent_score=float(i))
            for i in range(7)
        ]
        lines = _render_quarantine_block(
            None, {"recent": events, "streak_days": 0},
        )
        # 5 bullets max, regardless of how many events are passed
        bullets = [line for line in lines if line.startswith("    -")]
        assert len(bullets) == 5


# --- Exporter end-to-end --------------------------------------


class TestExporterIntegration:

    def test_engine_page_renders_quarantine_section(
        self, vault, isolated_data,
    ):
        _write_quarantine_state(
            isolated_data,
            alert_paused=[("loyalty", None)],
        )
        ObsidianExporter(vault).export()
        content = (
            vault / "engines" / "loyalty.md"
        ).read_text(encoding="utf-8")
        assert "## Quarantine & alerts" in content
        assert "Alert-paused (fleet)" in content

    def test_engine_page_renders_per_store_pauses(
        self, vault, isolated_data,
    ):
        _write_quarantine_state(
            isolated_data,
            alert_paused=[
                ("loyalty", "store_a"),
                ("loyalty", "store_b"),
            ],
        )
        ObsidianExporter(vault).export()
        content = (
            vault / "engines" / "loyalty.md"
        ).read_text(encoding="utf-8")
        assert "Alert-paused (per-store)" in content
        assert "`store_a`" in content
        assert "`store_b`" in content

    def test_engine_page_renders_exempt_and_released(
        self, vault, isolated_data,
    ):
        _write_quarantine_state(
            isolated_data,
            exemptions=["loyalty"],
            released=["cart_recovery"],
        )
        ObsidianExporter(vault).export()
        loyalty = (
            vault / "engines" / "loyalty.md"
        ).read_text(encoding="utf-8")
        cart = (
            vault / "engines" / "cart_recovery.md"
        ).read_text(encoding="utf-8")
        assert "Exempt" in loyalty
        assert "Released" in cart

    def test_engine_page_renders_alert_streak(
        self, vault, isolated_data,
    ):
        # Seed three alert events on distinct day-buckets so the
        # streak counter reports 3. Bypass the pytest test-env
        # guard so record_alerts actually writes.
        from core.approval.alert_history import (
            AlertEvent,
            _save_events,
        )

        now = time.time()
        events = [
            AlertEvent(
                engine="loyalty",
                recorded_at=now - day * 86400.0,
                drop=0.40,
                recent_score=1.0 + day * 0.1,
                baseline_score=3.0,
                store_id=None,
            )
            for day in range(3)
        ]
        _save_events(events)

        ObsidianExporter(vault).export()
        content = (
            vault / "engines" / "loyalty.md"
        ).read_text(encoding="utf-8")
        assert "Alert streak" in content
        assert "3 day(s)" in content
        assert "Recent alerts:" in content

    def test_healthy_engine_omits_section(
        self, vault, isolated_data,
    ):
        ObsidianExporter(vault).export()
        # No quarantine state, no alerts -> no section for
        # an unrelated engine
        content = (
            vault / "engines" / "cart_recovery.md"
        ).read_text(encoding="utf-8")
        assert "## Quarantine & alerts" not in content

    def test_section_ordering(
        self, vault, isolated_data,
    ):
        """Quarantine block sits BETWEEN Performance and Recent
        activity. Operators expect health signals before activity
        details."""
        _write_quarantine_state(
            isolated_data,
            alert_paused=[("loyalty", None)],
        )
        ObsidianExporter(vault).export()
        content = (
            vault / "engines" / "loyalty.md"
        ).read_text(encoding="utf-8")
        quarantine = content.find("## Quarantine & alerts")
        operator = content.find("## Operator notes")
        assert -1 < quarantine < operator


# --- Source-failure isolation ---------------------------------


class TestSourceFailureIsolation:

    def test_quarantine_read_raises_keeps_page_renderable(
        self, vault, isolated_data,
    ):
        with patch(
            "core.approval.quarantine.load_state",
            side_effect=RuntimeError("disk gone"),
        ):
            ObsidianExporter(vault).export()
        content = (
            vault / "engines" / "loyalty.md"
        ).read_text(encoding="utf-8")
        # Page still exists; no quarantine block since collection
        # returned empty.
        assert "# loyalty" in content
        assert "## Quarantine & alerts" not in content

    def test_alert_history_raises_keeps_page_renderable(
        self, vault, isolated_data,
    ):
        # Quarantine state exists; alert collection fails.
        _write_quarantine_state(
            isolated_data,
            alert_paused=[("loyalty", None)],
        )
        with patch(
            "core.approval.alert_history.recent_history",
            side_effect=RuntimeError("history corrupted"),
        ):
            ObsidianExporter(vault).export()
        content = (
            vault / "engines" / "loyalty.md"
        ).read_text(encoding="utf-8")
        # Quarantine line still renders even when alert history
        # is unreachable.
        assert "## Quarantine & alerts" in content
        assert "Alert-paused (fleet)" in content
        # No "Recent alerts" or streak line, since alerts dict
        # is empty.
        assert "Recent alerts:" not in content
        assert "Alert streak" not in content
