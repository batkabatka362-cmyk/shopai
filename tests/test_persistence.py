"""Tests for core.agi.persistence — W963-92."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from core.agi.persistence import (
    atomic_write_json,
    is_test_environment,
    load_json_dict,
    load_json_list,
)


# ── is_test_environment ───────────────────────────────────


class TestIsTestEnvironment:
    def test_pytest_var_triggers(self, monkeypatch):
        monkeypatch.setenv(
            "PYTEST_CURRENT_TEST", "fake",
        )
        monkeypatch.delenv(
            "SHOPAI_FORCE_PRODUCTION_WRITES",
            raising=False,
        )
        assert is_test_environment() is True

    @pytest.mark.parametrize("override", [
        "1", "true", "yes", "TRUE", "Yes",
    ])
    def test_force_override_unsets(
        self, monkeypatch, override,
    ):
        monkeypatch.setenv(
            "PYTEST_CURRENT_TEST", "fake",
        )
        monkeypatch.setenv(
            "SHOPAI_FORCE_PRODUCTION_WRITES", override,
        )
        assert is_test_environment() is False

    @pytest.mark.parametrize("override", [
        "0", "false", "no", "",
    ])
    def test_falsy_override_keeps_test_mode(
        self, monkeypatch, override,
    ):
        monkeypatch.setenv(
            "PYTEST_CURRENT_TEST", "fake",
        )
        monkeypatch.setenv(
            "SHOPAI_FORCE_PRODUCTION_WRITES", override,
        )
        assert is_test_environment() is True


# ── atomic_write_json ─────────────────────────────────────


class TestAtomicWriteJson:
    def test_writes_list(self, tmp_path):
        p = tmp_path / "out.json"
        ok = atomic_write_json(p, [{"a": 1}])
        assert ok is True
        loaded = json.loads(
            p.read_text(encoding="utf-8"),
        )
        assert loaded == [{"a": 1}]

    def test_writes_dict(self, tmp_path):
        p = tmp_path / "out.json"
        ok = atomic_write_json(p, {"k": "v"})
        assert ok is True
        assert (
            json.loads(p.read_text(encoding="utf-8"))
            == {"k": "v"}
        )

    def test_creates_parent_directory(self, tmp_path):
        p = tmp_path / "nested" / "out.json"
        ok = atomic_write_json(p, [])
        assert ok is True
        assert p.exists()

    def test_overwrites_existing(self, tmp_path):
        p = tmp_path / "out.json"
        p.write_text('["original"]', encoding="utf-8")
        ok = atomic_write_json(p, ["new"])
        assert ok is True
        assert p.read_text(encoding="utf-8").strip().startswith(
            "[",
        )

    def test_accepts_string_path(self, tmp_path):
        p = str(tmp_path / "out.json")
        ok = atomic_write_json(p, ["x"])
        assert ok is True

    def test_no_temp_files_left_behind(self, tmp_path):
        p = tmp_path / "out.json"
        atomic_write_json(p, ["x"])
        leftover = [
            f for f in tmp_path.iterdir()
            if f.name.startswith(".")
            and f.name.endswith(".tmp")
        ]
        assert leftover == []

    def test_returns_false_on_oserror(self, tmp_path):
        """Force an OSError by passing an invalid path."""
        # On Windows, a NUL character in the path raises
        # OSError consistently.
        p = tmp_path / "in\x00valid.json"
        ok = atomic_write_json(p, ["x"])
        assert ok is False

    def test_indent_param_threads_through(self, tmp_path):
        p = tmp_path / "out.json"
        atomic_write_json(p, {"a": 1}, indent=None)
        body = p.read_text(encoding="utf-8")
        # Compact form (no newlines after braces)
        assert "\n" not in body.strip()


# ── load_json_list ────────────────────────────────────────


class TestLoadJsonList:
    def test_missing_returns_empty(self, tmp_path):
        p = tmp_path / "no.json"
        assert load_json_list(p) == []

    def test_valid_list(self, tmp_path):
        p = tmp_path / "x.json"
        p.write_text(
            '[{"a": 1}, {"b": 2}]', encoding="utf-8",
        )
        assert load_json_list(p) == [
            {"a": 1}, {"b": 2},
        ]

    def test_filters_non_dict_entries(self, tmp_path):
        p = tmp_path / "x.json"
        p.write_text(
            '[{"a": 1}, "string", 42, {"b": 2}]',
            encoding="utf-8",
        )
        assert load_json_list(p) == [
            {"a": 1}, {"b": 2},
        ]

    def test_top_level_dict_returns_empty(self, tmp_path):
        p = tmp_path / "x.json"
        p.write_text(
            '{"not": "a list"}', encoding="utf-8",
        )
        assert load_json_list(p) == []

    def test_malformed_json_returns_empty(self, tmp_path):
        p = tmp_path / "x.json"
        p.write_text(
            "{not valid json", encoding="utf-8",
        )
        assert load_json_list(p) == []

    def test_accepts_string_path(self, tmp_path):
        p = tmp_path / "x.json"
        p.write_text("[]", encoding="utf-8")
        assert load_json_list(str(p)) == []


# ── load_json_dict ────────────────────────────────────────


class TestLoadJsonDict:
    def test_missing_returns_empty(self, tmp_path):
        p = tmp_path / "no.json"
        assert load_json_dict(p) == {}

    def test_valid_dict(self, tmp_path):
        p = tmp_path / "x.json"
        p.write_text(
            '{"a": 1, "b": "two"}', encoding="utf-8",
        )
        assert load_json_dict(p) == {
            "a": 1, "b": "two",
        }

    def test_top_level_list_returns_empty(self, tmp_path):
        p = tmp_path / "x.json"
        p.write_text(
            '["not", "a dict"]', encoding="utf-8",
        )
        assert load_json_dict(p) == {}

    def test_malformed_json_returns_empty(self, tmp_path):
        p = tmp_path / "x.json"
        p.write_text("garbage", encoding="utf-8")
        assert load_json_dict(p) == {}


# ── Migration sanity checks ────────────────────────────────


class TestMigrationSanity:
    """Verify the migrated engines still expose
    _is_test_environment + the new symbol IS the
    canonical."""

    def test_agi_earnings_history_uses_canonical(self):
        from engines.agi_earnings_history.store import (
            _is_test_environment,
        )
        from core.agi.persistence import (
            is_test_environment,
        )
        assert _is_test_environment is is_test_environment

    def test_auto_disarm_log_uses_canonical(self):
        from engines.agi_arm_recommender.auto_disarm_log \
            import _is_test_environment
        from core.agi.persistence import (
            is_test_environment,
        )
        assert _is_test_environment is is_test_environment

    def test_strategist_memory_uses_canonical(self):
        from engines.strategist_memory.store import (
            _is_test_environment,
        )
        from core.agi.persistence import (
            is_test_environment,
        )
        assert _is_test_environment is is_test_environment

    def test_daily_pnl_history_uses_canonical(self):
        from engines.daily_pnl_history.store import (
            _is_test_environment,
        )
        from core.agi.persistence import (
            is_test_environment,
        )
        assert _is_test_environment is is_test_environment

    def test_fleet_notifier_uses_canonical(self):
        from engines.fleet_notifier.state import (
            _is_test_environment,
        )
        from core.agi.persistence import (
            is_test_environment,
        )
        assert _is_test_environment is is_test_environment

    def test_morning_brief_uses_canonical(self):
        from engines.agi_morning_brief.briefer import (
            _is_test_environment,
        )
        from core.agi.persistence import (
            is_test_environment,
        )
        assert _is_test_environment is is_test_environment

    def test_earn_config_uses_canonical(self):
        from engines.earn_config.configurator import (
            _is_test_environment,
        )
        from core.agi.persistence import (
            is_test_environment,
        )
        assert _is_test_environment is is_test_environment
