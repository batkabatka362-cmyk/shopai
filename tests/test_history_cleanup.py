"""Tests for ``core.autonomous.history_cleanup``."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core.autonomous import history_cleanup as hc


@pytest.fixture
def isolated_history(tmp_path, monkeypatch):
    """Redirect every history env var to tmp_path so the
    cleanup walks a fake set of files."""
    for label, env, _default, _shape in hc._HISTORY_FILES:
        monkeypatch.setenv(
            env, str(tmp_path / f"{label}.json"),
        )
    yield tmp_path


def _write_events(path: Path, ages_days: list[int]):
    """Write a list of events with the given ages (from
    now)."""
    now = time.time()
    rows = []
    for i, age in enumerate(ages_days):
        rows.append({
            "kind": "demote",
            "capability": f"cap_{i}",
            "reason": "r",
            "recorded_at": now - age * 86400,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows))


class TestDryRun:

    def test_no_files_empty_result(
        self, isolated_history,
    ):
        result = hc.prune_all(
            older_than_days=180, dry_run=True,
        )
        assert result["dry_run"] is True
        assert result["total_pruned"] == 0
        # Every known file represented
        labels = {f["label"] for f in result["files"]}
        for known in (
            "cycle_history",
            "cycle_alert_history",
            "cycle_pause_history",
            "auto_demote_history",
            "auto_promote_history",
            "auto_relax_history",
            "transfer_history",
            "plan_history",
        ):
            assert known in labels

    def test_dry_run_doesnt_modify(
        self, isolated_history,
    ):
        path = (
            isolated_history / "auto_demote_history.json"
        )
        _write_events(path, [100, 300])
        result = hc.prune_all(
            older_than_days=180, dry_run=True,
        )
        # Identifies 1 to prune (300 > 180)
        entry = next(
            e for e in result["files"]
            if e["label"] == "auto_demote_history"
        )
        assert entry["pruned"] == 1
        assert entry["kept"] == 1
        # File untouched
        raw = json.loads(path.read_text())
        assert len(raw) == 2


class TestApply:

    def test_actually_prunes(
        self, isolated_history,
    ):
        path = (
            isolated_history / "auto_demote_history.json"
        )
        _write_events(path, [100, 300, 400])
        with patch(
            "core.autonomous.history_cleanup."
            "_is_test_environment",
            return_value=False,
        ):
            result = hc.prune_all(
                older_than_days=180, dry_run=False,
            )
        entry = next(
            e for e in result["files"]
            if e["label"] == "auto_demote_history"
        )
        assert entry["pruned"] == 2
        # File rewrote with just the kept row
        raw = json.loads(path.read_text())
        assert len(raw) == 1
        assert raw[0]["capability"] == "cap_0"

    def test_pattern_j_blocks_writes_in_test(
        self, isolated_history,
    ):
        """Without lifting the test_env guard, apply
        doesn't actually write."""
        path = (
            isolated_history / "auto_demote_history.json"
        )
        _write_events(path, [400])
        # dry_run=False but Pattern J active
        result = hc.prune_all(
            older_than_days=180, dry_run=False,
        )
        # Report says 1 to prune
        entry = next(
            e for e in result["files"]
            if e["label"] == "auto_demote_history"
        )
        assert entry["pruned"] == 1
        # File NOT touched
        raw = json.loads(path.read_text())
        assert len(raw) == 1


class TestEdgeCases:

    def test_corrupt_file_marks_error(
        self, isolated_history,
    ):
        path = (
            isolated_history / "auto_demote_history.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json{")
        result = hc.prune_all(
            older_than_days=180, dry_run=True,
        )
        entry = next(
            e for e in result["files"]
            if e["label"] == "auto_demote_history"
        )
        assert entry["error"] is not None
        assert "json_decode" in entry["error"]

    def test_wrong_shape_marks_error(
        self, isolated_history,
    ):
        path = (
            isolated_history / "auto_demote_history.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"not": "list"}))
        result = hc.prune_all(
            older_than_days=180, dry_run=True,
        )
        entry = next(
            e for e in result["files"]
            if e["label"] == "auto_demote_history"
        )
        assert entry["error"] is not None

    def test_zero_days_prunes_everything(
        self, isolated_history,
    ):
        path = (
            isolated_history / "auto_demote_history.json"
        )
        _write_events(path, [0, 1, 2])
        result = hc.prune_all(
            older_than_days=0, dry_run=True,
        )
        entry = next(
            e for e in result["files"]
            if e["label"] == "auto_demote_history"
        )
        # All events have recorded_at < cutoff (now - 0)
        # technically; in practice tiny clock drift means
        # 0-age events MAY survive. We accept either 2 or 3.
        assert entry["pruned"] >= 2
