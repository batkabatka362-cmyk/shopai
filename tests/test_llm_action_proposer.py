"""Tests for engines.llm_action_proposer — W963-52."""
from __future__ import annotations

import os
from unittest.mock import patch

from engines.llm_action_proposer import (
    LlmActionProposerEngine,
)
from engines.llm_action_proposer.proposer import (
    ProposedAction,
    _deterministic_baseline,
    _refine_with_llm,
    propose,
)


# ── _deterministic_baseline ───────────────────────────────


class TestDeterministicBaseline:
    def test_no_data_three_actions(self):
        acts = _deterministic_baseline(
            {"verdict": "no_data"}, "",
        )
        assert len(acts) == 3
        assert acts[0].action == "kick off a cycle"
        assert acts[0].priority == "critical"

    def test_no_data_store_arg_in_cli(self):
        acts = _deterministic_baseline(
            {"verdict": "no_data"}, "sX",
        )
        # earn-bootstrap should carry --store sX
        assert any(
            "--store sX" in a.cli_command for a in acts
        )

    def test_attributed_loss(self):
        acts = _deterministic_baseline(
            {
                "verdict": "attributed_loss",
                "gross_profit": -50.0,
            },
            "",
        )
        assert len(acts) == 3
        assert acts[0].action == "investigate ad ROAS"
        assert "shopai roas" in acts[0].cli_command

    def test_organic_only(self):
        acts = _deterministic_baseline(
            {
                "verdict": "organic_only",
                "pending_approvals": 5,
            },
            "",
        )
        assert len(acts) == 3
        assert acts[0].action == (
            "rank revenue engines by signal"
        )

    def test_earning_healthy(self):
        acts = _deterministic_baseline(
            {
                "verdict": "earning",
                "gross_profit": 200.0,
                "trend_verdict": "rising",
                "loss_store_count": 0,
            },
            "",
        )
        assert len(acts) == 3
        # Priority info when healthy
        assert acts[0].priority == "info"

    def test_earning_declining_critical(self):
        # W963-90: original test used "declining" vocab but
        # the real upstream (compute_summary) emits
        # "falling". Both should now escalate to critical.
        for vocab in ("declining", "falling"):
            acts = _deterministic_baseline(
                {
                    "verdict": "earning",
                    "gross_profit": 100.0,
                    "trend_verdict": vocab,
                    "loss_store_count": 0,
                },
                "",
            )
            assert acts[0].priority == "critical", (
                f"vocab {vocab} did not escalate"
            )

    def test_earning_loss_stores_normal(self):
        acts = _deterministic_baseline(
            {
                "verdict": "earning",
                "gross_profit": 100.0,
                "trend_verdict": "flat",
                "loss_store_count": 2,
            },
            "",
        )
        assert acts[0].priority == "normal"

    def test_every_branch_returns_three(self):
        for v in (
            "no_data", "attributed_loss",
            "organic_only", "earning",
        ):
            acts = _deterministic_baseline(
                {"verdict": v}, "",
            )
            assert len(acts) == 3
            ranks = [a.rank for a in acts]
            assert ranks == [1, 2, 3]


# ── _refine_with_llm ──────────────────────────────────────


def _make_actions():
    return [
        ProposedAction(
            rank=1, action="x", cli_command="shopai x",
            rationale="r1", priority="normal",
        ),
        ProposedAction(
            rank=2, action="y", cli_command="shopai y",
            rationale="r2", priority="normal",
        ),
    ]


