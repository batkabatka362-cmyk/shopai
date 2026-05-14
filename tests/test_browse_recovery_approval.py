"""Tests for the browse_recovery approval-queue wiring.

Sister to cart_recovery. Same audit follow-up: pre-fix this engine
unconditionally minted a code per offer whenever the router was
available. This PR brings browse_recovery in line with the opt-in
pattern.

Coverage:
  1. ``enqueue_offer_codes_for_approval`` happy path — per-offer
     mutation, ``pending_action_id`` stamped, ``minted=False``
  2. Skip semantics: low-intent / zero-pct / queue-unavailable
  3. flow integration — three branches of Stage 4.5
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue

    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


# ─── enqueue_offer_codes_for_approval ───────────────────────────


def _offers():
    return [
        {"user_id": "u1", "discount_pct": 15},
        {"user_id": "u2", "discount_pct": 10},
        {"user_id": "u3", "discount_pct": 20},
    ]


def _intent_scores():
    return [
        {"user_id": "u1", "purchase_likelihood": "high"},
        {"user_id": "u2", "purchase_likelihood": "medium"},
        {"user_id": "u3", "purchase_likelihood": "low"},  # filtered out
    ]


class TestEnqueueOfferCodesForApproval:

    def test_happy_path_queues_eligible_offers_only(
        self, isolated_queue,
    ):
        from engines.browse_recovery.discount_minter import (
            enqueue_offer_codes_for_approval,
        )

        offers = _offers()
        result = enqueue_offer_codes_for_approval(
            offers=offers, intent_scores=_intent_scores(),
        )

        # Same list returned (mutated in place).
        assert result is offers

        # u1 + u2 queued (high + medium intent); u3 skipped (low).
        assert offers[0]["pending_action_id"].startswith("appr_")
        assert offers[0]["minted"] is False
        assert offers[0]["code"] == ""

        assert offers[1]["pending_action_id"].startswith("appr_")
        assert offers[1]["minted"] is False

        # u3 had low intent — no enqueue, no pending_action_id key.
        assert "pending_action_id" not in offers[2]
        assert offers[2]["minted"] is False

        # Two actions actually persisted.
        assert isolated_queue.stats()["pending"] == 2

    def test_zero_discount_pct_skipped(self, isolated_queue):
        from engines.browse_recovery.discount_minter import (
            enqueue_offer_codes_for_approval,
        )

        offers = [{"user_id": "u1", "discount_pct": 0}]
        enqueue_offer_codes_for_approval(
            offers=offers,
            intent_scores=[
                {"user_id": "u1", "purchase_likelihood": "high"},
            ],
        )
        assert "pending_action_id" not in offers[0]
        assert offers[0]["minted"] is False

    def test_non_numeric_discount_pct_skipped(self, isolated_queue):
        from engines.browse_recovery.discount_minter import (
            enqueue_offer_codes_for_approval,
        )

        offers = [{"user_id": "u1", "discount_pct": "garbage"}]
        enqueue_offer_codes_for_approval(
            offers=offers,
            intent_scores=[
                {"user_id": "u1", "purchase_likelihood": "high"},
            ],
        )
        assert "pending_action_id" not in offers[0]

    def test_queue_unavailable_stamps_all_skipped(self, isolated_queue):
        from engines.browse_recovery.discount_minter import (
            enqueue_offer_codes_for_approval,
        )

        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("DB locked"),
        ):
            offers = _offers()
            enqueue_offer_codes_for_approval(
                offers=offers, intent_scores=_intent_scores(),
            )
        for offer in offers:
            assert offer["minted"] is False
            assert offer["code"] == ""
            assert "pending_action_id" not in offer

    def test_empty_offers_returns_empty(self, isolated_queue):
        from engines.browse_recovery.discount_minter import (
            enqueue_offer_codes_for_approval,
        )

        assert enqueue_offer_codes_for_approval(
            offers=[], intent_scores=[],
        ) == []

    def test_narrative_captures_user_pct_intent_ttl(
        self, isolated_queue,
    ):
        from engines.browse_recovery.discount_minter import (
            enqueue_offer_codes_for_approval,
        )

        offers = [{"user_id": "u1", "discount_pct": 25}]
        intents = [{"user_id": "u1", "purchase_likelihood": "high"}]
        enqueue_offer_codes_for_approval(
            offers=offers, intent_scores=intents,
            store={"recovery_code_ttl_days": 14},
        )
        action = isolated_queue.get(offers[0]["pending_action_id"])
        assert action is not None
        assert "25% off" in action.narrative
        assert "high intent" in action.narrative
        assert "14d TTL" in action.narrative


# ─── flow integration ───────────────────────────────────────────


def _flow_input(*, apply_recovery=None, require_approval=None):
    data: dict = {
        "sessions": [
            {"user_id": "u1", "viewed_at": 0,
             "products_viewed": ["p1", "p2"], "engagement": 0.8},
        ],
        "products": [{"id": "p1", "title": "Widget"}],
        "store": {"avg_margin": 0.4},
    }
    if apply_recovery is not None:
        data["apply_recovery"] = apply_recovery
    if require_approval is not None:
        data["require_approval"] = require_approval
    return {"status": "ok", "data": data, "meta": {}, "error": None}


class TestFlowApprovalIntegration:

    def test_default_off_writes_nothing(self, isolated_queue):
        # Default skips both paths — every offer surfaces with
        # minted=False and empty code fields.
        from engines.browse_recovery.flow import BrowseRecoveryEngine

        with patch(
            "engines.browse_recovery.flow.mint_offer_codes",
        ) as mock_mint, patch(
            "engines.browse_recovery.flow.enqueue_offer_codes_for_approval",
        ) as mock_enqueue:
            output = BrowseRecoveryEngine().run(_flow_input())

        mock_mint.assert_not_called()
        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            for offer in output["data"].get("offers", []):
                assert offer["minted"] is False
                assert offer["code"] == ""

    def test_apply_recovery_true_routes_to_direct_mint(
        self, isolated_queue,
    ):
        from engines.browse_recovery.flow import BrowseRecoveryEngine

        with patch(
            "engines.browse_recovery.flow.mint_offer_codes",
            side_effect=lambda offers, **kw: offers,
        ) as mock_mint, patch(
            "engines.browse_recovery.flow.enqueue_offer_codes_for_approval",
        ) as mock_enqueue:
            output = BrowseRecoveryEngine().run(
                _flow_input(apply_recovery=True, require_approval=False),
            )

        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            mock_mint.assert_called_once()

    def test_require_approval_true_routes_to_enqueue(
        self, isolated_queue,
    ):
        from engines.browse_recovery.flow import BrowseRecoveryEngine

        with patch(
            "engines.browse_recovery.flow.mint_offer_codes",
        ) as mock_mint, patch(
            "engines.browse_recovery.flow.enqueue_offer_codes_for_approval",
            side_effect=lambda offers, **kw: offers,
        ) as mock_enqueue:
            output = BrowseRecoveryEngine().run(
                _flow_input(apply_recovery=True, require_approval=True),
            )

        mock_mint.assert_not_called()
        if output["status"] == "success":
            mock_enqueue.assert_called_once()
