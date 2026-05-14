"""Tests for the operator-notes round trip:

  exporter (#95) → operator edits → importer → NotesStore

Coverage:
  1. ``NotesStore`` — read/write, atomic replace, corrupted-file
     fallback, persistence across instances.
  2. ``_parse_frontmatter`` — light YAML-ish key:value parser.
  3. ``_extract_notes_body`` — finds the heading, filters
     placeholder, strips tag line.
  4. ``ObsidianImporter`` — happy path, skip rules (no
     frontmatter, wrong source, no notes section, placeholder
     only).
  5. End-to-end — export → annotate → import → retrieve.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core.knowledge import NotesStore, ObsidianExporter, ObsidianImporter
from core.knowledge.importer import (
    ImportSummary,
    _extract_notes_body,
    _parse_frontmatter,
)


# ─── NotesStore ────────────────────────────────────────────────


class TestNotesStore:

    def test_get_returns_empty_for_unknown(self, tmp_path: Path):
        store = NotesStore(tmp_path / "notes.json")
        assert store.get_engine_notes("anything") == ""
        assert store.get_goal_notes("anything") == ""

    def test_set_then_get_engine(self, tmp_path: Path):
        store = NotesStore(tmp_path / "notes.json")
        store.set_engine_notes(
            "cart_recovery", "be careful with deep discounts",
        )
        assert store.get_engine_notes("cart_recovery") == (
            "be careful with deep discounts"
        )

    def test_set_then_get_goal(self, tmp_path: Path):
        store = NotesStore(tmp_path / "notes.json")
        store.set_goal_notes("grow_customers", "focus on retention")
        assert store.get_goal_notes("grow_customers") == "focus on retention"

    def test_persistence_across_instances(self, tmp_path: Path):
        path = tmp_path / "notes.json"
        NotesStore(path).set_engine_notes("x", "y")
        # New instance reads the same file
        assert NotesStore(path).get_engine_notes("x") == "y"

    def test_replace_all_drops_old_entries(self, tmp_path: Path):
        store = NotesStore(tmp_path / "notes.json")
        store.set_engine_notes("old", "stale")
        store.set_engine_notes("kept", "fresh")
        store.replace_all(
            engine_notes={"kept": "fresh", "new": "shiny"},
            goal_notes={},
        )
        assert store.get_engine_notes("old") == ""
        assert store.get_engine_notes("kept") == "fresh"
        assert store.get_engine_notes("new") == "shiny"

    def test_clear_drops_everything(self, tmp_path: Path):
        store = NotesStore(tmp_path / "notes.json")
        store.set_engine_notes("x", "y")
        store.clear()
        assert store.all_engine_notes() == {}
        assert store.all_goal_notes() == {}
        assert store.meta() == {}

    def test_meta_reflects_replace_all(self, tmp_path: Path):
        store = NotesStore(tmp_path / "notes.json")
        before = time.time()
        store.replace_all(
            engine_notes={"a": "1"}, goal_notes={"b": "2"},
            source_path="/some/vault",
        )
        meta = store.meta()
        assert meta["imported_count"] == 2
        assert meta["last_import_source"] == "/some/vault"
        assert meta["last_import_at"] >= before

    def test_corrupted_json_returns_empty(self, tmp_path: Path):
        path = tmp_path / "notes.json"
        path.write_text("{not valid json", encoding="utf-8")
        store = NotesStore(path)
        # Doesn't raise; returns empty
        assert store.all_engine_notes() == {}
        assert store.all_goal_notes() == {}

    def test_missing_file_returns_empty(self, tmp_path: Path):
        store = NotesStore(tmp_path / "nonexistent.json")
        assert store.all_engine_notes() == {}
        assert store.meta() == {}

    def test_blank_name_rejected(self, tmp_path: Path):
        store = NotesStore(tmp_path / "notes.json")
        store.set_engine_notes("", "should be ignored")
        store.set_engine_notes("   ", "should be ignored")
        assert store.all_engine_notes() == {}

    def test_per_entry_source_paths(self, tmp_path: Path):
        store = NotesStore(tmp_path / "notes.json")
        store.replace_all(
            engine_notes={"cart_recovery": "n", "loyalty": "m"},
            goal_notes={},
            source_path="/vault",
            engine_sources={
                "cart_recovery": "engines/cart_recovery.md",
                "loyalty": "engines/loyalty.md",
            },
        )
        notes = store.all_engine_notes()
        assert notes["cart_recovery"]["source_path"] == (
            "engines/cart_recovery.md"
        )
        assert notes["loyalty"]["source_path"] == "engines/loyalty.md"


# ─── _parse_frontmatter ────────────────────────────────────────


class TestParseFrontmatter:

    def test_simple_pairs(self):
        raw = "name: cart_recovery\ntype: engine\n"
        assert _parse_frontmatter(raw) == {
            "name": "cart_recovery", "type": "engine",
        }

    def test_quoted_values_stripped(self):
        raw = 'name: "cart recovery"\ntype: \'engine\'\n'
        result = _parse_frontmatter(raw)
        assert result["name"] == "cart recovery"
        assert result["type"] == "engine"

    def test_inline_comments_stripped(self):
        raw = "name: cart_recovery  # internal\ntype: engine\n"
        assert _parse_frontmatter(raw)["name"] == "cart_recovery"

    def test_lines_without_colon_ignored(self):
        raw = "name: x\njust a stray line\ntype: engine\n"
        assert _parse_frontmatter(raw) == {"name": "x", "type": "engine"}

    def test_empty_returns_empty(self):
        assert _parse_frontmatter("") == {}


# ─── _extract_notes_body ───────────────────────────────────────


class TestExtractNotesBody:

    def test_no_heading_returns_empty(self):
        body = "# title\n\nsome content"
        assert _extract_notes_body(body) == ""

    def test_extracts_simple_note(self):
        body = (
            "# title\n\n"
            "## Operator notes\n\n"
            "This engine works best on weekends.\n\n"
            "#shopai/engine\n"
        )
        assert _extract_notes_body(body) == (
            "This engine works best on weekends."
        )

    def test_placeholder_only_returns_empty(self):
        body = (
            "## Operator notes\n\n"
            "_Add your own observations below. "
            "This block is preserved across re-exports._\n\n"
            "#shopai/engine\n"
        )
        assert _extract_notes_body(body) == ""

    def test_placeholder_filtered_real_note_kept(self):
        body = (
            "## Operator notes\n\n"
            "_Add observations or override hints here._\n\n"
            "Real operator insight goes here.\n"
            "Second line of insight.\n\n"
            "#shopai/goal\n"
        )
        result = _extract_notes_body(body)
        assert "Real operator insight" in result
        assert "Second line of insight" in result
        assert "Add observations" not in result

    def test_multiline_preserved(self):
        body = (
            "## Operator notes\n\n"
            "Line one.\n"
            "Line two.\n"
            "Line three.\n\n"
            "#shopai/engine\n"
        )
        result = _extract_notes_body(body)
        assert result == "Line one.\nLine two.\nLine three."

    def test_subsequent_heading_terminates(self):
        body = (
            "## Operator notes\n\n"
            "Captured.\n\n"
            "## Some other section\n\n"
            "NOT captured.\n"
        )
        result = _extract_notes_body(body)
        assert "Captured." in result
        assert "NOT captured" not in result


# ─── ObsidianImporter ──────────────────────────────────────────


class TestImporterSkipRules:

    def test_missing_dir(self, tmp_path: Path):
        store = NotesStore(tmp_path / "notes.json")
        importer = ObsidianImporter(store=store)
        summary = importer.import_vault(tmp_path / "nonexistent")
        assert isinstance(summary, ImportSummary)
        assert summary.engines_imported == 0
        assert any("not found" in s for s in summary.skipped)

    def test_file_without_frontmatter_skipped(self, tmp_path: Path):
        # Create a vault with one non-shopai .md
        (tmp_path / "engines").mkdir()
        (tmp_path / "engines" / "stranger.md").write_text(
            "# stranger\n\nrandom prose, no frontmatter\n",
            encoding="utf-8",
        )
        store = NotesStore(tmp_path / "notes.json")
        summary = ObsidianImporter(store=store).import_vault(tmp_path)
        assert summary.files_scanned == 1
        assert summary.files_skipped == 1
        assert summary.engines_imported == 0

    def test_wrong_source_skipped(self, tmp_path: Path):
        (tmp_path / "engines").mkdir()
        (tmp_path / "engines" / "other.md").write_text(
            "---\nname: other\ntype: engine\nsource: someone_else\n---\n"
            "\n## Operator notes\n\nshould not be ingested\n",
            encoding="utf-8",
        )
        store = NotesStore(tmp_path / "notes.json")
        summary = ObsidianImporter(store=store).import_vault(tmp_path)
        assert summary.engines_imported == 0

    def test_no_notes_section_skipped(self, tmp_path: Path):
        (tmp_path / "engines").mkdir()
        (tmp_path / "engines" / "x.md").write_text(
            "---\nname: x\ntype: engine\nsource: shopai\n---\n"
            "\n# x\n\nbody without notes section\n",
            encoding="utf-8",
        )
        store = NotesStore(tmp_path / "notes.json")
        summary = ObsidianImporter(store=store).import_vault(tmp_path)
        assert summary.engines_imported == 0


class TestImporterHappyPath:

    def test_imports_engine_and_goal(self, tmp_path: Path):
        # Build a minimal vault by hand (no exporter needed)
        (tmp_path / "engines").mkdir()
        (tmp_path / "goals").mkdir()
        (tmp_path / "engines" / "cart_recovery.md").write_text(
            "---\nname: cart_recovery\ntype: engine\n"
            "source: shopai\n---\n\n"
            "## Operator notes\n\n"
            "Engine works best with offers < 10%.\n",
            encoding="utf-8",
        )
        (tmp_path / "goals" / "grow_customers.md").write_text(
            "---\nname: grow_customers\ntype: goal\n"
            "source: shopai\n---\n\n"
            "## Operator notes\n\n"
            "Focus on retention this Q.\n",
            encoding="utf-8",
        )

        store = NotesStore(tmp_path / "notes.json")
        summary = ObsidianImporter(store=store).import_vault(tmp_path)

        assert summary.engines_imported == 1
        assert summary.goals_imported == 1
        assert store.get_engine_notes("cart_recovery") == (
            "Engine works best with offers < 10%."
        )
        assert store.get_goal_notes("grow_customers") == (
            "Focus on retention this Q."
        )

    def test_replace_drops_removed_entries(self, tmp_path: Path):
        store = NotesStore(tmp_path / "notes.json")
        # Pre-seed an entry not in the vault
        store.set_engine_notes("ghost_engine", "haunting")

        (tmp_path / "engines").mkdir()
        (tmp_path / "engines" / "kept.md").write_text(
            "---\nname: kept\ntype: engine\nsource: shopai\n---\n"
            "## Operator notes\n\nstill alive\n",
            encoding="utf-8",
        )
        ObsidianImporter(store=store).import_vault(tmp_path)
        assert store.get_engine_notes("ghost_engine") == ""
        assert store.get_engine_notes("kept") == "still alive"


# ─── End-to-end: exporter + importer round trip ────────────────


class TestRoundTrip:

    def test_export_annotate_import_retrieve(self, tmp_path: Path):
        vault = tmp_path / "vault"
        ObsidianExporter(vault).export()

        # Annotate cart_recovery — append above the tag line
        cr = vault / "engines" / "cart_recovery.md"
        text = cr.read_text(encoding="utf-8")
        text = text.replace(
            "#shopai/engine #shopai/goal/grow_customers",
            "Live experience: discount must be under 10%.\n\n"
            "#shopai/engine #shopai/goal/grow_customers",
        )
        cr.write_text(text, encoding="utf-8")

        store = NotesStore(tmp_path / "notes.json")
        summary = ObsidianImporter(store=store).import_vault(vault)
        assert summary.engines_imported == 1
        retrieved = store.get_engine_notes("cart_recovery")
        assert "discount must be under 10%" in retrieved


# ─── ImportSummary serialisation ───────────────────────────────


class TestImportSummarySerialization:

    def test_to_dict_round_trip(self):
        s = ImportSummary(
            engines_imported=5, goals_imported=3,
            files_scanned=44, files_skipped=36,
            skipped=["x.md: bad"],
        )
        d = s.to_dict()
        assert d == {
            "engines_imported": 5,
            "goals_imported": 3,
            "files_scanned": 44,
            "files_skipped": 36,
            "skipped": ["x.md: bad"],
        }
