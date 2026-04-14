"""Feedback-driven learning — Option P.

Exercises ``core.learning.feedback_learner.FeedbackLearner``: the
module that reads down-rated chat feedback notes from the Obsidian
vault, clusters recurring complaint themes, and promotes each one to
a lesson note under ``ShopAI/Learned/lessons/``.

Coverage:

* tokeniser / stopword filter
* rating + operator-note parsing
* theme clustering with min-occurrences floor
* lesson emission (new + idempotent re-run)
* source-list merging across runs
* missing-vault / empty-feedback resilience
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.learning.feedback_learner import (
    FeedbackLearner,
    LearnReport,
    learn_from_feedback,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _write_feedback(
    fb_dir: Path,
    name: str,
    rating: str,
    op_note: str = "",
) -> Path:
    body = (
        "---\n"
        f"title: {name}\n"
        "tags: [chat-feedback]\n"
        f"rating: {rating}\n"
        "---\n\n"
        "## User message\n\n"
        "```\n"
        "what happened?\n"
        "```\n\n"
        "## Operator note\n\n"
        f"{op_note}\n"
    )
    p = fb_dir / f"{name}.md"
    p.write_text(body, encoding="utf-8")
    return p


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "ShopAI" / "Feedback").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def feedback_dir(vault):
    return vault / "ShopAI" / "Feedback"


# ---------------------------------------------------------------------------
# tokeniser + parsers
# ---------------------------------------------------------------------------


class TestParsers:
    def test_tokenise_drops_stopwords(self):
        toks = FeedbackLearner._tokenise("this refund with problem")
        assert "this" not in toks
        assert "with" not in toks
        assert "refund" in toks and "problem" in toks

    def test_tokenise_drops_short(self):
        assert FeedbackLearner._tokenise("a an is of") == []

    def test_tokenise_lowercases(self):
        assert FeedbackLearner._tokenise("Refund REFUND") == ["refund", "refund"]

    def test_rating_up(self):
        body = "---\nrating: up\n---"
        assert FeedbackLearner._rating(body) == "up"

    def test_rating_down(self):
        body = "---\nrating: down\n---"
        assert FeedbackLearner._rating(body) == "down"

    def test_rating_missing(self):
        assert FeedbackLearner._rating("---\ntitle: x\n---") == ""

    def test_operator_note_extracted(self):
        body = "## Operator note\n\nrefund is broken\n"
        assert "refund is broken" in FeedbackLearner._operator_note(body)

    def test_operator_note_fallback_to_body(self):
        """No marker → return the whole body so we don't silently miss
        a feedback note that didn't follow the convention."""
        body = "loose text, no heading"
        assert "loose text" in FeedbackLearner._operator_note(body)

    def test_slugify_ascii(self):
        assert FeedbackLearner._slugify("Refund") == "refund"

    def test_slugify_strips_punctuation(self):
        assert FeedbackLearner._slugify("re-fund!") == "re-fund"


# ---------------------------------------------------------------------------
# full run — end-to-end
# ---------------------------------------------------------------------------


