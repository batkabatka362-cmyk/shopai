"""Tests for the engines-calibration aggregator + CLI surface.

Composes PR #161 (auto-approve allowlist) with PR #166
(per-engine calibration) to surface the highest-priority alert:
engines that are auto-approved AND have inverted calibration.

The companion to ``shopai engine-calibration <name>`` —
triage view across all engines.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from pathlib import Path
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


@pytest.fixture
def isolated_state(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue
    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield {"queue": fresh, "data_dir": tmp_path}
    fresh._conn.close()


def _seed(q, *, engine, confidence, positive, negative=0):
    for i in range(positive):
        a = q.enqueue(
            engine=engine, action_type="y", capability="z",
            params={}, narrative="", confidence=confidence,
        )
        q.approve(a.id, decided_by="op")
        q.attach_result(a.id, success=True, result={})
        q.record_outcome(
            a.id, topic="o", polarity="positive", metrics={},
            source_event=f"p_{engine}_{confidence}_{i}",
        )
    for i in range(negative):
        a = q.enqueue(
            engine=engine, action_type="y", capability="z",
            params={}, narrative="", confidence=confidence,
        )
        q.approve(a.id, decided_by="op")
        q.attach_result(a.id, success=True, result={})
        q.record_outcome(
            a.id, topic="o", polarity="negative", metrics={},
            source_event=f"n_{engine}_{confidence}_{i}",
        )


def _seed_well_calibrated(q, engine):
    _seed(q, engine=engine, confidence=0.55, positive=3, negative=7)
    _seed(q, engine=engine, confidence=0.75, positive=7, negative=3)
    _seed(q, engine=engine, confidence=0.95, positive=9, negative=1)


def _seed_inverted(q, engine):
    _seed(q, engine=engine, confidence=0.55, positive=5, negative=5)
    _seed(q, engine=engine, confidence=0.75, positive=9, negative=1)
    _seed(q, engine=engine, confidence=0.95, positive=4, negative=6)


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
    defaults = dict(miscalibrated_only=False, json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── Queue aggregator ──────────────────────────────────────────


class TestAllEnginesCalibration:

    def test_empty_state_returns_empty(self, isolated_state):
        q = isolated_state["queue"]
        assert q.all_engines_calibration() == {}

    def test_returns_one_entry_per_engine(self, isolated_state):
        q = isolated_state["queue"]
        _seed_well_calibrated(q, "good")
        _seed_inverted(q, "bad")
        results = q.all_engines_calibration()
        assert set(results.keys()) == {"good", "bad"}
        assert results["good"]["monotonic_increasing"] is True
        assert results["bad"]["monotonic_increasing"] is False

    def test_excludes_engines_without_confidence(
        self, isolated_state,
    ):
        """An engine with actions but no confidence-tagged ones
        shouldn't appear in the sweep — nothing to assess."""
        q = isolated_state["queue"]
        # confidence-tagged
        _seed_well_calibrated(q, "tagged")
        # no confidence
        a = q.enqueue(
            engine="untagged", action_type="y", capability="z",
            params={}, narrative="",
        )
        q.approve(a.id, decided_by="op")
        q.attach_result(a.id, success=True, result={})
        q.record_outcome(
            a.id, topic="o", polarity="positive", metrics={},
            source_event="untagged_p",
        )
        results = q.all_engines_calibration()
        assert "tagged" in results
        assert "untagged" not in results

    def test_results_sorted_alphabetically(self, isolated_state):
        """Dict iteration order should be deterministic
        alphabetical so downstream UIs don't shuffle."""
        q = isolated_state["queue"]
        _seed_well_calibrated(q, "zebra")
        _seed_well_calibrated(q, "apple")
        _seed_well_calibrated(q, "mango")
        results = q.all_engines_calibration()
        assert list(results.keys()) == ["apple", "mango", "zebra"]


# ─── CLI ───────────────────────────────────────────────────────


