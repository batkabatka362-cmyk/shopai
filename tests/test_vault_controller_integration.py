"""Vault-controller integration tests.

Covers the two integration points between the Obsidian vault and
the ShopAI autonomous loop:

  1. ``UnifiedMemory._vault_lookup()`` — retrieve() augments results
     with vault knowledge notes.
  2. ``AutonomousController._log_cycle_to_vault()`` — writes Win or
     Error notes to the vault after each cycle.
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

from core.adapters.obsidian.parser import parse_note, search_notes, write_note


# ── Helpers ──────────────────────────────────────────────────────


def _seed_vault(vault: Path) -> None:
    """Create a minimal vault with notes in several categories."""
    for folder in ("Concepts", "Errors", "Wins", "Knowledge"):
        (vault / folder).mkdir(parents=True, exist_ok=True)

    write_note(
        vault, "ShopAI Architecture", (
            "# ShopAI Architecture\n\n"
            "Overview of the autonomous e-commerce system.\n\n"
            "## Холбоотой\n\n- [[Adapter Pattern]]\n"
        ),
        frontmatter={"tags": ["concept", "architecture"]},
        folder="Concepts",
    )
    write_note(
        vault, "Adapter Pattern", (
            "# Adapter Pattern\n\n"
            "BaseAdapter → _execute() → AdapterResult pattern.\n"
        ),
        frontmatter={"tags": ["concept", "adapter"]},
        folder="Concepts",
    )
    write_note(
        vault, "Shopify API Basics", (
            "# Shopify API Basics\n\n"
            "REST Admin API and GraphQL usage notes.\n"
        ),
        frontmatter={"tags": ["knowledge", "shopify", "api"]},
        folder="Knowledge",
    )


def _make_cycle_result(
    *,
    cycle_id: str = "cycle_1_1234",
    store_id: str = "test-store",
    error_count: int = 0,
    insights: int = 5,
    proposed: int = 3,
    reflection: dict | None = None,
) -> dict[str, Any]:
    """Build a minimal cycle_result dict for testing."""
    result: dict[str, Any] = {
        "cycle_id": cycle_id,
        "store_id": store_id,
        "duration_s": 2.5,
        "status": "complete",
        "phase_error_count": error_count,
        "phase_errors": {},
        "phases": {
            "analysis": {"insights": insights},
            "decisions": {"proposed": proposed},
            "data": {},
            "brain": {},
        },
    }
    if reflection:
        result["reflection"] = reflection
    return result


# =====================================================================
# 1. UnifiedMemory._vault_lookup
# =====================================================================


class TestVaultLookup:
    """Tests for ``UnifiedMemory._vault_lookup()``."""

    @pytest.fixture()
    def vault(self, tmp_path: Path) -> Path:
        vault = tmp_path / "vault"
        vault.mkdir()
        _seed_vault(vault)
        return vault

    def test_returns_matching_notes(self, vault: Path, monkeypatch):
        """vault_lookup returns notes matching the query."""
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
        from core.adapters.config import reset_config
        reset_config()

        from core.memory.unified_memory import UnifiedMemory
        mem = UnifiedMemory.__new__(UnifiedMemory)
        # _build_vector_query("architecture", {}) → "architecture"
        # which matches "ShopAI Architecture" title via substring
        results = mem._vault_lookup("architecture", {})
        assert isinstance(results, list)
        assert len(results) > 0
        first = results[0]
        assert "title" in first
        assert "score" in first
        assert first["source"] == "obsidian_vault"

        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        reset_config()

    def test_returns_empty_when_no_vault(self, monkeypatch):
        """vault_lookup returns [] when OBSIDIAN_VAULT_PATH is unset."""
        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        from core.adapters.config import reset_config
        reset_config()

        from core.memory.unified_memory import UnifiedMemory
        mem = UnifiedMemory.__new__(UnifiedMemory)
        results = mem._vault_lookup("anything", {})
        assert results == []

        reset_config()

    def test_returns_empty_for_nonexistent_path(self, tmp_path, monkeypatch):
        """vault_lookup returns [] when vault path doesn't exist."""
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "nope"))
        from core.adapters.config import reset_config
        reset_config()

        from core.memory.unified_memory import UnifiedMemory
        mem = UnifiedMemory.__new__(UnifiedMemory)
        results = mem._vault_lookup("test", {})
        assert results == []

        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        reset_config()

    def test_truncates_body_to_500(self, vault: Path, monkeypatch):
        """Body field in results is truncated to 500 chars."""
        # Write a note with a very long body
        write_note(
            vault, "Long Note",
            "x" * 1000,
            frontmatter={"tags": ["test"]},
            folder="Knowledge",
        )
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
        from core.adapters.config import reset_config
        reset_config()

        from core.memory.unified_memory import UnifiedMemory
        mem = UnifiedMemory.__new__(UnifiedMemory)
        results = mem._vault_lookup("long note test", {})
        for r in results:
            assert len(r.get("body", "")) <= 500

        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        reset_config()

    def test_returns_empty_for_empty_query(self, vault: Path, monkeypatch):
        """vault_lookup returns [] when query is empty."""
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
        from core.adapters.config import reset_config
        reset_config()

        from core.memory.unified_memory import UnifiedMemory
        mem = UnifiedMemory.__new__(UnifiedMemory)
        results = mem._vault_lookup("", {})
        assert results == []

        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        reset_config()


