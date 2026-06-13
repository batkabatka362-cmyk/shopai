"""W963-177: discount_compat pagination tests.

W963-157's list_existing_discount_titles capped at the first
250 results -- established stores with 250+ codes would silently
miss codes beyond #250 in the dedup. W963-177 paginates with
a 10-page safety cap (2,500 codes).
"""
from __future__ import annotations

from unittest.mock import patch

from execution._discount_compat import (
    list_existing_discount_titles,
)


class FakeResult:
    def __init__(self, data, ok=True):
        self.ok = ok
        self.data = data


class TestPagination:
    def test_single_page_no_pagination(self, monkeypatch):
        """Small catalogue (<250 codes) returns in one call."""
        calls: list[dict] = []

        class FakeRouter:
            def execute(self_inner, cap, params):
                calls.append(dict(params))
                return FakeResult({
                    "discounts": [
                        {"title": "WELCOME15"},
                        {"title": "FREESHIP50"},
                    ],
                    "has_next_page": False,
                    "end_cursor": "",
                })

        monkeypatch.setattr(
            "core.adapters.get_router",
            lambda: FakeRouter(),
        )
        titles = list_existing_discount_titles()
        assert titles == {"WELCOME15", "FREESHIP50"}
        assert len(calls) == 1
        assert "cursor" not in calls[0]

    def test_multi_page_follows_cursor(self, monkeypatch):
        """Large catalogue (>250 codes) paginates through."""
        pages = [
            (
                [{"title": f"P1_{i}"} for i in range(250)],
                True, "cursor_2",
            ),
            (
                [{"title": f"P2_{i}"} for i in range(250)],
                True, "cursor_3",
            ),
            (
                [{"title": f"P3_{i}"} for i in range(50)],
                False, "",
            ),
        ]
        calls: list[dict] = []
        idx = {"n": 0}

        class FakeRouter:
            def execute(self_inner, cap, params):
                calls.append(dict(params))
                discounts, has_next, end_cursor = (
                    pages[idx["n"]]
                )
                idx["n"] += 1
                return FakeResult({
                    "discounts": discounts,
                    "has_next_page": has_next,
                    "end_cursor": end_cursor,
                })

        monkeypatch.setattr(
            "core.adapters.get_router",
            lambda: FakeRouter(),
        )
        titles = list_existing_discount_titles()
        # 250 + 250 + 50 = 550 codes paginated
        assert len(titles) == 550
        assert len(calls) == 3
        # First call no cursor; subsequent calls carry the prior end_cursor
        assert "cursor" not in calls[0]
        assert calls[1]["cursor"] == "cursor_2"
        assert calls[2]["cursor"] == "cursor_3"

    def test_pagination_capped_at_10_pages(self, monkeypatch):
        """Runaway safety cap: never more than 10 pages."""
        call_count = {"n": 0}

        class FakeRouter:
            def execute(self_inner, cap, params):
                call_count["n"] += 1
                return FakeResult({
                    "discounts": [
                        {"title": f"x{call_count['n']}"},
                    ],
                    "has_next_page": True,
                    "end_cursor": (
                        f"c{call_count['n']}"
                    ),
                })

        monkeypatch.setattr(
            "core.adapters.get_router",
            lambda: FakeRouter(),
        )
        titles = list_existing_discount_titles()
        # Hard cap: 10 pages max
        assert call_count["n"] == 10
        assert len(titles) == 10

    def test_router_failure_returns_partial(
        self, monkeypatch,
    ):
        """Partial results on transient failure are better
        than empty -- still useful for dedup."""
        pages = [
            (
                [{"title": "GOOD1"}],
                True, "cursor_2",
            ),
        ]
        idx = {"n": 0}

        class FakeRouter:
            def execute(self_inner, cap, params):
                if idx["n"] >= len(pages):
                    raise RuntimeError("transient failure")
                discounts, has_next, end_cursor = (
                    pages[idx["n"]]
                )
                idx["n"] += 1
                return FakeResult({
                    "discounts": discounts,
                    "has_next_page": has_next,
                    "end_cursor": end_cursor,
                })

        monkeypatch.setattr(
            "core.adapters.get_router",
            lambda: FakeRouter(),
        )
        titles = list_existing_discount_titles()
        # GOOD1 collected before failure
        assert titles == {"GOOD1"}

    def test_no_end_cursor_stops_pagination(
        self, monkeypatch,
    ):
        """If has_next_page=True but end_cursor empty, stop
        rather than infinite-loop."""
        call_count = {"n": 0}

        class FakeRouter:
            def execute(self_inner, cap, params):
                call_count["n"] += 1
                return FakeResult({
                    "discounts": [{"title": "X"}],
                    "has_next_page": True,
                    "end_cursor": "",  # Empty cursor
                })

        monkeypatch.setattr(
            "core.adapters.get_router",
            lambda: FakeRouter(),
        )
        titles = list_existing_discount_titles()
        assert call_count["n"] == 1
        assert titles == {"X"}
