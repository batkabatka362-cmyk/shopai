"""Dashboard lessons endpoint + chat injection — Option P.

Covers the two dashboard-facing pieces of the feedback-driven learning
loop:

* ``GET /api/lessons`` — reads ``vault/ShopAI/Learned/lessons/*.md``
  and returns a well-formed payload the Feedback tab can render.
* ``_retrieve_relevant_lessons`` — the chat-pipeline helper that pulls
  matching lessons into the system prompt when a user message mentions
  a theme word.

The feedback learner itself (the writer) is covered by
``tests/test_feedback_learner.py``; here we only exercise the read
side + injection plumbing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from dashboard.app import (
    DashboardAPIHandler,
    _collect_lessons_snapshot,
    _parse_lesson_frontmatter,
)


def _handler() -> DashboardAPIHandler:
    h = object.__new__(DashboardAPIHandler)
    h._captured = []
    h._json = lambda status, data: h._captured.append((status, data))
    h.path = "/api/lessons"
    return h


def _write_lesson(lessons_dir: Path, theme: str, *, source_count: int = 2,
                  sources: list[str] | None = None) -> Path:
    sources = sources or [
        f"ShopAI/Feedback/d{i}.md" for i in range(1, source_count + 1)
    ]
    bullets = "\n".join(f'  - "{s}"' for s in sources)
    body = (
        "---\n"
        f"title: Lesson — {theme}\n"
        f"theme: {theme}\n"
        "tags: [learned, feedback-driven]\n"
        "updated: 2026-04-14 00:00:00\n"
        f"source_count: {source_count}\n"
        "sources:\n"
        f"{bullets}\n"
        "---\n\n"
        f"# Lesson: {theme}\n\nbody text\n"
    )
    p = lessons_dir / f"lesson-{theme}.md"
    p.write_text(body, encoding="utf-8")
    return p


@pytest.fixture
def temp_vault(tmp_path, monkeypatch):
    (tmp_path / "ShopAI" / "Learned" / "lessons").mkdir(parents=True)
    monkeypatch.setattr(
        "core.adapters.config.get_config",
        lambda: {"obsidian_vault_path": str(tmp_path)},
    )
    return tmp_path


@pytest.fixture
def lessons_dir(temp_vault):
    return temp_vault / "ShopAI" / "Learned" / "lessons"


# ---------------------------------------------------------------------------
# _parse_lesson_frontmatter
# ---------------------------------------------------------------------------


class TestFrontmatterParser:
    def test_parses_all_fields(self):
        body = (
            "---\n"
            "theme: refund\n"
            "source_count: 3\n"
            "updated: 2026-04-14 00:00:00\n"
            "sources:\n"
            '  - "ShopAI/Feedback/a.md"\n'
            '  - "ShopAI/Feedback/b.md"\n'
            "---\n\nbody\n"
        )
        meta = _parse_lesson_frontmatter(body)
        assert meta["theme"] == "refund"
        assert meta["source_count"] == 3
        assert "ShopAI/Feedback/a.md" in meta["sources"]
        assert "ShopAI/Feedback/b.md" in meta["sources"]

    def test_missing_frontmatter_returns_defaults(self):
        meta = _parse_lesson_frontmatter("no frontmatter here")
        assert meta["theme"] == ""
        assert meta["source_count"] == 0
        assert meta["sources"] == []

    def test_bad_source_count_safe(self):
        body = "---\ntheme: x\nsource_count: not-a-number\n---\n"
        meta = _parse_lesson_frontmatter(body)
        assert meta["source_count"] == 0


# ---------------------------------------------------------------------------
# _collect_lessons_snapshot
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_empty_lessons_dir(self, temp_vault):
        snap = _collect_lessons_snapshot()
        assert snap["configured"] is True
        assert snap["count"] == 0
        assert snap["lessons"] == []

    def test_missing_lessons_dir(self, tmp_path, monkeypatch):
        # Vault exists but no Learned/lessons subtree.
        monkeypatch.setattr(
            "core.adapters.config.get_config",
            lambda: {"obsidian_vault_path": str(tmp_path)},
        )
        snap = _collect_lessons_snapshot()
        assert snap["configured"] is True
        assert snap["count"] == 0

    def test_lists_lessons_with_metadata(self, temp_vault, lessons_dir):
        _write_lesson(lessons_dir, "refund", source_count=3)
        _write_lesson(lessons_dir, "shipping", source_count=2)

        snap = _collect_lessons_snapshot()
        assert snap["count"] == 2
        themes = {l["theme"] for l in snap["lessons"]}
        assert themes == {"refund", "shipping"}
        for lesson in snap["lessons"]:
            assert lesson["path"].startswith("ShopAI/Learned/lessons/")
            assert lesson["source_count"] >= 2

    def test_lessons_sorted_by_source_count_desc(self, temp_vault, lessons_dir):
        _write_lesson(lessons_dir, "shipping", source_count=2)
        _write_lesson(lessons_dir, "refund", source_count=5)
        _write_lesson(lessons_dir, "promo", source_count=3)

        snap = _collect_lessons_snapshot()
        themes = [l["theme"] for l in snap["lessons"]]
        assert themes == ["refund", "promo", "shipping"]

    def test_limit_parameter(self, temp_vault, lessons_dir):
        for i, theme in enumerate(("a", "b", "c", "d")):
            _write_lesson(lessons_dir, theme, source_count=2 + i)
        snap = _collect_lessons_snapshot(limit=2)
        assert len(snap["lessons"]) == 2
        assert snap["count"] == 2


# ---------------------------------------------------------------------------
# _api_lessons endpoint
# ---------------------------------------------------------------------------


class TestLessonsEndpoint:
    def test_unconfigured_vault(self, monkeypatch):
        monkeypatch.setattr(
            "core.adapters.config.get_config",
            lambda: {"obsidian_vault_path": ""},
        )
        h = _handler()
        h._api_lessons()
        status, payload = h._captured[0]
        assert status == 200
        assert payload["configured"] is False
        assert payload["count"] == 0

    def test_populated_endpoint(self, temp_vault, lessons_dir):
        _write_lesson(lessons_dir, "refund", source_count=3)
        h = _handler()
        h._api_lessons()
        status, payload = h._captured[0]
        assert status == 200
        assert payload["configured"] is True
        assert payload["count"] == 1
        assert payload["lessons"][0]["theme"] == "refund"

    def test_collector_exception_contained(self, monkeypatch):
        def boom():
            raise RuntimeError("disk on fire")
        monkeypatch.setattr(
            "dashboard.app._collect_lessons_snapshot", boom,
        )
        monkeypatch.setattr(
            "core.adapters.config.get_config",
            lambda: {"obsidian_vault_path": "/tmp"},
        )
        h = _handler()
        h._api_lessons()
        status, payload = h._captured[0]
        assert status == 200
        assert "disk on fire" in payload.get("error", "")


# ---------------------------------------------------------------------------
# _retrieve_relevant_lessons — chat injection
# ---------------------------------------------------------------------------


class TestChatInjection:
    def _h(self):
        return object.__new__(DashboardAPIHandler)

    def test_returns_empty_on_empty_message(self, temp_vault):
        out = self._h()._retrieve_relevant_lessons("")
        assert out == []

    def test_returns_empty_when_vault_unset(self, monkeypatch):
        monkeypatch.setattr(
            "core.adapters.config.get_config",
            lambda: {"obsidian_vault_path": ""},
        )
        out = self._h()._retrieve_relevant_lessons("how do refunds work?")
        assert out == []

    def test_returns_empty_when_lessons_dir_missing(self, tmp_path,
                                                     monkeypatch):
        monkeypatch.setattr(
            "core.adapters.config.get_config",
            lambda: {"obsidian_vault_path": str(tmp_path)},
        )
        out = self._h()._retrieve_relevant_lessons("how do refunds work?")
        assert out == []

    def test_matches_theme_in_message(self, temp_vault, lessons_dir):
        _write_lesson(lessons_dir, "refund", source_count=3)
        out = self._h()._retrieve_relevant_lessons("why is the refund slow?")
        assert len(out) == 1
        theme, summary = out[0]
        assert theme == "refund"
        assert "3" in summary  # source_count surfaces in summary

    def test_skips_non_matching_lessons(self, temp_vault, lessons_dir):
        _write_lesson(lessons_dir, "refund", source_count=2)
        _write_lesson(lessons_dir, "shipping", source_count=2)
        out = self._h()._retrieve_relevant_lessons("how do I cancel an order?")
        assert out == []

    def test_case_insensitive_match(self, temp_vault, lessons_dir):
        _write_lesson(lessons_dir, "refund", source_count=2)
        out = self._h()._retrieve_relevant_lessons("My REFUND is late!")
        assert len(out) == 1

    def test_caps_at_max_lessons(self, temp_vault, lessons_dir):
        # More than _CHAT_MAX_LESSONS (3) matching themes
        for theme in ("refund", "shipping", "promo", "discount"):
            _write_lesson(lessons_dir, theme, source_count=2)
        msg = "issues with refund shipping promo discount everything"
        out = self._h()._retrieve_relevant_lessons(msg)
        assert len(out) == 3

    def test_lesson_summary_uses_source_count(self, temp_vault, lessons_dir):
        _write_lesson(lessons_dir, "refund", source_count=7)
        out = self._h()._retrieve_relevant_lessons("refund help")
        _, summary = out[0]
        assert "7" in summary

    def test_survives_malformed_lesson(self, temp_vault, lessons_dir):
        # One valid lesson and one malformed file.
        _write_lesson(lessons_dir, "refund", source_count=2)
        (lessons_dir / "lesson-broken.md").write_text(
            "not even frontmatter", encoding="utf-8",
        )
        out = self._h()._retrieve_relevant_lessons("refund")
        # Valid lesson still surfaces; malformed one is skipped silently.
        assert any(t == "refund" for t, _ in out)


# ---------------------------------------------------------------------------
# system prompt injection — integration
# ---------------------------------------------------------------------------


class TestSystemPromptInjection:
    def test_prompt_includes_lesson_block(self, temp_vault, lessons_dir,
                                           monkeypatch):
        _write_lesson(lessons_dir, "refund", source_count=4)
        h = object.__new__(DashboardAPIHandler)
        # Stub the context collector so we don't need a live registry.
        h._build_chat_context = lambda: {
            "adapters_configured": 1, "adapters_total": 1,
            "adapters_categories": 1, "system_status": "ok",
            "cycle_summary": "", "vault_summary": "",
        }
        prompt = h._build_system_prompt(user_message="why is the refund late?")
        assert "LESSONS FROM PAST FEEDBACK" in prompt
        assert "refund" in prompt
        assert "4" in prompt  # source count

    def test_prompt_omits_block_when_no_match(self, temp_vault, lessons_dir):
        _write_lesson(lessons_dir, "refund", source_count=2)
        h = object.__new__(DashboardAPIHandler)
        h._build_chat_context = lambda: {
            "adapters_configured": 1, "adapters_total": 1,
            "adapters_categories": 1, "system_status": "ok",
            "cycle_summary": "", "vault_summary": "",
        }
        prompt = h._build_system_prompt(user_message="how are things going?")
        assert "LESSONS FROM PAST FEEDBACK" not in prompt
