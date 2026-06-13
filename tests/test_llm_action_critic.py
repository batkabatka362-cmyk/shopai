"""Tests for engines.llm_action_critic — W963-53."""
from __future__ import annotations

import os
from unittest.mock import patch

from engines.llm_action_critic import LlmActionCriticEngine
from engines.llm_action_critic.critic import (
    Critique,
    _deterministic_baseline,
    _refine_with_llm,
    _severity_rank,
    critique,
)


# ── _severity_rank ────────────────────────────────────────


class TestSeverityRank:
    def test_order(self):
        assert _severity_rank("critical") > _severity_rank(
            "warn",
        ) > _severity_rank("info")

    def test_unknown_is_info(self):
        assert _severity_rank("bogus") == 0


# ── _deterministic_baseline ───────────────────────────────


def _prop(rank, action, cli):
    return {
        "rank": rank, "action": action, "cli_command": cli,
        "priority": "normal",
    }


class TestDeterministicBaseline:
    def test_empty(self):
        assert _deterministic_baseline([], "no_data") == []

    def test_cycle_trigger(self):
        crits = _deterministic_baseline(
            [_prop(1, "cycle", "shopai cycle run --yes")],
            verdict="no_data",
        )
        assert len(crits) == 1
        c = crits[0]
        assert "cycle_without_failure_check" in c.risk_flags
        assert c.severity == "warn"

    def test_bootstrap_trigger(self):
        crits = _deterministic_baseline(
            [_prop(1, "boot", "shopai earn-bootstrap")],
            verdict="no_data",
        )
        assert "credentials_required" in crits[0].risk_flags

    def test_batch_review_trigger(self):
        crits = _deterministic_baseline(
            [_prop(
                1, "br",
                "shopai approvals batch-review "
                "--auto-approve-ok",
            )],
            verdict="earning",
        )
        assert "wide_blast_radius" in crits[0].risk_flags

    def test_verdict_attributed_loss_critical(self):
        crits = _deterministic_baseline(
            [_prop(1, "roas", "shopai roas")],
            verdict="attributed_loss",
        )
        # attributed_loss bumps to critical via verdict-risk
        assert crits[0].severity == "critical"
        assert "bleeding" in crits[0].risk_flags

    def test_verdict_organic_only_warn(self):
        crits = _deterministic_baseline(
            [_prop(
                1, "rank", "shopai engine ranking",
            )],
            verdict="organic_only",
        )
        # warn from verdict, info from engine ranking trigger
        assert crits[0].severity == "warn"
        assert "agi_not_attributed" in crits[0].risk_flags

    def test_verdict_earning_keeps_info(self):
        crits = _deterministic_baseline(
            [_prop(1, "summary", "shopai earnings-summary")],
            verdict="earning",
        )
        # No anti-pattern triggers; earning verdict info
        assert crits[0].severity == "info"

    def test_flags_deduped(self):
        crits = _deterministic_baseline(
            [_prop(
                1, "x",
                "shopai cycle run --yes "
                "shopai cycle run --yes",
            )],
            verdict="no_data",
        )
        # Only one flag despite duplicate trigger
        assert (
            crits[0].risk_flags.count(
                "cycle_without_failure_check",
            ) == 1
        )

    def test_severity_max_wins(self):
        # Verdict=attributed_loss is critical; engine ranking
        # trigger is info -> overall critical
        crits = _deterministic_baseline(
            [_prop(1, "rank", "shopai engine ranking")],
            verdict="attributed_loss",
        )
        assert crits[0].severity == "critical"


# ── _refine_with_llm ──────────────────────────────────────


def _make_crits():
    return [
        Critique(
            rank=1, action="x", cli_command="shopai x",
            counter_rationale="baseline", severity="info",
        ),
        Critique(
            rank=2, action="y", cli_command="shopai y",
            counter_rationale="baseline2", severity="warn",
        ),
    ]


class TestRefineWithLlm:
    def test_no_env(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SHOPAI_AI_STRATEGY", None)
            out, used, reason = _refine_with_llm(
                _make_crits(), "no_data", "",
            )
        assert used is False

    def test_pytest_guard(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_AI_STRATEGY": "1"},
            clear=False,
        ):
            out, used, reason = _refine_with_llm(
                _make_crits(), "no_data", "",
            )
        assert used is False
        assert "pytest" in reason

    def test_invalid_response(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_AI_STRATEGY": "1"},
            clear=False,
        ), patch(
            "engines.llm_action_critic.critic."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "engines._ai_strategies._LLMClient",
        ) as fake_cls:
            fake = fake_cls.return_value
            fake.available = True
            fake.chat_json.return_value = "garbage"
            out, used, reason = _refine_with_llm(
                _make_crits(), "no_data", "",
            )
        assert used is False

    def test_attaches_counter_by_rank(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_AI_STRATEGY": "1"},
            clear=False,
        ), patch(
            "engines.llm_action_critic.critic."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "engines._ai_strategies._LLMClient",
        ) as fake_cls:
            fake = fake_cls.return_value
            fake.available = True
            fake.chat_json.return_value = {
                "counters": [
                    {
                        "rank": 1,
                        "counter_rationale": "sharper 1",
                    },
                    {
                        "rank": 2,
                        "counter_rationale": "sharper 2",
                    },
                ],
            }
            out, used, _ = _refine_with_llm(
                _make_crits(), "no_data", "",
            )
        assert used is True
        assert out[0].counter_rationale == "sharper 1"
        assert out[1].counter_rationale == "sharper 2"

    def test_truncates_long(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_AI_STRATEGY": "1"},
            clear=False,
        ), patch(
            "engines.llm_action_critic.critic."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "engines._ai_strategies._LLMClient",
        ) as fake_cls:
            fake = fake_cls.return_value
            fake.available = True
            fake.chat_json.return_value = {
                "counters": [
                    {
                        "rank": 1,
                        "counter_rationale": "x" * 500,
                    },
                ],
            }
            out, _, _ = _refine_with_llm(
                _make_crits(), "no_data", "",
            )
        assert len(out[0].counter_rationale) <= 300


# ── critique() ────────────────────────────────────────────


class TestCritique:
    def test_override(self):
        r = critique(
            proposed_override=[
                _prop(1, "x", "shopai cycle run --yes"),
            ],
            verdict_override="no_data",
        )
        assert len(r.critiques) == 1
        assert r.verdict == "no_data"

    def test_default_verdict_when_empty(self):
        r = critique(
            proposed_override=[
                _prop(1, "x", "shopai go-live"),
            ],
        )
        # Default verdict_override="" → "no_data"
        assert r.verdict == "no_data"


# ── Envelope (Pattern Q) ──────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = LlmActionCriticEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = LlmActionCriticEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = LlmActionCriticEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = LlmActionCriticEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = LlmActionCriticEngine().run({})
        assert (
            r["meta"]["engine"] == "llm_action_critic"
        )

    def test_returns_critiques_list(self):
        r = LlmActionCriticEngine().run({})
        assert isinstance(r["data"]["critiques"], list)

    def test_next_action_present(self):
        r = LlmActionCriticEngine().run({})
        assert r["data"]["next_action"]