class TestCli:

    def test_empty_state_friendly_message(self, cli, isolated_state):
        out, code = _capture(
            cli._cmd_engines_calibration, _ns(),
        )
        assert code == 0
        assert "No engines with confidence-tagged actions" in out

    def test_lists_all_engines(self, cli, isolated_state):
        q = isolated_state["queue"]
        _seed_well_calibrated(q, "good")
        _seed_inverted(q, "bad")
        out, _ = _capture(
            cli._cmd_engines_calibration, _ns(),
        )
        assert "good" in out
        assert "bad" in out
        assert "well-calibrated" in out
        assert "INVERTED" in out

    def test_inverted_engines_sort_first(self, cli, isolated_state):
        """Triage UX: inverted engines render before
        well-calibrated ones so operators see what needs
        attention at the top."""
        q = isolated_state["queue"]
        _seed_well_calibrated(q, "zebra_good")
        _seed_inverted(q, "apple_bad")
        out, _ = _capture(
            cli._cmd_engines_calibration, _ns(),
        )
        bad_pos = out.find("apple_bad")
        good_pos = out.find("zebra_good")
        # Sort priority overrides alphabetical
        assert 0 <= bad_pos < good_pos

    def test_miscalibrated_only_filter(self, cli, isolated_state):
        q = isolated_state["queue"]
        _seed_well_calibrated(q, "good")
        _seed_inverted(q, "bad")
        out, _ = _capture(
            cli._cmd_engines_calibration,
            _ns(miscalibrated_only=True),
        )
        assert "bad" in out
        # well-calibrated engines filtered out
        assert "good" not in out

    def test_miscalibrated_only_empty_message(
        self, cli, isolated_state,
    ):
        q = isolated_state["queue"]
        _seed_well_calibrated(q, "good")
        out, _ = _capture(
            cli._cmd_engines_calibration,
            _ns(miscalibrated_only=True),
        )
        assert "No miscalibrated engines" in out

    def test_allowlisted_inverted_engine_alerts(
        self, cli, isolated_state,
    ):
        """The highest-priority alert: an engine on the
        auto-approve allowlist with inverted calibration."""
        from core.approval.auto_approve import enable_engine
        q = isolated_state["queue"]
        _seed_inverted(q, "bad")
        enable_engine("bad")
        out, _ = _capture(
            cli._cmd_engines_calibration, _ns(),
        )
        # Alert banner present
        assert "ALERT" in out
        assert "auto-approved AND" in out
        # Help points to the disable command
        assert "auto-config --disable" in out

    def test_no_alert_when_no_allowlisted_inverted(
        self, cli, isolated_state,
    ):
        """A miscalibrated engine that's NOT on the allowlist
        is a warning, not the highest-priority alert."""
        q = isolated_state["queue"]
        _seed_inverted(q, "bad")  # not allowlisted
        out, _ = _capture(
            cli._cmd_engines_calibration, _ns(),
        )
        # Engine surfaces, but no ALERT banner
        assert "bad" in out
        assert "ALERT" not in out

    def test_allowlisted_inverted_sorts_first(
        self, cli, isolated_state,
    ):
        """The alert engine should be the very first row."""
        from core.approval.auto_approve import enable_engine
        q = isolated_state["queue"]
        _seed_inverted(q, "a_not_allow")  # inverted, not allowlisted
        _seed_inverted(q, "z_allow")  # inverted AND allowlisted
        _seed_well_calibrated(q, "good")
        enable_engine("z_allow")
        out, _ = _capture(
            cli._cmd_engines_calibration, _ns(),
        )
        z_pos = out.find("z_allow")
        a_pos = out.find("a_not_allow")
        good_pos = out.find("good")
        # z_allow renders before a_not_allow (priority override)
        # and both before good
        assert 0 <= z_pos < a_pos < good_pos

    def test_alert_row_has_bang_prefix(self, cli, isolated_state):
        """Grep-friendly: each alert row starts with '!'."""
        from core.approval.auto_approve import enable_engine
        q = isolated_state["queue"]
        _seed_inverted(q, "bad")
        enable_engine("bad")
        out, _ = _capture(
            cli._cmd_engines_calibration, _ns(),
        )
        # Find the line containing "bad" and check its prefix
        for line in out.splitlines():
            if "bad" in line and "INVERTED" in line:
                assert line.startswith("!")
                break
        else:
            raise AssertionError("alert row for 'bad' not found")

    def test_json_mode(self, cli, isolated_state):
        q = isolated_state["queue"]
        _seed_well_calibrated(q, "good")
        _seed_inverted(q, "bad")
        out, _ = _capture(
            cli._cmd_engines_calibration, _ns(json=True),
        )
        data = json.loads(out)
        assert isinstance(data, list)
        # Each row has full shape
        for row in data:
            assert set(row.keys()) >= {
                "engine", "verdict", "monotonic_increasing",
                "allowlisted", "action_count",
                "miscalibrated_and_allowlisted",
            }

    def test_json_first_char_is_bracket(self, cli, isolated_state):
        """jq-friendly empty array."""
        out, _ = _capture(
            cli._cmd_engines_calibration, _ns(json=True),
        )
        assert out.strip()[0] == "["

    def test_queue_failure_renders_friendly(self, cli, isolated_state):
        with patch.object(
            isolated_state["queue"],
            "all_engines_calibration",
            side_effect=RuntimeError("db lock"),
        ):
            out, code = _capture(
                cli._cmd_engines_calibration, _ns(),
            )
        assert code == 0
        assert "No engines" in out


# ─── Integration: composes auto-approve + calibration ──────────


class TestComposition:

    def test_allowlist_probe_failure_doesnt_break_render(
        self, cli, isolated_state,
    ):
        """If the auto-approve allowlist probe fails, treat it
        as empty (no engines highlighted) rather than crashing
        the whole sweep."""
        q = isolated_state["queue"]
        _seed_inverted(q, "bad")
        with patch(
            "core.approval.auto_approve.load_config",
            side_effect=RuntimeError("config broken"),
        ):
            out, code = _capture(
                cli._cmd_engines_calibration, _ns(),
            )
        assert code == 0
        # Engine still surfaced; just no alert banner
        assert "bad" in out
        assert "ALERT" not in out