class TestLearnerRun:
    def test_missing_feedback_dir_returns_empty(self, tmp_path):
        # No ShopAI/Feedback at all.
        report = FeedbackLearner(tmp_path).run()
        assert isinstance(report, LearnReport)
        assert report.scanned == 0
        assert report.down_rated == 0
        assert report.themes_found == 0
        assert report.lessons_written == 0

    def test_ignores_up_rated_notes(self, vault, feedback_dir):
        _write_feedback(feedback_dir, "u1", "up", op_note="refund great")
        _write_feedback(feedback_dir, "u2", "up", op_note="refund great")
        report = FeedbackLearner(vault).run()
        assert report.scanned == 2
        assert report.down_rated == 0
        assert report.themes_found == 0
        # No lesson file should exist.
        lessons = (vault / "ShopAI" / "Learned" / "lessons")
        assert not lessons.exists() or not any(lessons.iterdir())

    def test_singleton_theme_not_promoted(self, vault, feedback_dir):
        _write_feedback(feedback_dir, "d1", "down",
                        op_note="xyzzy appeared once")
        report = FeedbackLearner(vault).run(min_occurrences=2)
        assert report.down_rated == 1
        assert report.themes_found == 0
        assert report.lessons_written == 0

    def test_recurring_theme_promoted(self, vault, feedback_dir):
        _write_feedback(feedback_dir, "d1", "down",
                        op_note="refund logic wrong")
        _write_feedback(feedback_dir, "d2", "down",
                        op_note="refund amount incorrect")
        _write_feedback(feedback_dir, "d3", "down",
                        op_note="refund delayed again")
        report = FeedbackLearner(vault).run(min_occurrences=2)
        assert report.down_rated == 3
        assert report.lessons_written >= 1
        # The theme "refund" must exist as a lesson file.
        lesson = vault / "ShopAI" / "Learned" / "lessons" / "lesson-refund.md"
        assert lesson.exists()
        content = lesson.read_text(encoding="utf-8")
        assert "theme: refund" in content
        assert "source_count: 3" in content
        # Frontmatter must link back to every source.
        assert "d1.md" in content
        assert "d2.md" in content
        assert "d3.md" in content

    def test_higher_floor_suppresses_theme(self, vault, feedback_dir):
        _write_feedback(feedback_dir, "d1", "down", op_note="refund bad")
        _write_feedback(feedback_dir, "d2", "down", op_note="refund bad")
        report = FeedbackLearner(vault).run(min_occurrences=5)
        assert report.down_rated == 2
        assert report.themes_found == 0

    def test_idempotent_merges_sources(self, vault, feedback_dir):
        """Re-running adds new sources without dropping old ones."""
        _write_feedback(feedback_dir, "d1", "down", op_note="refund bad")
        _write_feedback(feedback_dir, "d2", "down", op_note="refund bad")
        FeedbackLearner(vault).run()
        lesson = vault / "ShopAI" / "Learned" / "lessons" / "lesson-refund.md"
        first = lesson.read_text(encoding="utf-8")
        assert "d1.md" in first and "d2.md" in first

        # Add a third note and re-run.
        _write_feedback(feedback_dir, "d3", "down", op_note="refund bad")
        FeedbackLearner(vault).run()
        second = lesson.read_text(encoding="utf-8")
        assert "d1.md" in second
        assert "d2.md" in second
        assert "d3.md" in second
        assert "source_count: 3" in second

    def test_unreadable_file_reported_not_raised(self, vault, feedback_dir,
                                                  monkeypatch):
        _write_feedback(feedback_dir, "d1", "down", op_note="refund bad")
        # Simulate a read failure on exactly one file.
        orig_read = Path.read_text

        def flaky_read(self, *a, **k):
            if self.name == "d1.md":
                raise OSError("permission denied")
            return orig_read(self, *a, **k)

        monkeypatch.setattr(Path, "read_text", flaky_read)
        report = FeedbackLearner(vault).run()
        assert any("d1.md" in e for e in report.errors)
        # Report still returns — never raises.

    def test_wrapper_function(self, vault, feedback_dir):
        _write_feedback(feedback_dir, "d1", "down", op_note="refund broken")
        _write_feedback(feedback_dir, "d2", "down", op_note="refund broken")
        report = learn_from_feedback(vault)
        assert isinstance(report, LearnReport)
        assert report.lessons_written >= 1


# ---------------------------------------------------------------------------
# report shape
# ---------------------------------------------------------------------------


class TestReport:
    def test_as_dict_serialisable(self, vault, feedback_dir):
        _write_feedback(feedback_dir, "d1", "down", op_note="refund bad")
        _write_feedback(feedback_dir, "d2", "down", op_note="refund bad")
        report = FeedbackLearner(vault).run()
        d = report.as_dict()
        assert set(d.keys()) == {
            "scanned", "down_rated", "themes_found",
            "lessons_written", "lessons_skipped", "errors",
        }
        # Numeric fields must be ints so JSON-encoding downstream
        # doesn't need type coercion.
        for k in ("scanned", "down_rated", "themes_found",
                  "lessons_written", "lessons_skipped"):
            assert isinstance(d[k], int)
