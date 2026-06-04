"""Tests for engines.llm_strategist_advisor — W963-51."""
from __future__ import annotations

import os
from unittest.mock import patch

from engines.llm_strategist_advisor import (
    LlmStrategistAdvisorEngine,
)
from engines.llm_strategist_advisor.advisor import (
    Recommendation,
    _confidence_band,
    _deterministic_baseline,
    _refine_with_llm,
    advise,
)


# ── _confidence_band ──────────────────────────────────────


class TestConfidenceBand:
    def test_low(self):
        assert _confidence_band(0) == "low"
        assert _confidence_band(2) == "low"

    def test_medium(self):
        assert _confidence_band(3) == "medium"
        assert _confidence_band(9) == "medium"

    def test_high(self):
        assert _confidence_band(10) == "high"
        assert _confidence_band(100) == "high"


# ── _deterministic_baseline ───────────────────────────────


def _entry(signal, outcome="positive", store_id="s1"):
    return {
        "store_id": store_id,
        "signal": signal,
        "outcome": outcome,
    }


class TestDeterministicBaseline:
    def test_empty(self):
        recs = _deterministic_baseline([], "s1", 10)
        assert recs == []

    def test_skips_empty_signal(self):
        recs = _deterministic_baseline(
            [_entry("")], "s1", 10,
        )
        assert recs == []

    def test_groups_by_signal(self):
        entries = [
            _entry("mint", "positive"),
            _entry("mint", "positive"),
            _entry("mint", "negative"),
            _entry("tag", "positive"),
        ]
        recs = _deterministic_baseline(entries, "s1", 10)
        assert len(recs) == 2
        mint = next(r for r in recs if r.signal == "mint")
        assert mint.positive_count == 2
        assert mint.negative_count == 1
        # success rate = 2 / (2+1) ≈ 0.667
        assert abs(mint.success_rate - 0.667) < 0.01

    def test_ranks_by_positive_then_sr(self):
        entries = [
            _entry("a", "positive"),
            _entry("a", "positive"),
            _entry("b", "positive"),
            _entry("b", "positive"),
            _entry("b", "negative"),
        ]
        recs = _deterministic_baseline(entries, "s1", 10)
        # b has more positives (2) vs a (2) -- tied;
        # a has higher sr (1.0) vs b (0.667). Ranking is
        # positive_count desc, then success_rate desc -- so
        # tied positive → a wins on sr
        assert recs[0].signal == "a"
        assert recs[0].rank == 1
        assert recs[1].rank == 2

    def test_limit_k(self):
        entries = [
            _entry(f"sig_{i}", "positive") for i in range(15)
        ]
        recs = _deterministic_baseline(entries, "s1", 5)
        assert len(recs) == 5

    def test_unknown_outcome_counted_in_total(self):
        entries = [
            _entry("x", "positive"),
            _entry("x", "unknown"),
            _entry("x", "garbage"),
        ]
        recs = _deterministic_baseline(entries, "s1", 10)
        assert len(recs) == 1
        r = recs[0]
        # "garbage" doesn't match positive/negative/unknown
        # bucket, falls through to unknown
        assert r.total == 3


# ── _refine_with_llm ──────────────────────────────────────


