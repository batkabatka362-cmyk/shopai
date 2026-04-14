"""Dashboard feedback review — Option O.

Exercises ``GET /api/feedback`` and its underlying collector. The
endpoint rolls up ``vault/ShopAI/Feedback/*.md`` notes written by
Option H (chat thumbs up/down) into per-rating counts, a recent list
with excerpts, and a "common complaint themes" word histogram.

Coverage:

* ``_feedback_rating_from_body`` — frontmatter rating parser
* ``_feedback_excerpt`` — user-message excerpt extractor
* ``_feedback_operator_note`` — operator-note section extractor
* ``_tokenise_feedback`` — stopword-filtered tokeniser
* ``_collect_feedback_snapshot`` — full aggregation
* ``_api_feedback`` — HTTP envelope (missing vault, errors, success)
"""
from __future__ import annotations

import pytest

from dashboard.app import (
    DashboardAPIHandler,
    _collect_feedback_snapshot,
    _feedback_excerpt,
    _feedback_operator_note,
    _feedback_rating_from_body,
    _tokenise_feedback,
)


# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------


def _handler(query: str = "") -> DashboardAPIHandler:
    h = object.__new__(DashboardAPIHandler)
    h._captured = []
    h._json = lambda status, data: h._captured.append((status, data))
    h.path = "/api/feedback" + (("?" + query) if query else "")
    return h


def _write_feedback(fb_dir, name: str, rating: str, *,
                    user_msg: str = "what is 1+1", op_note: str = "") -> None:
    """Seed a single feedback note matching the shape produced by Option H."""
    body = (
        "---\n"
        f"title: {name}\n"
        "tags: [chat-feedback]\n"
        f"rating: {rating}\n"
        "---\n\n"
        "## User message\n\n"
        "```\n"
        f"{user_msg}\n"
        "```\n\n"
        "## Operator note\n\n"
        f"{op_note}\n"
    )
    (fb_dir / f"{name}.md").write_text(body, encoding="utf-8")


@pytest.fixture
def temp_vault(tmp_path, monkeypatch):
    fb_dir = tmp_path / "ShopAI" / "Feedback"
    fb_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "core.adapters.config.get_config",
        lambda: {"obsidian_vault_path": str(tmp_path)},
    )
    return tmp_path


@pytest.fixture
def empty_vault(tmp_path, monkeypatch):
    """Vault exists but no Feedback dir — collector must not crash."""
    monkeypatch.setattr(
        "core.adapters.config.get_config",
        lambda: {"obsidian_vault_path": str(tmp_path)},
    )
    return tmp_path


# ---------------------------------------------------------------------------
# _feedback_rating_from_body
# ---------------------------------------------------------------------------


class TestRatingParser:
    def test_parses_up(self):
        body = "---\ntitle: x\nrating: up\n---\n"
        assert _feedback_rating_from_body(body) == "up"

    def test_parses_down(self):
        body = "---\nrating: down\n---\nhello"
        assert _feedback_rating_from_body(body) == "down"

    def test_case_insensitive(self):
        body = "---\nRating: UP\n---\n"
        assert _feedback_rating_from_body(body) == "up"

    def test_unknown_rating_returns_empty(self):
        body = "---\nrating: maybe\n---\n"
        assert _feedback_rating_from_body(body) == ""

    def test_missing_rating_returns_empty(self):
        body = "---\ntitle: x\n---\n"
        assert _feedback_rating_from_body(body) == ""

    def test_ignores_rating_past_head(self):
        """Rating line buried deep in the body must not be picked up."""
        preamble = "\n".join(["filler"] * 40)
        body = f"---\ntitle: x\n---\n{preamble}\nrating: down\n"
        assert _feedback_rating_from_body(body) == ""


# ---------------------------------------------------------------------------
# _feedback_excerpt
# ---------------------------------------------------------------------------


