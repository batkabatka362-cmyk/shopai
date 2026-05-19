"""Tests for the Score trajectory block on engine pages.

PR #347 introduced ``engine_health_history`` -- the persistent
score event log. PR #352 wires daily-brief to populate it. This
test file covers the Obsidian engine-page renderer that surfaces
the recorded trajectory alongside Performance / Quarantine /
Recent activity / Operator notes.

Coverage:
  1. Empty trajectory -> section omitted.
  2. Renderer produces newest-first bullets with date/score/verdict.
  3. Capped at 10 events per engine.
  4. Exporter end-to-end: section appears when history is seeded.
  5. Source-failure isolation: a raising history read keeps the
     page renderable without the trajectory section.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core.knowledge import ObsidianExporter
from core.knowledge.exporter import _render_score_trajectory_block


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    return tmp_path / "vault"


@pytest.fixture
def isolated_data(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    return tmp_path


def _seed_history(data_dir: Path, events: list[dict]) -> None:
    """Write the engine_health_history payload directly."""
    (
        data_dir / "engine_health_history.json"
    ).write_text(json.dumps(events), encoding="utf-8")


def _event(*, score: int, verdict: str, recorded_at: float):
    from core.approval.engine_health_history import ScoreEvent
    return ScoreEvent(
        engine="loyalty",
        recorded_at=recorded_at,
        score=score,
        verdict=verdict,
    )


# --- Renderer-level coverage ----------------------------------


class TestRenderScoreTrajectoryBlock:

    def test_empty_returns_empty_list(self):
        assert _render_score_trajectory_block(None) == []
        assert _render_score_trajectory_block([]) == []

    def test_renders_single_event(self):
        ev = _event(
            score=7, verdict="healthy", recorded_at=2_000_000.0,
        )
        lines = _render_score_trajectory_block([ev])
        assert len(lines) == 1
        assert "7/10" in lines[0]
        assert "healthy" in lines[0]

    def test_renders_multiple_newest_first_caller_order(self):
        # The renderer preserves the order it gets; the
        # caller is responsible for newest-first.
        events = [
            _event(
                score=7, verdict="healthy",
                recorded_at=2_000_000.0,
            ),
            _event(
                score=5, verdict="warning",
                recorded_at=1_500_000.0,
            ),
            _event(
                score=3, verdict="unhealthy",
                recorded_at=1_000_000.0,
            ),
        ]
        lines = _render_score_trajectory_block(events)
        assert len(lines) == 3
        # First line shows the newest event (highest recorded_at)
        assert "7/10" in lines[0]
        assert "5/10" in lines[1]
        assert "3/10" in lines[2]

    def test_score_padding(self):
        """Single-digit scores get padded so the bullet column
        lines up in a scannable view."""
        ev = _event(
            score=4, verdict="unhealthy",
            recorded_at=2_000_000.0,
        )
        lines = _render_score_trajectory_block([ev])
        assert " 4/10" in lines[0]


# --- Exporter end-to-end --------------------------------------


class TestExporterIntegration:

    def test_engine_page_renders_trajectory(
        self, vault, isolated_data,
    ):
        now = time.time()
        _seed_history(isolated_data, [
            {
                "engine": "loyalty",
                "recorded_at": now - 86400.0 * i,
                "score": 9 - i,
                "verdict": (
                    "healthy" if 9 - i >= 8
                    else "warning" if 9 - i >= 5
                    else "unhealthy"
                ),
            }
            for i in range(5)
        ])
        ObsidianExporter(vault).export()
        content = (
            vault / "engines" / "loyalty.md"
        ).read_text(encoding="utf-8")
        assert "## Score trajectory" in content
        # 5 score values render
        for s in (9, 8, 7, 6, 5):
            assert f"{s}/10" in content

    def test_capped_at_ten_per_engine(
        self, vault, isolated_data,
    ):
        now = time.time()
        _seed_history(isolated_data, [
            {
                "engine": "loyalty",
                "recorded_at": now - i * 60.0,
                "score": (i % 10) + 1,
                "verdict": "warning",
            }
            for i in range(15)
        ])
        ObsidianExporter(vault).export()
        content = (
            vault / "engines" / "loyalty.md"
        ).read_text(encoding="utf-8")
        traj_section = content.split("## Score trajectory")[1]
        bullets = [
            ln for ln in traj_section.splitlines()
            if ln.startswith("- ")
        ]
        assert len(bullets) == 10

    def test_section_omitted_when_no_events(
        self, vault, isolated_data,
    ):
        ObsidianExporter(vault).export()
        content = (
            vault / "engines" / "loyalty.md"
        ).read_text(encoding="utf-8")
        assert "## Score trajectory" not in content

    def test_section_ordering(
        self, vault, isolated_data,
    ):
        """Score trajectory sits between Quarantine & alerts
        and Recent activity (or Operator notes when neither
        Quarantine nor Recent activity is present)."""
        now = time.time()
        _seed_history(isolated_data, [
            {
                "engine": "loyalty",
                "recorded_at": now - 3600.0,
                "score": 5,
                "verdict": "warning",
            },
        ])
        ObsidianExporter(vault).export()
        content = (
            vault / "engines" / "loyalty.md"
        ).read_text(encoding="utf-8")
        traj_pos = content.find("## Score trajectory")
        operator_pos = content.find("## Operator notes")
        assert -1 < traj_pos < operator_pos


# --- Source-failure isolation ---------------------------------


class TestSourceFailureIsolation:

    def test_history_raise_keeps_page_renderable(
        self, vault, isolated_data,
    ):
        with patch(
            "core.approval.engine_health_history."
            "recent_history",
            side_effect=RuntimeError("history corrupted"),
        ):
            ObsidianExporter(vault).export()
        content = (
            vault / "engines" / "loyalty.md"
        ).read_text(encoding="utf-8")
        # Page renders without the trajectory section
        assert "# loyalty" in content
        assert "## Score trajectory" not in content
