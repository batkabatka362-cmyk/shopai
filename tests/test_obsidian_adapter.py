"""Tests for the ObsidianVaultAdapter.

Covers:
  * is_configured() with and without vault path
  * _execute() dispatch for all 3 capabilities
  * Validation errors (missing params, non-existent vault)
  * Path traversal prevention
  * Bootstrap registration
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from core.adapters.base import AdapterCategory, Capability
from core.adapters.config import reset_config
from core.adapters.errors import (
    AdapterNotConfigured,
    AdapterValidationError,
)
from core.adapters.obsidian.vault import ObsidianVaultAdapter


# ── Helpers ───────────────────────────────────────────────────


def _configure_vault(monkeypatch, vault_path: str) -> None:
    """Set the vault path env var and reload config."""
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", vault_path)
    from core.adapters.config import get_config
    get_config().reload()


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Ensure OBSIDIAN_VAULT_PATH is unset and config is fresh
    before each test. Tests that need the env var set call
    ``_configure_vault`` explicitly."""
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    reset_config()
    yield
    reset_config()


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    """Create a minimal vault with sample notes."""
    (tmp_path / "Note One.md").write_text(textwrap.dedent("""\
        ---
        title: Note One
        tags:
          - alpha
          - beta
        ---
        # Note One

        First note body with [[Note Two]] link.
    """), encoding="utf-8")

    (tmp_path / "Note Two.md").write_text(textwrap.dedent("""\
        ---
        title: Note Two
        tags:
          - beta
        ---
        # Note Two

        Second note body.
    """), encoding="utf-8")

    sub = tmp_path / "Projects"
    sub.mkdir()
    (sub / "Project A.md").write_text(textwrap.dedent("""\
        ---
        title: Project A
        tags:
          - project
        ---
        Project A details.
    """), encoding="utf-8")

    return tmp_path


# ── Configuration ─────────────────────────────────────────────


class TestConfiguration:
    def test_not_configured_without_env(self):
        adapter = ObsidianVaultAdapter()
        assert not adapter.is_configured()

    def test_configured_with_valid_path(self, monkeypatch, vault: Path):
        _configure_vault(monkeypatch, str(vault))
        adapter = ObsidianVaultAdapter()
        assert adapter.is_configured()

    def test_not_configured_with_nonexistent_path(self, monkeypatch):
        _configure_vault(monkeypatch, "/nonexistent/path")
        adapter = ObsidianVaultAdapter()
        assert not adapter.is_configured()

    def test_adapter_metadata(self):
        adapter = ObsidianVaultAdapter()
        assert adapter.name == "obsidian"
        assert adapter.category == AdapterCategory.KNOWLEDGE_BASE
        assert Capability.VAULT_READ_NOTES in adapter.capabilities
        assert Capability.VAULT_SEARCH_NOTES in adapter.capabilities
        assert Capability.VAULT_WRITE_NOTE in adapter.capabilities


# ── Read notes ────────────────────────────────────────────────


class TestReadNotes:
    def test_read_all(self, monkeypatch, vault: Path):
        _configure_vault(monkeypatch, str(vault))
        adapter = ObsidianVaultAdapter()
        result = adapter.execute(Capability.VAULT_READ_NOTES, {})
        assert result.ok
        notes = result.data["notes"]
        assert len(notes) >= 3

    def test_read_specific_note(self, monkeypatch, vault: Path):
        _configure_vault(monkeypatch, str(vault))
        adapter = ObsidianVaultAdapter()
        result = adapter.execute(
            Capability.VAULT_READ_NOTES, {"path": "Note One.md"},
        )
        assert result.ok
        assert result.data["count"] == 1
        assert result.data["notes"][0]["title"] == "Note One"

    def test_read_nonexistent_note(self, monkeypatch, vault: Path):
        _configure_vault(monkeypatch, str(vault))
        adapter = ObsidianVaultAdapter()
        result = adapter.execute(
            Capability.VAULT_READ_NOTES, {"path": "nonexistent.md"},
        )
        assert not result.ok

    def test_read_by_folder(self, monkeypatch, vault: Path):
        _configure_vault(monkeypatch, str(vault))
        adapter = ObsidianVaultAdapter()
        result = adapter.execute(
            Capability.VAULT_READ_NOTES, {"folder": "Projects"},
        )
        assert result.ok
        assert result.data["count"] == 1

    def test_read_by_tags(self, monkeypatch, vault: Path):
        _configure_vault(monkeypatch, str(vault))
        adapter = ObsidianVaultAdapter()
        result = adapter.execute(
            Capability.VAULT_READ_NOTES, {"tags": ["beta"]},
        )
        assert result.ok
        for note in result.data["notes"]:
            assert "beta" in note["tags"]

    def test_path_traversal_blocked(self, monkeypatch, vault: Path):
        _configure_vault(monkeypatch, str(vault))
        adapter = ObsidianVaultAdapter()
        # Write a note outside the vault to attempt traversal
        outside = vault.parent / "secret.md"
        outside.write_text("secret", encoding="utf-8")
        result = adapter.execute(
            Capability.VAULT_READ_NOTES, {"path": "../secret.md"},
        )
        assert not result.ok


