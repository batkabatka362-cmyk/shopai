"""Dashboard vault note detail — Option I.

Exercises the ``GET /api/vault/note?path=...`` pipeline and, more
importantly, its path-traversal guard. A single leaked ``..`` or
absolute path would turn this endpoint into an arbitrary-file-read
primitive, so the sandbox checks are the critical coverage here.

* ``_read_vault_note`` — resolves ``rel`` strictly under the vault
  root, enforces the ``.md`` suffix, trims oversize bodies, and raises
  typed errors the endpoint can map cleanly onto HTTP status codes.
* ``_api_vault_note`` — parses the query string, surfaces 400 for
  traversal/bad-type, 404 for missing files, and 200 otherwise.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from dashboard.app import (
    DashboardAPIHandler,
    _VaultNotConfigured,
    _VaultPathDenied,
    _read_vault_note,
)


def _handler(query: str = "") -> DashboardAPIHandler:
    h = object.__new__(DashboardAPIHandler)
    h._captured = []
    h._json = lambda status, data: h._captured.append((status, data))
    h.path = "/api/vault/note" + (("?" + query) if query else "")
    return h


@pytest.fixture
def temp_vault(tmp_path, monkeypatch):
    # Seed a few legit notes across the expected folders.
    (tmp_path / "Wins").mkdir()
    (tmp_path / "Wins" / "first-win.md").write_text(
        "# First win\n\nIt worked.\n", encoding="utf-8",
    )
    (tmp_path / "ShopAI" / "Learned").mkdir(parents=True)
    (tmp_path / "ShopAI" / "Learned" / "pattern-1.md").write_text(
        "pattern body\n", encoding="utf-8",
    )
    # Also drop a sensitive file at vault-parent so traversal attempts
    # have a real target to try to reach.
    (tmp_path.parent / "SECRET.md").write_text("do not leak", encoding="utf-8")

    monkeypatch.setattr(
        "core.adapters.config.get_config",
        lambda: {"obsidian_vault_path": str(tmp_path)},
    )
    return tmp_path


# ---------------------------------------------------------------------------
# _read_vault_note
# ---------------------------------------------------------------------------


class TestReadVaultNote:
    def test_reads_legit_note(self, temp_vault):
        data = _read_vault_note("Wins/first-win.md")
        assert data["title"] == "first-win"
        assert data["path"] == "Wins/first-win.md"
        assert "It worked" in data["body"]
        assert isinstance(data["mtime"], float)

    def test_reads_nested_folder(self, temp_vault):
        data = _read_vault_note("ShopAI/Learned/pattern-1.md")
        assert data["title"] == "pattern-1"

    def test_rejects_parent_traversal(self, temp_vault):
        with pytest.raises(_VaultPathDenied):
            _read_vault_note("../SECRET.md")

    def test_rejects_absolute_path(self, temp_vault):
        with pytest.raises(_VaultPathDenied):
            _read_vault_note("/etc/passwd")

    def test_rejects_backslash(self, temp_vault):
        with pytest.raises(_VaultPathDenied):
            _read_vault_note("Wins\\first-win.md")

    def test_rejects_null_byte(self, temp_vault):
        with pytest.raises(_VaultPathDenied):
            _read_vault_note("Wins/first-win.md\x00")

    def test_rejects_non_markdown(self, temp_vault):
        # Seed a config-ish file — must stay unreachable.
        (temp_vault / "secret.txt").write_text("nope", encoding="utf-8")
        with pytest.raises(_VaultPathDenied):
            _read_vault_note("secret.txt")

    def test_rejects_symlink_escape(self, temp_vault):
        # Symlink pointing outside the vault should resolve out and fail.
        link = temp_vault / "escape.md"
        try:
            link.symlink_to(temp_vault.parent / "SECRET.md")
        except OSError:
            pytest.skip("symlinks not supported on this filesystem")
        with pytest.raises(_VaultPathDenied):
            _read_vault_note("escape.md")

    def test_missing_file_raises(self, temp_vault):
        with pytest.raises(FileNotFoundError):
            _read_vault_note("Wins/never-was.md")

    def test_unconfigured_vault_raises(self, monkeypatch):
        monkeypatch.setattr(
            "core.adapters.config.get_config",
            lambda: {"obsidian_vault_path": ""},
        )
        with pytest.raises(_VaultNotConfigured):
            _read_vault_note("Wins/x.md")

    def test_truncates_huge_body(self, temp_vault):
        huge = temp_vault / "Wins" / "huge.md"
        huge.write_text("y" * 500_000, encoding="utf-8")
        data = _read_vault_note("Wins/huge.md")
        assert "[truncated]" in data["body"]
        assert len(data["body"]) <= 200_050  # body + suffix


# ---------------------------------------------------------------------------
# _api_vault_note endpoint
# ---------------------------------------------------------------------------


class TestAPIVaultNote:
    def test_requires_path(self, temp_vault):
        h = _handler(query="")
        h._api_vault_note()
        status, data = h._captured[-1]
        assert status == 400
        assert "path" in data["error"]

    def test_reads_when_configured(self, temp_vault):
        h = _handler(query="path=Wins/first-win.md")
        h._api_vault_note()
        status, data = h._captured[-1]
        assert status == 200
        assert data["title"] == "first-win"
        assert "It worked" in data["body"]

    def test_traversal_returns_400(self, temp_vault):
        h = _handler(query="path=../SECRET.md")
        h._api_vault_note()
        status, data = h._captured[-1]
        assert status == 400
        assert "vault" in data["error"].lower() or "path" in data["error"].lower()

    def test_missing_returns_404(self, temp_vault):
        h = _handler(query="path=Wins/missing.md")
        h._api_vault_note()
        status, data = h._captured[-1]
        assert status == 404

    def test_unconfigured_vault_returns_400(self, monkeypatch):
        monkeypatch.setattr(
            "core.adapters.config.get_config",
            lambda: {"obsidian_vault_path": ""},
        )
        h = _handler(query="path=Wins/x.md")
        h._api_vault_note()
        status, data = h._captured[-1]
        assert status == 400

    def test_url_decoded_path(self, temp_vault):
        # "ShopAI/Learned" has a slash, fine as-is; but confirm query
        # decoding also handles percent-encoded characters.
        (temp_vault / "Wins" / "my note.md").write_text(
            "spaces ok\n", encoding="utf-8",
        )
        h = _handler(query="path=Wins/my%20note.md")
        h._api_vault_note()
        status, data = h._captured[-1]
        assert status == 200
        assert data["title"] == "my note"