class TestExcerpt:
    def test_pulls_user_message_fence(self):
        body = (
            "---\nrating: up\n---\n\n"
            "## User message\n\n"
            "```\n"
            "why did the order fail?\n"
            "```\n\n"
            "## Operator note\n\ntrash answer\n"
        )
        assert "why did the order fail" in _feedback_excerpt(body)

    def test_falls_back_to_first_line(self):
        # No ``## User message`` marker — excerpt falls back to the first
        # non-heading, non-fence line it sees.
        body = "plain body with no heading\n"
        assert _feedback_excerpt(body).startswith("plain body")

    def test_clips_to_160_chars(self):
        long = "a" * 500
        body = f"---\nrating: up\n---\n\n## User message\n\n```\n{long}\n```\n"
        assert len(_feedback_excerpt(body)) <= 160

    def test_empty_body(self):
        assert _feedback_excerpt("") == ""


# ---------------------------------------------------------------------------
# _feedback_operator_note
# ---------------------------------------------------------------------------


class TestOperatorNote:
    def test_returns_text_under_marker(self):
        body = "## Operator note\n\nthe answer was wrong about refunds"
        assert "wrong about refunds" in _feedback_operator_note(body)

    def test_missing_marker_returns_empty(self):
        assert _feedback_operator_note("no marker here") == ""


# ---------------------------------------------------------------------------
# _tokenise_feedback
# ---------------------------------------------------------------------------


class TestTokeniser:
    def test_drops_short_words(self):
        assert _tokenise_feedback("a an the of").count("the") == 0
        # Three-letter 'the' is in stopwords but also below the 4-char cutoff
        # anyway — just verify nothing short survives.
        toks = _tokenise_feedback("a an is of to be")
        assert toks == []

    def test_drops_stopwords(self):
        # "this" and "with" are stopwords
        toks = _tokenise_feedback("this refund with problem")
        assert "this" not in toks
        assert "with" not in toks
        assert "refund" in toks
        assert "problem" in toks

    def test_lowercases(self):
        toks = _tokenise_feedback("Refund REFUND refund")
        assert all(t == "refund" for t in toks)
        assert len(toks) == 3

    def test_skips_digits(self):
        toks = _tokenise_feedback("123 4567 refund")
        assert toks == ["refund"]

    def test_empty_returns_empty(self):
        assert _tokenise_feedback("") == []


# ---------------------------------------------------------------------------
# _collect_feedback_snapshot
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_missing_feedback_dir(self, empty_vault):
        snap = _collect_feedback_snapshot()
        assert snap["configured"] is True
        assert snap["total"] == 0
        assert snap["good"] == 0
        assert snap["bad"] == 0
        assert snap["good_rate"] == 0.0
        assert snap["recent"] == []
        assert snap["themes"] == []

    def test_counts_up_and_down(self, temp_vault):
        fb = temp_vault / "ShopAI" / "Feedback"
        _write_feedback(fb, "n1", "up")
        _write_feedback(fb, "n2", "up")
        _write_feedback(fb, "n3", "down")

        snap = _collect_feedback_snapshot()
        assert snap["good"] == 2
        assert snap["bad"] == 1
        assert snap["total"] == 3
        assert snap["good_rate"] == round(2 / 3, 4)

    def test_ignores_unrated_notes(self, temp_vault):
        fb = temp_vault / "ShopAI" / "Feedback"
        _write_feedback(fb, "n1", "up")
        # A note with no valid rating
        (fb / "junk.md").write_text(
            "---\ntitle: x\n---\n\nno rating line\n", encoding="utf-8",
        )
        snap = _collect_feedback_snapshot()
        assert snap["total"] == 1
        assert len(snap["recent"]) == 1

    def test_recent_list_shape(self, temp_vault):
        fb = temp_vault / "ShopAI" / "Feedback"
        _write_feedback(fb, "n1", "up", user_msg="how do refunds work")
        snap = _collect_feedback_snapshot()
        assert len(snap["recent"]) == 1
        item = snap["recent"][0]
        assert item["rating"] == "up"
        assert item["title"] == "n1"
        assert item["path"].startswith("ShopAI/Feedback")
        assert "refunds" in item["excerpt"]
        assert isinstance(item["mtime"], float)

    def test_recent_sorted_newest_first(self, temp_vault):
        import os
        import time
        fb = temp_vault / "ShopAI" / "Feedback"
        _write_feedback(fb, "older", "up")
        # Backdate
        older = fb / "older.md"
        os.utime(older, (time.time() - 3600, time.time() - 3600))
        _write_feedback(fb, "newer", "up")

        snap = _collect_feedback_snapshot()
        assert [r["title"] for r in snap["recent"]] == ["newer", "older"]

    def test_themes_include_recurring_words(self, temp_vault):
        fb = temp_vault / "ShopAI" / "Feedback"
        # Three distinct down notes all mentioning "refund" — must surface.
        _write_feedback(fb, "d1", "down",
                        op_note="refund logic wrong")
        _write_feedback(fb, "d2", "down",
                        op_note="refund amount incorrect")
        _write_feedback(fb, "d3", "down",
                        op_note="refund delayed again")

        snap = _collect_feedback_snapshot()
        theme_words = [t["word"] for t in snap["themes"]]
        assert "refund" in theme_words
        # "refund" must have count 3
        refund = [t for t in snap["themes"] if t["word"] == "refund"][0]
        assert refund["count"] == 3

    def test_themes_skip_singletons(self, temp_vault):
        fb = temp_vault / "ShopAI" / "Feedback"
        _write_feedback(fb, "d1", "down", op_note="xyzzy happened once")
        snap = _collect_feedback_snapshot()
        assert snap["themes"] == []  # count=1 filtered out

    def test_themes_only_from_down_ratings(self, temp_vault):
        fb = temp_vault / "ShopAI" / "Feedback"
        # Two "up" notes mentioning refund — must not leak into themes.
        _write_feedback(fb, "u1", "up", op_note="refund fine")
        _write_feedback(fb, "u2", "up", op_note="refund great")
        snap = _collect_feedback_snapshot()
        assert snap["themes"] == []

    def test_recent_honours_limit(self, temp_vault):
        fb = temp_vault / "ShopAI" / "Feedback"
        for i in range(5):
            _write_feedback(fb, f"n{i}", "up")
        snap = _collect_feedback_snapshot(limit=3)
        assert len(snap["recent"]) == 3
        assert snap["total"] == 5


