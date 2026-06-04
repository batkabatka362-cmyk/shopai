"""Tests for engines.capability_browser — W963-30."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from engines.capability_browser import CapabilityBrowserEngine
from engines.capability_browser.searcher import (
    CapabilityHit,
    _goal_expansion,
    _score_capability,
    _tokens,
    goal_suggestions,
    search_capabilities,
)


# ── _tokens ───────────────────────────────────────────────


class TestTokens:
    def test_basic(self):
        assert _tokens("Hello world") == {"hello", "world"}

    def test_skip_short(self):
        # 'a' has length 1, skip
        assert "a" not in _tokens("a big test")

    def test_non_string(self):
        assert _tokens(None) == set()
        assert _tokens(123) == set()

    def test_underscores_preserved(self):
        assert "cart_recovery" in _tokens("Use cart_recovery")


# ── _goal_expansion ───────────────────────────────────────


class TestGoalExpansion:
    def test_traffic_expansion(self):
        out = _goal_expansion("get traffic")
        assert "ads" in out
        assert "pinterest" in out

    def test_convert_expansion(self):
        out = _goal_expansion("convert better")
        assert "cro" in out

    def test_no_match_returns_empty(self):
        out = _goal_expansion("xyzzy")
        assert out == []

    def test_case_insensitive(self):
        out = _goal_expansion("GET TRAFFIC")
        assert "ads" in out


# ── _score_capability ──────────────────────────────────────


def _make_cap(
    name="loyalty",
    description="Loyalty rewards engine for retention",
    when_to_use="When repeat customers exist",
    tags=None,
    cli_commands=None,
):
    c = MagicMock()
    c.name = name
    c.description = description
    c.when_to_use = when_to_use
    c.tags = tags or []
    c.cli_commands = cli_commands or []
    return c


class TestScoreCapability:
    def test_no_query_baseline(self):
        c = _make_cap()
        score, comp = _score_capability(
            c, query_tokens=set(), expanded_keywords=[],
        )
        assert score == 1.0
        assert "baseline" in comp

    def test_name_match_high_score(self):
        c = _make_cap(name="loyalty")
        score, comp = _score_capability(
            c,
            query_tokens={"loyalty"},
            expanded_keywords=[],
        )
        assert score >= 5.0
        assert "name" in comp

    def test_tag_match(self):
        c = _make_cap(tags=["retention", "high_value"])
        score, comp = _score_capability(
            c,
            query_tokens={"retention"},
            expanded_keywords=[],
        )
        assert "tag" in comp

    def test_description_match(self):
        c = _make_cap(
            description="Reward loyal customers",
        )
        score, comp = _score_capability(
            c,
            query_tokens={"reward"},
            expanded_keywords=[],
        )
        assert "description" in comp

    def test_goal_expansion_soft_hit(self):
        c = _make_cap(
            name="pinterest_publisher",
            description="Publish pins to pinterest",
        )
        # Operator typed "get traffic" — expanded includes
        # pinterest/ads/etc.
        score, comp = _score_capability(
            c,
            query_tokens={"get", "traffic"},
            expanded_keywords=["ads", "pinterest", "social"],
        )
        assert "goal_expansion" in comp

    def test_zero_score_when_no_match(self):
        c = _make_cap(
            name="unrelated", description="something else",
        )
        score, _ = _score_capability(
            c,
            query_tokens={"loyalty"},
            expanded_keywords=[],
        )
        assert score == 0.0


# ── search_capabilities ──────────────────────────────────


def _fake_registry(caps):
    r = MagicMock()
    r.all.return_value = caps
    return r


class TestSearch:
    def test_empty_query_returns_all_with_top_cap(self):
        caps = [
            _make_cap(name=f"cap_{i}") for i in range(30)
        ]
        with patch(
            "core.capability_registry.bootstrap."
            "ensure_registered",
        ), patch(
            "core.capability_registry.get_registry",
            return_value=_fake_registry(caps),
        ):
            r = search_capabilities(query="", top=10)
        assert r.total_registry == 30
        assert len(r.hits) == 10

    def test_query_filters_to_matches(self):
        caps = [
            _make_cap(name="loyalty", description="x"),
            _make_cap(
                name="other_engine",
                description="unrelated stuff",
            ),
            _make_cap(
                name="random", description="more unrelated",
            ),
        ]
        with patch(
            "core.capability_registry.bootstrap."
            "ensure_registered",
        ), patch(
            "core.capability_registry.get_registry",
            return_value=_fake_registry(caps),
        ):
            r = search_capabilities(query="loyalty")
        assert len(r.hits) == 1
        assert r.hits[0].name == "loyalty"

    def test_kind_filter(self):
        caps = [
            _make_cap(name="a"),
            _make_cap(name="b"),
        ]
        caps[0].kind = "engine"
        caps[1].kind = "adapter"
        with patch(
            "core.capability_registry.bootstrap."
            "ensure_registered",
        ), patch(
            "core.capability_registry.get_registry",
            return_value=_fake_registry(caps),
        ):
            r = search_capabilities(
                query="", kind_filter="engine",
            )
        assert all(h.kind == "engine" for h in r.hits)

    def test_tag_filter(self):
        caps = [
            _make_cap(name="a", tags=["cold_start"]),
            _make_cap(name="b", tags=["growth"]),
        ]
        with patch(
            "core.capability_registry.bootstrap."
            "ensure_registered",
        ), patch(
            "core.capability_registry.get_registry",
            return_value=_fake_registry(caps),
        ):
            r = search_capabilities(
                query="", tag_filter="cold_start",
            )
        assert len(r.hits) == 1
        assert r.hits[0].name == "a"

    def test_hits_sorted_desc_by_score(self):
        caps = [
            _make_cap(name="loyalty"),  # name match high
            _make_cap(
                name="other",
                description="loyalty mentioned here",
            ),  # desc match lower
        ]
        with patch(
            "core.capability_registry.bootstrap."
            "ensure_registered",
        ), patch(
            "core.capability_registry.get_registry",
            return_value=_fake_registry(caps),
        ):
            r = search_capabilities(query="loyalty")
        assert r.hits[0].name == "loyalty"
        assert r.hits[0].score > r.hits[1].score

    def test_no_match_returns_empty_hits(self):
        caps = [_make_cap(name="x")]
        with patch(
            "core.capability_registry.bootstrap."
            "ensure_registered",
        ), patch(
            "core.capability_registry.get_registry",
            return_value=_fake_registry(caps),
        ):
            r = search_capabilities(query="zzz_unmatched")
        assert r.hits == []

    def test_registry_failure_returns_empty(self):
        with patch(
            "core.capability_registry.bootstrap."
            "ensure_registered",
            side_effect=RuntimeError("nope"),
        ):
            r = search_capabilities(query="x")
        assert r.total_registry == 0
        assert r.hits == []


# ── goal_suggestions ──────────────────────────────────────


class TestGoalSuggestions:
    def test_returns_sorted_list(self):
        out = goal_suggestions()
        assert isinstance(out, list)
        assert out == sorted(out)
        assert "traffic" in out


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = CapabilityBrowserEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = CapabilityBrowserEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = CapabilityBrowserEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = CapabilityBrowserEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = CapabilityBrowserEngine().run({})
        assert r["meta"]["engine"] == "capability_browser"


class TestEngineActions:
    def test_query_threaded(self):
        r = CapabilityBrowserEngine().run({
            "data": {"query": "loyalty"},
        })
        assert r["data"]["query"] == "loyalty"

    def test_invalid_top_falls_back(self):
        r = CapabilityBrowserEngine().run({
            "data": {"top": "abc"},
        })
        assert r["status"] == "success"

    def test_goal_suggestions_included(self):
        r = CapabilityBrowserEngine().run({})
        suggs = r["data"]["goal_suggestions"]
        assert len(suggs) >= 5
