"""Tests for ``shopai knowledge set-notes`` — operator can update
operator notes directly from the terminal without going through
the export → edit-in-vault → import roundtrip.

Notes persist to ``data/operator_notes.json`` (via NotesStore).
Downstream consumers (digest, knowledge export enrichment,
action review) read the same file, so a quickly-typed CLI note
shows up everywhere with no extra step.
"""
from __future__ import annotations

import argparse
import importlib.util
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
def isolated_store(tmp_path: Path, monkeypatch):
    """Each test gets a fresh NotesStore pointed at a tmp file —
    no pollution of data/operator_notes.json."""
    from core.knowledge.notes_store import NotesStore

    store_path = tmp_path / "notes.json"
    fresh = NotesStore(path=store_path)
    monkeypatch.setattr(
        "core.knowledge.get_default_store",
        lambda: fresh,
    )
    yield fresh


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


def _ns(**kwargs):
    return argparse.Namespace(**kwargs)


# ─── happy paths ──────────────────────────────────────────────────


class TestSetNotes:

    def test_engine_inline_text(self, cli, isolated_store):
        out, code = _capture(
            cli._cmd_knowledge_set_notes,
            _ns(
                kind="engine", name="cart_recovery",
                text="Deprioritize in winter — high return rate",
                from_file=None,
            ),
        )
        assert code == 0
        assert "Saved engine note for 'cart_recovery'" in out
        # Note is readable through the same store
        assert "winter" in isolated_store.get_engine_notes("cart_recovery")

    def test_goal_inline_text(self, cli, isolated_store):
        out, code = _capture(
            cli._cmd_knowledge_set_notes,
            _ns(
                kind="goal", name="grow_customers",
                text="Focus on retention until Q3",
                from_file=None,
            ),
        )
        assert code == 0
        assert isolated_store.get_goal_notes("grow_customers")

    def test_from_file(self, cli, isolated_store, tmp_path):
        note_file = tmp_path / "note.md"
        note_file.write_text(
            "# Bulk import\n\nFull markdown body here.",
            encoding="utf-8",
        )
        out, code = _capture(
            cli._cmd_knowledge_set_notes,
            _ns(
                kind="engine", name="loyalty",
                text=None,
                from_file=str(note_file),
            ),
        )
        assert code == 0
        body = isolated_store.get_engine_notes("loyalty")
        assert "Bulk import" in body
        assert "markdown body" in body

    def test_text_dash_reads_stdin(self, cli, isolated_store):
        """``--text -`` reads from stdin — supports piping
        (``echo 'note' | shopai knowledge set-notes ...``)."""
        with patch(
            "sys.stdin",
            StringIO("Piped note body"),
        ):
            out, code = _capture(
                cli._cmd_knowledge_set_notes,
                _ns(
                    kind="engine", name="loyalty",
                    text="-",
                    from_file=None,
                ),
            )
        assert code == 0
        assert "Piped note body" in isolated_store.get_engine_notes("loyalty")

    def test_overwrites_existing(self, cli, isolated_store):
        """A second set replaces the first — last-write-wins."""
        isolated_store.set_engine_notes(
            "cart_recovery", "old note", source_path="test",
        )
        _capture(
            cli._cmd_knowledge_set_notes,
            _ns(
                kind="engine", name="cart_recovery",
                text="new note",
                from_file=None,
            ),
        )
        assert isolated_store.get_engine_notes("cart_recovery") == "new note"


# ─── validation ───────────────────────────────────────────────────


class TestValidation:

    def test_empty_name_rejected(self, cli, isolated_store):
        out, code = _capture(
            cli._cmd_knowledge_set_notes,
            _ns(
                kind="engine", name="",
                text="body",
                from_file=None,
            ),
        )
        assert code == 1
        assert "name is required" in out

    def test_empty_body_rejected(self, cli, isolated_store):
        out, code = _capture(
            cli._cmd_knowledge_set_notes,
            _ns(
                kind="engine", name="x",
                text="   ",
                from_file=None,
            ),
        )
        assert code == 1
        assert "empty" in out

    def test_missing_file_exits_1(self, cli, isolated_store, tmp_path):
        out, code = _capture(
            cli._cmd_knowledge_set_notes,
            _ns(
                kind="engine", name="x",
                text=None,
                from_file=str(tmp_path / "nonexistent.md"),
            ),
        )
        assert code == 1
        assert "could not read" in out


# ─── dispatcher routes verb ───────────────────────────────────────


class TestKnowledgeDispatcher:

    def test_set_notes_routed(self, cli):
        """Bare ``shopai knowledge`` shows usage that includes the
        new verb."""
        out, code = _capture(
            cli._cmd_knowledge,
            _ns(knowledge_action=None),
        )
        assert code == 1
        assert "set-notes" in out
