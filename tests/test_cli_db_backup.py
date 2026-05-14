"""Tests for ``shopai db backup`` — snapshot data/ to a tarball.

Operator safety net: before a risky upgrade, schema migration,
or experimental auto-approve session, capture a one-shot
snapshot. Restore is ``tar -xzf`` — no special tooling needed.
"""
from __future__ import annotations

import importlib.util
import tarfile
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
    """Each test runs in a tmp directory with its own data/."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    return data_dir


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


# ─── happy paths ──────────────────────────────────────────────────


class TestBackup:

    def test_default_filename_written(self, cli, isolated_data):
        """Without --out, name is shopai-backup-<UTC timestamp>.tar.gz."""
        # Seed a sample data file
        (isolated_data / "approval_queue.db").write_text(
            "(test data)", encoding="utf-8",
        )

        out, code = _capture(cli._cmd_db_backup, None)
        assert code == 0
        # Find the produced file
        backups = list(Path(".").glob("shopai-backup-*.tar.gz"))
        assert len(backups) == 1
        assert "Backup written" in out
        assert "MB" in out or "KB" in out  # size rendered

    def test_explicit_out_path(self, cli, isolated_data, tmp_path):
        (isolated_data / "x.json").write_text("{}", encoding="utf-8")
        target = tmp_path / "manual-snap.tar.gz"
        out, code = _capture(
            cli._cmd_db_backup, str(target),
        )
        assert code == 0
        assert target.exists()

    def test_archive_contents(self, cli, isolated_data, tmp_path):
        """The tarball contains the data/ directory tree."""
        (isolated_data / "approval_queue.db").write_bytes(b"approval data")
        (isolated_data / "goal_state.json").write_text(
            '{"x": 1}', encoding="utf-8",
        )
        target = tmp_path / "snap.tar.gz"
        _capture(cli._cmd_db_backup, str(target))

        with tarfile.open(target, "r:gz") as tar:
            names = tar.getnames()
        # Archived under "data/" prefix
        assert "data" in names or any(
            n.startswith("data/") for n in names
        )
        # The two seeded files are present
        assert any(
            n.endswith("approval_queue.db") for n in names
        )
        assert any(
            n.endswith("goal_state.json") for n in names
        )


# ─── edge cases ──────────────────────────────────────────────────


class TestEdgeCases:

    def test_missing_data_dir_exits_1(self, cli, tmp_path, monkeypatch):
        """No data/ → friendly error, exit 1."""
        monkeypatch.chdir(tmp_path)
        out, code = _capture(cli._cmd_db_backup, None)
        assert code == 1
        assert "no data directory" in out.lower()

    def test_existing_out_refused(self, cli, isolated_data, tmp_path):
        """Refuse to overwrite an existing backup — protects
        against typo'd --out that would clobber a prior snapshot."""
        (isolated_data / "x.json").write_text("{}", encoding="utf-8")
        target = tmp_path / "already-exists.tar.gz"
        target.write_text("placeholder", encoding="utf-8")

        out, code = _capture(cli._cmd_db_backup, str(target))
        assert code == 1
        assert "already exists" in out
        # Original file not overwritten
        assert target.read_text() == "placeholder"

    def test_empty_data_dir_still_backs_up(self, cli, isolated_data, tmp_path):
        """Even an empty data/ produces a valid tarball — the
        operator gets an audit trail of the empty state."""
        target = tmp_path / "empty.tar.gz"
        out, code = _capture(cli._cmd_db_backup, str(target))
        assert code == 0
        # Tarball is valid (openable)
        with tarfile.open(target, "r:gz") as tar:
            names = tar.getnames()
        assert "data" in names or any(n.startswith("data") for n in names)


# ─── restore round-trip ──────────────────────────────────────────


class TestRestoreRoundTrip:

    def test_restore_yields_identical_files(
        self, cli, isolated_data, tmp_path,
    ):
        """tar -xzf the backup → contents match the original
        data/ directory verbatim."""
        (isolated_data / "approval_queue.db").write_bytes(
            b"sample bytes",
        )
        (isolated_data / "operator_notes.json").write_text(
            '{"engines": {"x": "note"}}', encoding="utf-8",
        )

        target = tmp_path / "snap.tar.gz"
        _capture(cli._cmd_db_backup, str(target))

        # Extract into a separate dir and compare
        restore_dir = tmp_path / "restore"
        restore_dir.mkdir()
        with tarfile.open(target, "r:gz") as tar:
            tar.extractall(restore_dir)

        restored_db = restore_dir / "data" / "approval_queue.db"
        restored_json = restore_dir / "data" / "operator_notes.json"
        assert restored_db.read_bytes() == b"sample bytes"
        assert restored_json.read_text() == (
            '{"engines": {"x": "note"}}'
        )
