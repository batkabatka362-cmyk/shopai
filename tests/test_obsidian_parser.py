"""Tests for the Obsidian markdown parser.

Covers:
  * YAML frontmatter parsing (valid, empty, malformed)
  * Wikilink extraction (plain and aliased)
  * Tag extraction (frontmatter + inline)
  * Note title resolution (frontmatter → H1 → filename)
  * Content hashing
  * Full-text search scoring
  * Note writing with frontmatter
  * Filename sanitisation
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from core.adapters.obsidian.parser import (
    list_notes,
    parse_note,
    search_notes,
    write_note,
    _sanitise_filename,
)


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    """Create a minimal vault with sample notes."""
    # Note with full frontmatter
    (tmp_path / "Project.md").write_text(textwrap.dedent("""\
        ---
        title: My Project
        tags:
          - project
          - shopai
        status: active
        ---
        # My Project

        This is a project note with a [[Related Note]] link.

        Also links to [[Another Note|display text]].

        Some #inline tags and #code references.
    """), encoding="utf-8")

    # Note without frontmatter
    (tmp_path / "Quick Note.md").write_text(textwrap.dedent("""\
        # Quick Note

        Just a quick note with no frontmatter.

        Has a #tag though.
    """), encoding="utf-8")

    # Note with empty frontmatter
    (tmp_path / "Empty FM.md").write_text(textwrap.dedent("""\
        ---
        ---
        Some content here.
    """), encoding="utf-8")

    # Note with malformed frontmatter
    (tmp_path / "Bad FM.md").write_text(textwrap.dedent("""\
        ---
        this is: [not: valid: yaml: {{{
        ---
        Body after bad YAML.
    """), encoding="utf-8")

    # Note in subfolder
    sub = tmp_path / "subfolder"
    sub.mkdir()
    (sub / "Deep Note.md").write_text(textwrap.dedent("""\
        ---
        title: Deep Note
        tags: deep, nested
        ---
        # Deep Note

        A note inside a subfolder.
    """), encoding="utf-8")

    # Hidden dir (should be ignored by search/list)
    hidden = tmp_path / ".obsidian"
    hidden.mkdir()
    (hidden / "config.md").write_text("config file", encoding="utf-8")

    return tmp_path


# ── parse_note ────────────────────────────────────────────────


class TestParseNote:
    def test_full_frontmatter(self, vault: Path):
        note = parse_note(vault / "Project.md", vault_root=vault)
        assert note["title"] == "My Project"
        assert note["frontmatter"]["status"] == "active"
        assert "project" in note["tags"]
        assert "shopai" in note["tags"]
        assert "inline" in note["tags"]
        assert "code" in note["tags"]
        assert note["path"] == "Project.md"
        assert len(note["content_hash"]) == 16

    def test_wikilinks_extracted(self, vault: Path):
        note = parse_note(vault / "Project.md", vault_root=vault)
        assert "Related Note" in note["wikilinks"]
        assert "Another Note" in note["wikilinks"]

    def test_no_frontmatter(self, vault: Path):
        note = parse_note(vault / "Quick Note.md", vault_root=vault)
        assert note["title"] == "Quick Note"
        assert note["frontmatter"] == {}
        assert "tag" in note["tags"]

    def test_empty_frontmatter(self, vault: Path):
        note = parse_note(vault / "Empty FM.md", vault_root=vault)
        assert note["frontmatter"] == {}
        assert note["title"] == "Empty FM"  # Falls back to filename stem

    def test_malformed_frontmatter(self, vault: Path):
        note = parse_note(vault / "Bad FM.md", vault_root=vault)
        # Should not crash — frontmatter stays empty
        assert note["frontmatter"] == {}
        assert "Body after bad YAML" in note["body"]

    def test_title_from_h1(self, vault: Path):
        note = parse_note(vault / "Quick Note.md", vault_root=vault)
        assert note["title"] == "Quick Note"

    def test_title_from_filename(self, vault: Path):
        note = parse_note(vault / "Empty FM.md", vault_root=vault)
        assert note["title"] == "Empty FM"

    def test_relative_path(self, vault: Path):
        note = parse_note(
            vault / "subfolder" / "Deep Note.md", vault_root=vault,
        )
        assert note["path"] == "subfolder/Deep Note.md"

    def test_modified_at_is_iso(self, vault: Path):
        note = parse_note(vault / "Project.md", vault_root=vault)
        assert "T" in note["modified_at"]  # ISO format

    def test_comma_separated_tags_in_frontmatter(self, vault: Path):
        note = parse_note(
            vault / "subfolder" / "Deep Note.md", vault_root=vault,
        )
        assert "deep" in note["tags"]
        assert "nested" in note["tags"]


# ── search_notes ──────────────────────────────────────────────


class TestSearchNotes:
    def test_title_match_scores_higher(self, vault: Path):
        results = search_notes(vault, "Project")
        assert len(results) >= 1
        assert results[0]["title"] == "My Project"
        assert results[0]["score"] > 0

    def test_body_match(self, vault: Path):
        results = search_notes(vault, "subfolder")
        assert len(results) >= 1

    def test_no_results(self, vault: Path):
        results = search_notes(vault, "xyznonexistent")
        assert results == []

    def test_limit(self, vault: Path):
        results = search_notes(vault, "note", limit=2)
        assert len(results) <= 2

    def test_tag_filter(self, vault: Path):
        results = search_notes(vault, "note", tags=["project"])
        for r in results:
            assert "project" in r["tags"]

    def test_folder_filter(self, vault: Path):
        results = search_notes(vault, "Deep", folder="subfolder")
        assert len(results) >= 1
        assert all("subfolder" in r["path"] for r in results)

    def test_hidden_dirs_excluded(self, vault: Path):
        results = search_notes(vault, "config")
        paths = [r["path"] for r in results]
        assert not any(".obsidian" in p for p in paths)


# ── list_notes ────────────────────────────────────────────────


class TestListNotes:
    def test_lists_all(self, vault: Path):
        notes = list_notes(vault)
        # Should find all non-hidden notes
        assert len(notes) >= 4

    def test_folder_filter(self, vault: Path):
        notes = list_notes(vault, folder="subfolder")
        assert len(notes) == 1
        assert notes[0]["title"] == "Deep Note"

    def test_tag_filter(self, vault: Path):
        notes = list_notes(vault, tags=["shopai"])
        assert all("shopai" in n["tags"] for n in notes)

    def test_limit(self, vault: Path):
        notes = list_notes(vault, limit=2)
        assert len(notes) <= 2

    def test_hidden_excluded(self, vault: Path):
        notes = list_notes(vault)
        paths = [n["path"] for n in notes]
        assert not any(".obsidian" in p for p in paths)


# ── write_note ────────────────────────────────────────────────


class TestWriteNote:
    def test_creates_file(self, tmp_path: Path):
        written = write_note(
            tmp_path, "Test Note", "Hello world",
            frontmatter={"tags": ["test"]},
        )
        assert written.exists()
        assert written.name == "Test-Note.md"
        content = written.read_text(encoding="utf-8")
        assert "---" in content
        assert "Hello world" in content
        assert "tags:" in content

    def test_subfolder_created(self, tmp_path: Path):
        written = write_note(
            tmp_path, "Sub Note", "Content",
            folder="ShopAI/Learned",
        )
        assert written.exists()
        # Path uses ``\`` on Windows, ``/`` on POSIX — compare via
        # ``as_posix()`` so the substring assertion is OS-agnostic.
        assert "ShopAI/Learned" in written.as_posix()

    def test_frontmatter_defaults(self, tmp_path: Path):
        written = write_note(tmp_path, "Defaults", "Body")
        content = written.read_text(encoding="utf-8")
        assert "title: Defaults" in content
        assert "created_at:" in content

    def test_roundtrip(self, tmp_path: Path):
        write_note(
            tmp_path, "Round Trip", "Body text here",
            frontmatter={"tags": ["rt"], "custom": "value"},
        )
        note = parse_note(tmp_path / "Round-Trip.md", vault_root=tmp_path)
        assert note["title"] == "Round Trip"
        assert "rt" in note["tags"]
        assert note["frontmatter"]["custom"] == "value"
        assert "Body text here" in note["body"]


# ── _sanitise_filename ────────────────────────────────────────


class TestSanitiseFilename:
    def test_basic(self):
        assert _sanitise_filename("Hello World") == "Hello-World"

    def test_special_chars(self):
        result = _sanitise_filename('File: "name" <test>')
        assert ":" not in result
        assert '"' not in result
        assert "<" not in result
        assert ">" not in result

    def test_empty(self):
        assert _sanitise_filename("") == "untitled"

    def test_whitespace_only(self):
        assert _sanitise_filename("   ") == "untitled"