class TestRefineWithLlm:
    def test_no_env_returns_baseline(self):
        recs = [Recommendation(
            signal="x", positive_count=1, negative_count=0,
            unknown_count=0, total=1,
        )]
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SHOPAI_AI_STRATEGY", None)
            out, used, reason = _refine_with_llm(
                recs, store_id="s1",
            )
        assert used is False
        assert "not set" in reason
        assert out == recs

    def test_pytest_guard(self):
        recs = [Recommendation(
            signal="x", positive_count=1, negative_count=0,
            unknown_count=0, total=1,
        )]
        with patch.dict(
            os.environ,
            {"SHOPAI_AI_STRATEGY": "1"},
            clear=False,
        ):
            out, used, reason = _refine_with_llm(
                recs, store_id="s1",
            )
        assert used is False
        assert "pytest" in reason

    def test_empty_recs(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_AI_STRATEGY": "1"},
            clear=False,
        ), patch(
            "engines.llm_strategist_advisor.advisor."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "engines._ai_strategies._LLMClient",
        ) as fake_cls:
            fake_cls.return_value.available = True
            out, used, reason = _refine_with_llm(
                [], store_id="s1",
            )
        assert used is False
        assert out == []

    def test_llm_unavailable(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_AI_STRATEGY": "1"},
            clear=False,
        ), patch(
            "engines.llm_strategist_advisor.advisor."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "engines._ai_strategies._LLMClient",
        ) as fake_cls:
            fake_cls.return_value.available = False
            recs = [Recommendation(
                signal="x", positive_count=1,
                negative_count=0, unknown_count=0, total=1,
            )]
            out, used, reason = _refine_with_llm(
                recs, store_id="s1",
            )
        assert used is False
        assert "no LLM" in reason

    def test_llm_invalid_response(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_AI_STRATEGY": "1"},
            clear=False,
        ), patch(
            "engines.llm_strategist_advisor.advisor."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "engines._ai_strategies._LLMClient",
        ) as fake_cls:
            fake = fake_cls.return_value
            fake.available = True
            fake.chat_json.return_value = (
                "not a dict"
            )
            recs = [Recommendation(
                signal="x", positive_count=1,
                negative_count=0, unknown_count=0, total=1,
            )]
            out, used, reason = _refine_with_llm(
                recs, store_id="s1",
            )
        assert used is False
        assert "non-dict" in reason

    def test_llm_attaches_insight(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_AI_STRATEGY": "1"},
            clear=False,
        ), patch(
            "engines.llm_strategist_advisor.advisor."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "engines._ai_strategies._LLMClient",
        ) as fake_cls:
            fake = fake_cls.return_value
            fake.available = True
            fake.chat_json.return_value = {
                "insights": [
                    {
                        "signal": "x",
                        "insight": "Works best on Tuesdays.",
                    },
                ],
            }
            recs = [Recommendation(
                signal="x", positive_count=1,
                negative_count=0, unknown_count=0, total=1,
            )]
            out, used, reason = _refine_with_llm(
                recs, store_id="s1",
            )
        assert used is True
        assert out[0].pattern_insight.startswith(
            "Works best",
        )

    def test_llm_truncates_long_insight(self):
        long_str = "x" * 500
        with patch.dict(
            os.environ,
            {"SHOPAI_AI_STRATEGY": "1"},
            clear=False,
        ), patch(
            "engines.llm_strategist_advisor.advisor."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "engines._ai_strategies._LLMClient",
        ) as fake_cls:
            fake = fake_cls.return_value
            fake.available = True
            fake.chat_json.return_value = {
                "insights": [
                    {"signal": "x", "insight": long_str},
                ],
            }
            recs = [Recommendation(
                signal="x", positive_count=1,
                negative_count=0, unknown_count=0, total=1,
            )]
            out, _, _ = _refine_with_llm(
                recs, store_id="s1",
            )
        assert len(out[0].pattern_insight) <= 240


# ── advise() ──────────────────────────────────────────────


class TestAdvise:
    def test_no_entries(self):
        r = advise(entries_override=[])
        assert r.entries_scanned == 0
        assert r.recommendations == []

    def test_basic_baseline(self):
        entries = [
            _entry("mint", "positive"),
            _entry("mint", "positive"),
            _entry("tag", "negative"),
        ]
        r = advise(
            store_id="s1", k=10,
            entries_override=entries,
        )
        assert r.entries_scanned == 3
        assert len(r.recommendations) == 2
        assert r.llm_used is False


# ── Envelope (Pattern Q) ──────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = LlmStrategistAdvisorEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = LlmStrategistAdvisorEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = LlmStrategistAdvisorEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = LlmStrategistAdvisorEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = LlmStrategistAdvisorEngine().run({})
        assert (
            r["meta"]["engine"] == "llm_strategist_advisor"
        )

    def test_invalid_k_falls_back(self):
        r = LlmStrategistAdvisorEngine().run({
            "data": {"k": "abc"},
        })
        assert r["data"]["k"] == 10

    def test_next_action_present(self):
        r = LlmStrategistAdvisorEngine().run({})
        assert r["data"]["next_action"]