class TestRefineWithLlm:
    def test_no_env(self):
        acts = _make_actions()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SHOPAI_AI_STRATEGY", None)
            out, used, reason = _refine_with_llm(
                acts, {}, "",
            )
        assert used is False
        assert "not set" in reason

    def test_pytest_guard(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_AI_STRATEGY": "1"},
            clear=False,
        ):
            out, used, reason = _refine_with_llm(
                _make_actions(), {}, "",
            )
        assert used is False
        assert "pytest" in reason

    def test_no_client(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_AI_STRATEGY": "1"},
            clear=False,
        ), patch(
            "engines.llm_action_proposer.proposer."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "engines._ai_strategies._LLMClient",
        ) as fake_cls:
            fake_cls.return_value.available = False
            out, used, reason = _refine_with_llm(
                _make_actions(), {}, "",
            )
        assert used is False
        assert "no LLM" in reason

    def test_invalid_response(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_AI_STRATEGY": "1"},
            clear=False,
        ), patch(
            "engines.llm_action_proposer.proposer."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "engines._ai_strategies._LLMClient",
        ) as fake_cls:
            fake = fake_cls.return_value
            fake.available = True
            fake.chat_json.return_value = "garbage"
            out, used, reason = _refine_with_llm(
                _make_actions(), {}, "",
            )
        assert used is False

    def test_attaches_rationale_by_rank(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_AI_STRATEGY": "1"},
            clear=False,
        ), patch(
            "engines.llm_action_proposer.proposer."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "engines._ai_strategies._LLMClient",
        ) as fake_cls:
            fake = fake_cls.return_value
            fake.available = True
            fake.chat_json.return_value = {
                "rationales": [
                    {
                        "rank": 1,
                        "rationale": "refined rationale 1",
                    },
                    {
                        "rank": 2,
                        "rationale": "refined rationale 2",
                    },
                ],
            }
            out, used, reason = _refine_with_llm(
                _make_actions(), {}, "",
            )
        assert used is True
        assert out[0].rationale == "refined rationale 1"
        assert out[1].rationale == "refined rationale 2"

    def test_truncates_long_rationale(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_AI_STRATEGY": "1"},
            clear=False,
        ), patch(
            "engines.llm_action_proposer.proposer."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "engines._ai_strategies._LLMClient",
        ) as fake_cls:
            fake = fake_cls.return_value
            fake.available = True
            fake.chat_json.return_value = {
                "rationales": [
                    {"rank": 1, "rationale": "x" * 500},
                ],
            }
            out, _, _ = _refine_with_llm(
                _make_actions(), {}, "",
            )
        assert len(out[0].rationale) <= 300

    def test_invalid_rank_skipped(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_AI_STRATEGY": "1"},
            clear=False,
        ), patch(
            "engines.llm_action_proposer.proposer."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "engines._ai_strategies._LLMClient",
        ) as fake_cls:
            fake = fake_cls.return_value
            fake.available = True
            fake.chat_json.return_value = {
                "rationales": [
                    {"rank": "abc", "rationale": "should skip"},
                    {"rank": 1, "rationale": "good"},
                ],
            }
            out, used, _ = _refine_with_llm(
                _make_actions(), {}, "",
            )
        assert used is True
        assert out[0].rationale == "good"
        # Rank 2 unchanged
        assert out[1].rationale == "r2"


# ── propose() ─────────────────────────────────────────────


class TestPropose:
    def test_signal_override(self):
        r = propose(
            signals_override={"verdict": "no_data"},
        )
        assert r.verdict == "no_data"
        assert len(r.proposed) == 3

    def test_attributed_loss_override(self):
        r = propose(
            signals_override={
                "verdict": "attributed_loss",
                "gross_profit": -100.0,
            },
        )
        assert r.verdict == "attributed_loss"
        assert r.proposed[0].action == (
            "investigate ad ROAS"
        )


# ── Envelope (Pattern Q) ──────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = LlmActionProposerEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = LlmActionProposerEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = LlmActionProposerEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = LlmActionProposerEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = LlmActionProposerEngine().run({})
        assert (
            r["meta"]["engine"] == "llm_action_proposer"
        )

    def test_returns_proposed_list(self):
        r = LlmActionProposerEngine().run({})
        assert isinstance(r["data"]["proposed"], list)

    def test_next_action_present(self):
        r = LlmActionProposerEngine().run({})
        assert r["data"]["next_action"]