# ── Search notes ──────────────────────────────────────────────


class TestSearchNotes:
    def test_search_by_query(self, monkeypatch, vault: Path):
        _configure_vault(monkeypatch, str(vault))
        adapter = ObsidianVaultAdapter()
        result = adapter.execute(
            Capability.VAULT_SEARCH_NOTES, {"query": "Note One"},
        )
        assert result.ok
        assert result.data["count"] >= 1

    def test_search_missing_query(self, monkeypatch, vault: Path):
        _configure_vault(monkeypatch, str(vault))
        adapter = ObsidianVaultAdapter()
        result = adapter.execute(Capability.VAULT_SEARCH_NOTES, {})
        assert not result.ok

    def test_search_no_results(self, monkeypatch, vault: Path):
        _configure_vault(monkeypatch, str(vault))
        adapter = ObsidianVaultAdapter()
        result = adapter.execute(
            Capability.VAULT_SEARCH_NOTES,
            {"query": "xyznonexistent"},
        )
        assert result.ok
        assert result.data["count"] == 0


# ── Write note ────────────────────────────────────────────────


class TestWriteNote:
    def test_write_note(self, monkeypatch, vault: Path):
        _configure_vault(monkeypatch, str(vault))
        adapter = ObsidianVaultAdapter()
        result = adapter.execute(
            Capability.VAULT_WRITE_NOTE,
            {
                "title": "New Note",
                "body": "Created by test",
                "folder": "ShopAI",
            },
        )
        assert result.ok
        assert result.data["title"] == "New Note"
        written = vault / "ShopAI" / "New-Note.md"
        assert written.exists()

    def test_write_missing_title(self, monkeypatch, vault: Path):
        _configure_vault(monkeypatch, str(vault))
        adapter = ObsidianVaultAdapter()
        result = adapter.execute(
            Capability.VAULT_WRITE_NOTE, {"body": "no title"},
        )
        assert not result.ok

    def test_write_with_frontmatter(self, monkeypatch, vault: Path):
        _configure_vault(monkeypatch, str(vault))
        adapter = ObsidianVaultAdapter()
        result = adapter.execute(
            Capability.VAULT_WRITE_NOTE,
            {
                "title": "FM Note",
                "body": "With metadata",
                "frontmatter": {"custom": "value"},
            },
        )
        assert result.ok
        content = (vault / "FM-Note.md").read_text(encoding="utf-8")
        assert "custom: value" in content


# ── Unconfigured adapter ─────────────────────────────────────


class TestUnconfigured:
    def test_execute_without_config(self):
        adapter = ObsidianVaultAdapter()
        assert not adapter.is_configured()
        result = adapter.execute(
            Capability.VAULT_READ_NOTES, {},
        )
        assert not result.ok


# ── Bootstrap ─────────────────────────────────────────────────


class TestBootstrap:
    def test_register_all(self, monkeypatch, vault: Path):
        _configure_vault(monkeypatch, str(vault))
        from core.adapters.obsidian.bootstrap import register_all
        from core.adapters.registry import AdapterRegistry
        reg = AdapterRegistry()
        status = register_all(registry=reg)
        assert "obsidian" in status
        assert status["obsidian"] is True

    def test_register_unconfigured(self):
        from core.adapters.obsidian.bootstrap import register_all
        from core.adapters.registry import AdapterRegistry
        reg = AdapterRegistry()
        status = register_all(registry=reg)
        assert "obsidian" in status
        assert status["obsidian"] is False
