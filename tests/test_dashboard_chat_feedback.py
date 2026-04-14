"""Dashboard chat feedback — Option H.

Exercises the thumbs-up/down → Obsidian vault pipeline:

* ``_handle_chat_feedback`` validates the body shape, rejects non-up/down
  ratings and missing response text, and accepts feedback even when the
  vault isn't configured (so upstream stats can still land).
* ``_write_feedback_note`` writes a well-formed Markdown note with
  Obsidian frontmatter + wikilinks into ``vault/ShopAI/Feedback/``.
* ``_sanitise_feedback_snippet`` clips + strips NULs so a crafted
  transcript can't blow up the vault.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from dashboard.app import (
    DashboardAPIHandler,
    _VaultNotConfigured,
    _sanitise_feedback_snippet,
    _vault_root,
    _write_feedback_note,
)


def _handler() -> DashboardAPIHandler:
    h = object.__new__(DashboardAPIHandler)
    h._captured = []
    h._json = lambda status, data: h._captured.append((status, data))
    return h


@pytest.fixture
def temp_vault(tmp_path, monkeypatch):
    """Point the config at a fresh temp directory for each test."""
    monkeypatch.setattr(
        "core.adapters.config.get_config",
        lambda: {"obsidian_vault_path": str(tmp_path)},
    )
    return tmp_path


# ---------------------------------------------------------------------------
# _sanitise_feedback_snippet
# ---------------------------------------------------------------------------


class TestSanitise:
    def test_strips_nul_bytes(self):
        out = _sanitise_feedback_snippet("hello\x00world")
        assert "\x00" not in out
        assert "hello" in out and "world" in out

    def test_clips_to_limit(self):
        out = _sanitise_feedback_snippet("x" * 5000, limit=100)
        assert len(out) == 100

    def test_empty_passthrough(self):
        assert _sanitise_feedback_snippet("") == ""
        assert _sanitise_feedback_snippet(None) == ""


# ---------------------------------------------------------------------------
# _vault_root
# ---------------------------------------------------------------------------


class TestVaultRoot:
    def test_missing_config_raises(self, monkeypatch):
        monkeypatch.setattr(
            "core.adapters.config.get_config",
            lambda: {"obsidian_vault_path": ""},
        )
        with pytest.raises(_VaultNotConfigured):
            _vault_root()

    def test_bad_path_raises(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "core.adapters.config.get_config",
            lambda: {"obsidian_vault_path": str(tmp_path / "nope")},
        )
        with pytest.raises(_VaultNotConfigured):
            _vault_root()

    def test_valid_path_returns(self, temp_vault):
        assert _vault_root() == temp_vault


# ---------------------------------------------------------------------------
# _write_feedback_note
# ---------------------------------------------------------------------------


class TestWriteFeedbackNote:
    def test_creates_feedback_folder(self, temp_vault):
        _write_feedback_note(
            rating="up", message="hi", response="there", note="",
        )
        folder = temp_vault / "ShopAI" / "Feedback"
        assert folder.is_dir()
        files = list(folder.glob("*.md"))
        assert len(files) == 1

    def test_up_rating_links_to_wins(self, temp_vault):
        path = _write_feedback_note(
            rating="up", message="msg", response="rsp", note="",
        )
        content = path.read_text(encoding="utf-8")
        assert "[[Wins]]" in content
        assert "rating: up" in content
        assert "tags: [feedback, chat, good]" in content

    def test_down_rating_links_to_errors(self, temp_vault):
        path = _write_feedback_note(
            rating="down", message="msg", response="rsp", note="wrong",
        )
        content = path.read_text(encoding="utf-8")
        assert "[[Errors]]" in content
        assert "tags: [feedback, chat, bad]" in content
        assert "wrong" in content  # operator note included

    def test_note_section_omitted_when_empty(self, temp_vault):
        path = _write_feedback_note(
            rating="up", message="m", response="r", note="",
        )
        content = path.read_text(encoding="utf-8")
        assert "Operator note" not in content

    def test_filename_has_timestamp_and_rating(self, temp_vault):
        path = _write_feedback_note(
            rating="up", message="m", response="r", note="",
        )
        assert path.name.endswith("-up.md")
        # Filesystem-safe timestamp — no colons.
        assert ":" not in path.name

    def test_response_content_preserved(self, temp_vault):
        path = _write_feedback_note(
            rating="up", message="hello",
            response="the latest cycle had 3 errors", note="",
        )
        content = path.read_text(encoding="utf-8")
        assert "hello" in content
        assert "the latest cycle had 3 errors" in content


# ---------------------------------------------------------------------------
# _handle_chat_feedback endpoint
# ---------------------------------------------------------------------------


class TestHandleChatFeedback:
    def test_rejects_missing_rating(self):
        h = _handler()
        h._handle_chat_feedback({"response": "x"})
        status, data = h._captured[-1]
        assert status == 400
        assert "rating" in data["error"]

    def test_rejects_invalid_rating(self):
        h = _handler()
        h._handle_chat_feedback({"rating": "maybe", "response": "x"})
        status, _ = h._captured[-1]
        assert status == 400

    def test_rejects_missing_response(self):
        h = _handler()
        h._handle_chat_feedback({"rating": "up", "response": ""})
        status, data = h._captured[-1]
        assert status == 400
        assert "response" in data["error"]

    def test_accepts_when_vault_unconfigured(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr(
            "core.adapters.config.get_config",
            lambda: {"obsidian_vault_path": ""},
        )
        h._handle_chat_feedback({
            "rating": "down",
            "message": "hi",
            "response": "oops",
        })
        status, data = h._captured[-1]
        assert status == 200
        assert data["status"] == "accepted"
        assert data["persisted"] is False

    def test_persists_when_configured(self, temp_vault):
        h = _handler()
        h._handle_chat_feedback({
            "rating": "up",
            "message": "thanks",
            "response": "you're welcome",
            "note": "",
        })
        status, data = h._captured[-1]
        assert status == 200
        assert data["status"] == "ok"
        assert data["persisted"] is True
        path = Path(data["path"])
        assert path.exists()
        assert "thanks" in path.read_text(encoding="utf-8")

    def test_normalises_whitespace(self, temp_vault):
        h = _handler()
        h._handle_chat_feedback({
            "rating": "  Up  ",
            "message": "m", "response": "r",
        })
        status, data = h._captured[-1]
        assert status == 200
        assert data["status"] == "ok"

    def test_fails_soft_on_write_error(self, temp_vault, monkeypatch):
        h = _handler()

        def _boom(**kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr(
            "dashboard.app._write_feedback_note", _boom,
        )
        h._handle_chat_feedback({
            "rating": "up", "message": "m", "response": "r",
        })
        status, data = h._captured[-1]
        # Never 500 — always graceful.
        assert status == 200
        assert data["persisted"] is False
        assert "disk full" in data["error"]
