"""Tests for engines.earn_config — W963-87."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from engines.earn_config import EarnConfigEngine
from engines.earn_config import configurator as cfg


@pytest.fixture
def _tmp_env(tmp_path, monkeypatch):
    """Redirect _ENV_FILE to a tmp_path .env so tests don't
    touch the real working directory."""
    p = tmp_path / ".env"
    monkeypatch.setattr(cfg, "_ENV_FILE", p)
    yield p


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Strip the earn_config keys from os.environ so test
    state matches the inspect output."""
    for key in (
        "SHOPAI_SPEND_CAP_DAILY_USD",
        "SHOPAI_AUTO_PAUSE_ON_OVERSPEND",
        "SHOPAI_AUTO_QUARANTINE_FROM_REVENUE",
        "SHOPAI_AUTO_DISARM_ON_OVERRIDE",
        "SHOPAI_CYCLE_RECORD_BRIEF",
        "SHOPAI_AI_STRATEGY",
        "SHOPAI_NOTIFY_AUTONOMY_COALESCE",
        "SHOPAI_NOTIFY_WEBHOOK_URL",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


# ── _load_env_file ────────────────────────────────────────


class TestLoadEnvFile:
    def test_missing_file_empty(self, _tmp_env):
        assert cfg._load_env_file() == {}

    def test_parses_kv_lines(self, _tmp_env):
        _tmp_env.write_text(
            "FOO=bar\nBAZ=qux\n",
            encoding="utf-8",
        )
        out = cfg._load_env_file()
        assert out == {"FOO": "bar", "BAZ": "qux"}

    def test_skips_comments_and_blanks(self, _tmp_env):
        _tmp_env.write_text(
            "# comment\n\nFOO=bar\n  \nBAZ=qux\n",
            encoding="utf-8",
        )
        out = cfg._load_env_file()
        assert out == {"FOO": "bar", "BAZ": "qux"}

    def test_skips_lines_without_equals(self, _tmp_env):
        _tmp_env.write_text(
            "FOO=bar\nGARBAGE\nBAZ=qux\n",
            encoding="utf-8",
        )
        out = cfg._load_env_file()
        assert out == {"FOO": "bar", "BAZ": "qux"}

    def test_first_equals_splits(self, _tmp_env):
        _tmp_env.write_text(
            "FOO=bar=baz\n", encoding="utf-8",
        )
        out = cfg._load_env_file()
        assert out["FOO"] == "bar=baz"


# ── build_state ───────────────────────────────────────────


class TestBuildState:
    def test_all_unset_initially(self, _tmp_env):
        r = cfg.build_state()
        assert r.n_total == 9
        assert r.n_already_set == 0
        assert r.n_applicable == 7  # 7 safe defaults
        assert r.n_operator_specific_missing == 2

    def test_env_set_counts_as_set(
        self, _tmp_env, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_SPEND_CAP_DAILY_USD", "100",
        )
        r = cfg.build_state()
        assert r.n_already_set == 1

    def test_file_set_counts_as_set(self, _tmp_env):
        _tmp_env.write_text(
            "SHOPAI_AI_STRATEGY=1\n", encoding="utf-8",
        )
        r = cfg.build_state()
        assert r.n_already_set == 1

    def test_placeholder_treated_as_unset(
        self, _tmp_env, monkeypatch,
    ):
        # Placeholder values like "sk-..." should NOT
        # count as set
        monkeypatch.setenv("OPENAI_API_KEY", "sk-...")
        r = cfg.build_state()
        assert r.n_already_set == 0

    def test_real_value_counts_as_set(
        self, _tmp_env, monkeypatch,
    ):
        monkeypatch.setenv(
            "OPENAI_API_KEY", "sk-abc123def456",
        )
        r = cfg.build_state()
        assert r.n_already_set == 1

    def test_key_state_carries_rationale(self, _tmp_env):
        r = cfg.build_state()
        for k in r.keys:
            assert k.rationale
            assert k.name
            assert k.fix_command


# ── apply_defaults ────────────────────────────────────────


class TestApplyDefaults:
    def test_writes_safe_defaults(
        self, _tmp_env, monkeypatch,
    ):
        # Bypass the Pattern J guard for this test
        monkeypatch.setattr(
            cfg, "_is_test_environment",
            lambda: False,
        )
        r = cfg.apply_defaults()
        assert r.applied_count == 7
        # Verify file contents
        body = _tmp_env.read_text(encoding="utf-8")
        assert "SHOPAI_SPEND_CAP_DAILY_USD=50" in body
        assert "SHOPAI_AUTO_DISARM_ON_OVERRIDE=1" in body
        # Operator-specific NOT written
        assert "OPENAI_API_KEY" not in body
        assert "SHOPAI_NOTIFY_WEBHOOK_URL" not in body

    def test_pattern_j_guard_blocks_write(self, _tmp_env):
        # Default: _is_test_environment returns True under
        # pytest so the apply path no-ops.
        r = cfg.apply_defaults()
        assert r.applied_count == 0
        assert not _tmp_env.exists()

    def test_skips_already_set(
        self, _tmp_env, monkeypatch,
    ):
        monkeypatch.setattr(
            cfg, "_is_test_environment",
            lambda: False,
        )
        _tmp_env.write_text(
            "SHOPAI_SPEND_CAP_DAILY_USD=100\n",
            encoding="utf-8",
        )
        r = cfg.apply_defaults()
        assert r.applied_count == 6  # 7 - 1 already set
        body = _tmp_env.read_text(encoding="utf-8")
        # Pre-existing value preserved
        assert "SHOPAI_SPEND_CAP_DAILY_USD=100" in body
        # New defaults added
        assert "SHOPAI_AI_STRATEGY=1" in body

    def test_idempotent(
        self, _tmp_env, monkeypatch,
    ):
        monkeypatch.setattr(
            cfg, "_is_test_environment",
            lambda: False,
        )
        cfg.apply_defaults()
        # Second call -- everything already set
        r = cfg.apply_defaults()
        assert r.applied_count == 0


# ── print_exports ─────────────────────────────────────────


class TestPrintExports:
    def test_all_unset(self, _tmp_env):
        exports = cfg.print_exports()
        # 7 safe defaults
        assert len(exports) == 7
        for line in exports:
            assert line.startswith("export ")

    def test_excludes_operator_specific(self, _tmp_env):
        exports = cfg.print_exports()
        joined = "\n".join(exports)
        assert "OPENAI_API_KEY" not in joined
        assert "SHOPAI_NOTIFY_WEBHOOK_URL" not in joined

    def test_excludes_already_set(
        self, _tmp_env, monkeypatch,
    ):
        monkeypatch.setenv("SHOPAI_AI_STRATEGY", "1")
        exports = cfg.print_exports()
        joined = "\n".join(exports)
        assert "SHOPAI_AI_STRATEGY" not in joined


# ── Pattern Q envelope ────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = EarnConfigEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = EarnConfigEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = EarnConfigEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = EarnConfigEngine().run({
            "status": "fail", "error": "x",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = EarnConfigEngine().run({})
        assert r["meta"]["engine"] == "earn_config"

    def test_inspect_default_action(self, _tmp_env):
        r = EarnConfigEngine().run({})
        assert "keys" in r["data"]
        assert r["data"]["n_total"] == 9

    def test_print_action_includes_exports(
        self, _tmp_env,
    ):
        r = EarnConfigEngine().run({
            "data": {"action": "print"},
        })
        assert "exports" in r["data"]