# ---------------------------------------------------------------------------
# _api_feedback endpoint
# ---------------------------------------------------------------------------


class TestFeedbackEndpoint:
    def test_vault_unconfigured_returns_200_with_flag(self, monkeypatch):
        monkeypatch.setattr(
            "core.adapters.config.get_config",
            lambda: {"obsidian_vault_path": ""},
        )
        h = _handler()
        h._api_feedback()
        assert len(h._captured) == 1
        status, payload = h._captured[0]
        assert status == 200
        assert payload["configured"] is False
        assert payload["total"] == 0

    def test_empty_vault_success_envelope(self, empty_vault):
        h = _handler()
        h._api_feedback()
        status, payload = h._captured[0]
        assert status == 200
        assert payload["configured"] is True
        assert payload["total"] == 0
        assert payload["themes"] == []

    def test_populated_vault_returns_counts(self, temp_vault):
        fb = temp_vault / "ShopAI" / "Feedback"
        _write_feedback(fb, "n1", "up")
        _write_feedback(fb, "n2", "down", op_note="refund broken")
        _write_feedback(fb, "n3", "down", op_note="refund broken again")

        h = _handler()
        h._api_feedback()
        status, payload = h._captured[0]
        assert status == 200
        assert payload["good"] == 1
        assert payload["bad"] == 2
        assert len(payload["recent"]) == 3
        theme_words = [t["word"] for t in payload["themes"]]
        assert "refund" in theme_words

    def test_collector_exception_is_contained(self, monkeypatch):
        """A crash inside the collector must not 500 the endpoint."""
        def boom(*a, **k):
            raise RuntimeError("disk on fire")
        monkeypatch.setattr(
            "dashboard.app._collect_feedback_snapshot", boom,
        )
        # Also configure vault so we reach the collector call.
        monkeypatch.setattr(
            "core.adapters.config.get_config",
            lambda: {"obsidian_vault_path": "/tmp"},
        )
        h = _handler()
        h._api_feedback()
        status, payload = h._captured[0]
        assert status == 200
        assert "disk on fire" in payload.get("error", "")
