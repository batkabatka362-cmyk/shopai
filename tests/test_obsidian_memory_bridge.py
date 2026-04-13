"""Tests for the VaultMemoryBridge.

Covers:
  * import_vault — scans notes, ingests into memory
  * export_knowledge — writes learned knowledge as notes
  * Idempotency — re-import skips unchanged notes
  * Tag / folder filtering during import
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.adapters.obsidian.memory_bridge import VaultMemoryBridge


# ── Mock memory ───────────────────────────────────────────────


class MockMemory:
    """Minimal mock for UnifiedMemory interface."""

    def __init__(self):
        self.ingested: list[dict[str, Any]] = []
        self._retrieve_data: dict[str, Any] = {
            "best_cases": [],
            "failures": [],
            "rules": [],
            "patterns": [],
            "total_memories": 0,
        }

    def ingest(self, category: str, data: Any, source: str = "",
               store_id: str = "", ttl: int = 600) -> None:
        self.ingested.append({
            "category": category,
            "data": data,
            "source": source,
        })

    def retrieve(self, category: str, context: dict | None = None) -> dict:
        return self._retrieve_data

    def set_retrieve_data(self, data: dict) -> None:
        self._retrieve_data = data


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    """Create a vault with sample notes."""
    (tmp_path / "Knowledge.md").write_text(textwrap.dedent("""\
        ---
        title: Knowledge Note
        tags:
          - knowledge
          - important
        ---
        # Knowledge Note

        This is important knowledge about the system.
    """), encoding="utf-8")

    (tmp_path / "Signal.md").write_text(textwrap.dedent("""\
        ---
        title: Signal Note
        tags:
          - signal
        ---
        A signal observation.
    """), encoding="utf-8")

    sub = tmp_path / "Archive"
    sub.mkdir()
    (sub / "Old Note.md").write_text(textwrap.dedent("""\
        ---
        title: Old Note
        tags:
          - archive
        ---
        Archived content.
    """), encoding="utf-8")

    # Hidden dir
    hidden = tmp_path / ".obsidian"
    hidden.mkdir()
    (hidden / "config.md").write_text("config", encoding="utf-8")

    return tmp_path


@pytest.fixture()
def memory() -> MockMemory:
    return MockMemory()


# ── Import tests ──────────────────────────────────────────────


class TestImportVault:
    def test_imports_all_notes(self, vault: Path, memory: MockMemory):
        bridge = VaultMemoryBridge(vault)
        result = bridge.import_vault(memory)
        assert result["imported"] >= 3
        assert result["errors"] == 0
        # All ingested records have the right category/source
        for record in memory.ingested:
            assert record["category"] == "vault_note"
            assert record["source"] == "obsidian_vault"

    def test_skips_hidden_dirs(self, vault: Path, memory: MockMemory):
        bridge = VaultMemoryBridge(vault)
        bridge.import_vault(memory)
        paths = [r["data"]["vault_path"] for r in memory.ingested]
        assert not any(".obsidian" in p for p in paths)

    def test_folder_filter(self, vault: Path, memory: MockMemory):
        bridge = VaultMemoryBridge(vault)
        result = bridge.import_vault(memory, folder="Archive")
        assert result["imported"] == 1
        assert memory.ingested[0]["data"]["title"] == "Old Note"

    def test_tag_filter(self, vault: Path, memory: MockMemory):
        bridge = VaultMemoryBridge(vault)
        result = bridge.import_vault(memory, tags=["knowledge"])
        assert result["imported"] == 1
        assert memory.ingested[0]["data"]["title"] == "Knowledge Note"

    def test_nonexistent_folder(self, vault: Path, memory: MockMemory):
        bridge = VaultMemoryBridge(vault)
        result = bridge.import_vault(memory, folder="nonexistent")
        assert result["imported"] == 0

    def test_ingested_data_shape(self, vault: Path, memory: MockMemory):
        bridge = VaultMemoryBridge(vault)
        bridge.import_vault(memory)
        for record in memory.ingested:
            data = record["data"]
            assert "title" in data
            assert "body" in data
            assert "tags" in data
            assert "wikilinks" in data
            assert "vault_path" in data
            assert "content_hash" in data
            assert "memory_class" in data


# ── Idempotency tests ────────────────────────────────────────


class TestIdempotency:
    def test_reimport_skips_unchanged(self, vault: Path, memory: MockMemory):
        bridge = VaultMemoryBridge(vault)
        result1 = bridge.import_vault(memory)
        count1 = result1["imported"]
        assert count1 >= 3

        # Second import — same content, should skip all
        memory2 = MockMemory()
        result2 = bridge.import_vault(memory2)
        assert result2["imported"] == 0
        assert result2["skipped"] >= count1

    def test_reimport_picks_up_changes(self, vault: Path, memory: MockMemory):
        bridge = VaultMemoryBridge(vault)
        bridge.import_vault(memory)

        # Modify a note
        (vault / "Knowledge.md").write_text(textwrap.dedent("""\
            ---
            title: Knowledge Note Updated
            tags:
              - knowledge
              - updated
            ---
            Updated knowledge content.
        """), encoding="utf-8")

        memory2 = MockMemory()
        result2 = bridge.import_vault(memory2)
        assert result2["imported"] >= 1
        titles = [r["data"]["title"] for r in memory2.ingested]
        assert "Knowledge Note Updated" in titles

    def test_state_file_created(self, vault: Path, memory: MockMemory):
        bridge = VaultMemoryBridge(vault)
        bridge.import_vault(memory)
        state_file = vault / ".shopai_import_state.json"
        assert state_file.exists()
        state = json.loads(state_file.read_text(encoding="utf-8"))
        assert len(state) >= 3


# ── Export tests ──────────────────────────────────────────────


class TestExportKnowledge:
    def test_exports_cases(self, vault: Path, memory: MockMemory):
        memory.set_retrieve_data({
            "best_cases": [
                {"title": "Learned Rule 1", "body": "Always check X before Y."},
                {"title": "Learned Rule 2", "body": "Avoid pattern Z."},
            ],
            "failures": [],
            "rules": [],
            "patterns": [],
            "total_memories": 2,
        })
        bridge = VaultMemoryBridge(vault)
        result = bridge.export_knowledge(memory)
        assert result["exported"] == 2
        exported_dir = vault / "ShopAI" / "Learned"
        assert exported_dir.is_dir()
        files = list(exported_dir.glob("*.md"))
        assert len(files) == 2

    def test_export_skips_existing(self, vault: Path, memory: MockMemory):
        memory.set_retrieve_data({
            "best_cases": [
                {"title": "Existing Rule", "body": "Some content."},
            ],
        })
        bridge = VaultMemoryBridge(vault)
        # First export
        result1 = bridge.export_knowledge(memory)
        assert result1["exported"] == 1
        # Second export — should skip
        result2 = bridge.export_knowledge(memory)
        assert result2["exported"] == 0
        assert result2["skipped"] == 1

    def test_export_empty_cases(self, vault: Path, memory: MockMemory):
        bridge = VaultMemoryBridge(vault)
        result = bridge.export_knowledge(memory)
        assert result["exported"] == 0
        assert result["skipped"] == 0

    def test_exported_note_frontmatter(self, vault: Path, memory: MockMemory):
        memory.set_retrieve_data({
            "best_cases": [
                {
                    "title": "FM Check",
                    "body": "Content here.",
                    "confidence": 0.95,
                },
            ],
        })
        bridge = VaultMemoryBridge(vault)
        bridge.export_knowledge(memory)
        note_path = vault / "ShopAI" / "Learned" / "FM-Check.md"
        assert note_path.exists()
        content = note_path.read_text(encoding="utf-8")
        assert "source: shopai" in content
        assert "exported_at:" in content
        assert "confidence:" in content
        assert "shopai" in content  # tag

    def test_export_custom_folder(self, vault: Path, memory: MockMemory):
        memory.set_retrieve_data({
            "best_cases": [
                {"title": "Custom Folder", "body": "Content."},
            ],
        })
        bridge = VaultMemoryBridge(vault)
        result = bridge.export_knowledge(
            memory, folder="Custom/Export",
        )
        assert result["exported"] == 1
        assert (vault / "Custom" / "Export" / "Custom-Folder.md").exists()
