"""Tests for ``shopai db info`` — inventory ShopAI's
persistent state files.

Operators have no overview of what state ShopAI persists.
``db status`` covers SQLite schema versions; ``db info`` covers
sizes/ages/row counts across every file under ``data/`` — useful
for "is anything growing or stale?" debug questions.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
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
def isolated_data(tmp_path: Path, monkeypatch):
    """Run db info against a temporary data dir so tests don't
    inspect the real ShopAI data."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    return data_dir


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    with patch("sys.stdout", buf):
        fn(*args, **kwargs)
    return buf.getvalue()


# ─── empty / missing data dir ────────────────────────────────────


class TestEdgeCases:

    def test_missing_data_dir_clean_message(self, cli, tmp_path, monkeypatch):
        """A directory without a ``data/`` subdir gets a friendly
        message, not a stack trace."""
        monkeypatch.chdir(tmp_path)
        out = _capture(cli._cmd_db_info)
        assert "No data directory" in out

    def test_empty_data_dir(self, cli, isolated_data):
        out = _capture(cli._cmd_db_info)
        assert "No state files" in out


# ─── sqlite row counts ────────────────────────────────────────────


class TestSqliteHandling:

    def test_db_row_count_aggregates_tables(self, cli, isolated_data):
        """A SQLite file with two tables sums their row counts."""
        db_path = isolated_data / "approval_queue.db"
        with sqlite3.connect(str(db_path)) as conn:
            conn.executescript("""
                CREATE TABLE t1 (id INTEGER PRIMARY KEY);
                CREATE TABLE t2 (id INTEGER PRIMARY KEY);
                INSERT INTO t1 VALUES (1), (2), (3);
                INSERT INTO t2 VALUES (1), (2);
            """)
            conn.commit()
        out = _capture(cli._cmd_db_info)
        # 3 + 2 = 5 rows total
        assert "approval_queue.db" in out
        assert "5 rows" in out

    def test_db_skips_sqlite_master(self, cli, isolated_data):
        """sqlite_master and other ``sqlite_*`` tables aren't
        counted (they'd inflate every row count by 1+)."""
        db_path = isolated_data / "empty.db"
        with sqlite3.connect(str(db_path)) as conn:
            # No user tables — just SQLite's internal ones
            conn.commit()
        out = _capture(cli._cmd_db_info)
        assert "0 rows" in out

    def test_corrupt_db_no_crash(self, cli, isolated_data):
        """A non-SQLite file with .db extension surfaces as '-'
        rather than crashing the inventory."""
        (isolated_data / "corrupt.db").write_bytes(
            b"not a sqlite file"
        )
        out = _capture(cli._cmd_db_info)
        assert "corrupt.db" in out


# ─── json entry counts ──────────────────────────────────────────


class TestJsonHandling:

    def test_json_dict_count(self, cli, isolated_data):
        (isolated_data / "config.json").write_text(
            json.dumps({"a": 1, "b": 2, "c": 3}),
            encoding="utf-8",
        )
        out = _capture(cli._cmd_db_info)
        assert "config.json" in out
        assert "3 entries" in out

    def test_json_list_count(self, cli, isolated_data):
        (isolated_data / "log.json").write_text(
            json.dumps([{"a": 1}, {"a": 2}]),
            encoding="utf-8",
        )
        out = _capture(cli._cmd_db_info)
        assert "log.json" in out
        assert "2 entries" in out

    def test_malformed_json_no_crash(self, cli, isolated_data):
        (isolated_data / "broken.json").write_text(
            "{not valid", encoding="utf-8",
        )
        out = _capture(cli._cmd_db_info)
        # Just listed without entries count
        assert "broken.json" in out


# ─── summary ──────────────────────────────────────────────────────


class TestSummary:

    def test_total_line_present(self, cli, isolated_data):
        (isolated_data / "x.json").write_text("{}", encoding="utf-8")
        out = _capture(cli._cmd_db_info)
        assert "Total:" in out
        # File count appears in total
        assert "1 files" in out

    def test_total_size_summed(self, cli, isolated_data):
        # Two small files
        (isolated_data / "a.json").write_text(
            "{}" * 50, encoding="utf-8",
        )
        (isolated_data / "b.json").write_text(
            "{}" * 100, encoding="utf-8",
        )
        out = _capture(cli._cmd_db_info)
        assert "Total: 2 files" in out