# =====================================================================
# 2. AutonomousController._log_cycle_to_vault
# =====================================================================


class TestLogCycleToVault:
    """Tests for ``AutonomousController._log_cycle_to_vault()``."""

    @pytest.fixture()
    def vault(self, tmp_path: Path) -> Path:
        vault = tmp_path / "vault"
        vault.mkdir()
        return vault

    @pytest.fixture()
    def controller(self):
        """Bare controller via __new__ — no initialize() needed."""
        from core.autonomous.controller import AutonomousController
        return AutonomousController.__new__(AutonomousController)

    def test_writes_win_note_on_success(self, vault, controller, monkeypatch):
        """Successful cycle writes a Win note."""
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
        from core.adapters.config import reset_config
        reset_config()

        cycle_result = _make_cycle_result()
        controller._log_cycle_to_vault(cycle_result, {})

        wins_dir = vault / "Wins"
        assert wins_dir.exists()
        notes = list(wins_dir.glob("*.md"))
        assert len(notes) == 1

        note = parse_note(notes[0], vault)
        assert "win" in note["tags"]
        assert "cycle" in note["tags"]
        assert note["frontmatter"]["cycle_id"] == "cycle_1_1234"
        assert note["frontmatter"]["phase_error_count"] == 0

        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        reset_config()

    def test_writes_error_note_on_high_failure_rate(self, vault, controller, monkeypatch):
        """Cycle with >25% phase failures writes an Error note."""
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
        from core.adapters.config import reset_config
        reset_config()

        phase_errors = {
            "data": "TimeoutError: API timeout",
            "brain": "ValueError: no data",
            "competitor": "ConnectionError: offline",
        }
        cycle_result = _make_cycle_result(error_count=3)
        cycle_result["phase_errors"] = phase_errors

        controller._log_cycle_to_vault(cycle_result, phase_errors)

        errors_dir = vault / "Errors"
        assert errors_dir.exists()
        notes = list(errors_dir.glob("*.md"))
        assert len(notes) == 1

        note = parse_note(notes[0], vault)
        assert "error" in note["tags"]
        assert "TimeoutError" in note["body"]
        assert note["frontmatter"]["phase_error_count"] == 3

        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        reset_config()

    def test_writes_win_on_low_failure_rate(self, vault, controller, monkeypatch):
        """A single failure in many phases is still a Win."""
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
        from core.adapters.config import reset_config
        reset_config()

        phase_errors = {"seo_analysis": "ImportError: missing dep"}
        cycle_result = _make_cycle_result(error_count=1)
        cycle_result["phase_errors"] = phase_errors

        controller._log_cycle_to_vault(cycle_result, phase_errors)

        # 1 error out of 4 phases = 25%, threshold is >25%, so it's a Win
        wins_dir = vault / "Wins"
        assert wins_dir.exists()
        notes = list(wins_dir.glob("*.md"))
        assert len(notes) == 1

        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        reset_config()

    def test_includes_reflection_in_win(self, vault, controller, monkeypatch):
        """Win note includes reflection summary when present."""
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
        from core.adapters.config import reset_config
        reset_config()

        cycle_result = _make_cycle_result(
            reflection={"patterns_promoted": 2},
        )
        controller._log_cycle_to_vault(cycle_result, {})

        wins_dir = vault / "Wins"
        notes = list(wins_dir.glob("*.md"))
        assert len(notes) == 1
        note = parse_note(notes[0], vault)
        assert "Patterns promoted: 2" in note["body"]

        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        reset_config()

    def test_skips_when_no_vault_path(self, controller, monkeypatch):
        """Does nothing when OBSIDIAN_VAULT_PATH is not set."""
        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        from core.adapters.config import reset_config
        reset_config()

        cycle_result = _make_cycle_result()
        # Should not raise
        controller._log_cycle_to_vault(cycle_result, {})

        reset_config()

    def test_skips_when_vault_dir_missing(self, tmp_path, controller, monkeypatch):
        """Does nothing when vault path doesn't exist on disk."""
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "nope"))
        from core.adapters.config import reset_config
        reset_config()

        cycle_result = _make_cycle_result()
        # Should not raise
        controller._log_cycle_to_vault(cycle_result, {})

        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        reset_config()

    def test_error_note_has_wikilinks(self, vault, controller, monkeypatch):
        """Error notes include wikilinks for graph view connectivity."""
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
        from core.adapters.config import reset_config
        reset_config()

        phase_errors = {"a": "err1", "b": "err2", "c": "err3"}
        cycle_result = _make_cycle_result(error_count=3)
        cycle_result["phase_errors"] = phase_errors

        controller._log_cycle_to_vault(cycle_result, phase_errors)

        errors_dir = vault / "Errors"
        note = parse_note(list(errors_dir.glob("*.md"))[0], vault)
        assert "[[ShopAI Architecture]]" in note["body"]
        assert len(note["wikilinks"]) >= 1

        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        reset_config()

    def test_win_note_has_wikilinks(self, vault, controller, monkeypatch):
        """Win notes include wikilinks for graph view connectivity."""
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
        from core.adapters.config import reset_config
        reset_config()

        cycle_result = _make_cycle_result()
        controller._log_cycle_to_vault(cycle_result, {})

        wins_dir = vault / "Wins"
        note = parse_note(list(wins_dir.glob("*.md"))[0], vault)
        assert "[[ShopAI Architecture]]" in note["body"]
        assert "[[Obsidian Integration Complete]]" in note["body"]

        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        reset_config()

    def test_frontmatter_has_date(self, vault, controller, monkeypatch):
        """Note frontmatter includes today's date."""
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
        from core.adapters.config import reset_config
        reset_config()

        cycle_result = _make_cycle_result()
        controller._log_cycle_to_vault(cycle_result, {})

        wins_dir = vault / "Wins"
        note = parse_note(list(wins_dir.glob("*.md"))[0], vault)
        assert "date" in note["frontmatter"]

        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        reset_config()


# =====================================================================
# 3. retrieve() includes vault_knowledge key
# =====================================================================


class TestRetrieveVaultKnowledge:
    """Verify that UnifiedMemory.retrieve() populates vault_knowledge."""

    def test_retrieve_has_vault_knowledge_key(self, tmp_path, monkeypatch):
        """retrieve() result dict contains vault_knowledge."""
        vault = tmp_path / "vault"
        vault.mkdir()
        _seed_vault(vault)
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
        from core.adapters.config import reset_config
        reset_config()

        from core.memory.unified_memory import UnifiedMemory
        mem = UnifiedMemory()
        result = mem.retrieve("architecture", {"topic": "shopify"})
        assert "vault_knowledge" in result
        assert isinstance(result["vault_knowledge"], list)

        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        reset_config()

    def test_retrieve_vault_knowledge_empty_without_config(self, monkeypatch):
        """vault_knowledge is [] when vault is not configured."""
        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        from core.adapters.config import reset_config
        reset_config()

        from core.memory.unified_memory import UnifiedMemory
        mem = UnifiedMemory()
        result = mem.retrieve("test", {})
        assert result.get("vault_knowledge") == []

        reset_config()
