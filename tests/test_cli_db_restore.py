"""Tests for ``shopai db restore <archive>`` — restore data/ from a
backup tarball.

Companion to PR #133 (``shopai db backup``). The restore path:
  1. Refuses without --yes (safety)
  2. Moves current data/ aside to data.<timestamp>.bak/ before
     extracting (recoverable on mistake)
  3. Extracts archive contents back into ./data/
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


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


@pytest.fixture
def backup_archive(tmp_path, cli, monkeypatch):
    """Make a real backup tarball using the backup verb, then
    return the archive path. Each test gets its own data/ +
    archive combo."""
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "approval_queue.db").write_bytes(b"original data")
    (data_dir / "operator_notes.json").write_text(
        '{"engines": {"x": "original note"}}', encoding="utf-8",
    )

    archive = tmp_path / "snap.tar.gz"
    _capture(cli._cmd_db_backup, str(archive))
    return archive


# ─── safety / validation ──────────────────────────────────────────


class TestSafetyChecks:

    def test_missing_archive_exits_1(self, cli, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out, code = _capture(
            cli._cmd_db_restore,
            str(tmp_path / "nonexistent.tar.gz"),
            yes=True,
        )
        assert code == 1
        assert "archive not found" in out

    def test_requires_yes_flag(self, cli, backup_archive):
        out, code = _capture(
            cli._cmd_db_restore, str(backup_archive), yes=False,
        )
        assert code == 1
        assert "Re-run with --yes" in out


# ─── safe move-aside behavior ─────────────────────────────────────


class TestMoveAside:

    def test_current_data_moved_to_bak_dir(
        self, cli, backup_archive, tmp_path,
    ):
        """Current data/ is preserved as data.<ts>.bak/ — restore
        is recoverable even if the operator picked the wrong
        tarball."""
        # Mutate data/ before restoring so we can verify it's the
        # OLD content that moved aside
        data_dir = tmp_path / "data"
        (data_dir / "approval_queue.db").write_bytes(b"MUTATED")

        _capture(
            cli._cmd_db_restore,
            str(backup_archive),
            yes=True,
        )

        # data.<ts>.bak/ exists with the mutated content
        bak_dirs = list(tmp_path.glob("data.*.bak"))
        assert len(bak_dirs) == 1
        assert (
            bak_dirs[0] / "approval_queue.db"
        ).read_bytes() == b"MUTATED"

    def test_restored_content_is_archive_content(
        self, cli, backup_archive, tmp_path,
    ):
        data_dir = tmp_path / "data"
        (data_dir / "approval_queue.db").write_bytes(b"MUTATED")

        _capture(
            cli._cmd_db_restore,
            str(backup_archive),
            yes=True,
        )

        # data/ now has the original content from the archive
        assert (
            data_dir / "approval_queue.db"
        ).read_bytes() == b"original data"
        assert (
            data_dir / "operator_notes.json"
        ).read_text() == '{"engines": {"x": "original note"}}'

    def test_no_existing_data_dir_still_restores(
        self, cli, backup_archive, tmp_path,
    ):
        """If data/ doesn't exist (fresh install), restore still
        works — no move-aside step needed."""
        # Remove the seeded data/ dir before restoring
        import shutil
        shutil.rmtree(tmp_path / "data")

        out, code = _capture(
            cli._cmd_db_restore,
            str(backup_archive),
            yes=True,
        )
        assert code == 0
        assert (tmp_path / "data" / "approval_queue.db").exists()


# ─── failure modes ───────────────────────────────────────────────


class TestFailureModes:

    def test_corrupt_archive_exits_1(self, cli, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        bad_archive = tmp_path / "bad.tar.gz"
        bad_archive.write_bytes(b"not actually a tarball")
        out, code = _capture(
            cli._cmd_db_restore,
            str(bad_archive),
            yes=True,
        )
        assert code == 1
        assert "extract failed" in out

    def test_existing_bak_dir_refused(
        self, cli, backup_archive, tmp_path,
    ):
        """If a data.<ts>.bak/ already exists at the timestamp,
        abort rather than clobber it."""
        # Force-create a collision (real-world this is impossible
        # except within the same second)
        import datetime
        ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        (tmp_path / f"data.{ts}.bak").mkdir()

        out, code = _capture(
            cli._cmd_db_restore,
            str(backup_archive),
            yes=True,
        )
        assert code == 1
        assert "already exists" in out
