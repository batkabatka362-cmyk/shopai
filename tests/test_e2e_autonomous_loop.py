"""End-to-end smoke test for the autonomous loop.

A single test that exercises every edge of the loop that landed
in PRs #103-#146:

    1. Operator/engine enqueues an action
    2. Approval queue stores it
    3. Operator approves (or executor auto-approves)
    4. Dispatcher executes → ``approval.executed`` hook fires
    5. ``goal_feedback`` handler (auto-attached on
       ``core.approval`` import via PR #115) updates the
       per-goal EMA in ``GoalManager``
    6. Webhook outcome arrives → bridge matches → ``record_outcome``
       fires → ``approval.outcome.recorded`` hook → EMA refines
       with revenue signal (PR #114)
    7. EMA persists to disk (PR #118)
    8. New ``GoalManager`` instance pointed at the same file
       reads back the learned EMA (durability check)
    9. Recommender consults the EMA and ranks the engine higher
       than its untrained baseline

If ANY of these edges breaks, this test fails. That's the whole
point — one test guards the contract across the loop.

Doesn't touch real Shopify. Doesn't touch real LearningLoop.
Doesn't pollute the dev DB (each fixture isolates via tmp_path
and the Pattern J pytest gates).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ─── shared fixtures ─────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _allow_hook_fanout():
    """The hooks dispatcher short-circuits under pytest by
    default. For this test, we WANT handlers to fire (that's
    what the test is verifying)."""
    with patch(
        "core.hooks.dispatcher._is_test_environment",
        return_value=False,
    ):
        yield


@pytest.fixture(autouse=True)
def _allow_goal_state_save():
    """GoalManager persistence is also gated under pytest. Allow
    saves so the load round-trip step can read what step 7 wrote."""
    with patch(
        "core.goals.goal_manager._is_test_environment",
        return_value=False,
    ):
        yield


@pytest.fixture
def isolated_state(tmp_path: Path, monkeypatch):
    """Each test gets its own:
    - approval queue DB
    - goal state file
    - hooks registry
    - goal_feedback registration

    Wired together so the e2e flow runs against a clean slate.
    """
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue
    from core.goals import goal_manager as gm
    from core.goals import goal_feedback as gf
    from core.hooks import dispatcher as hd

    # Fresh queue
    queue_path = tmp_path / "approval.db"
    fresh_queue = ApprovalQueue(db_path=queue_path)
    monkeypatch.setattr(q, "_INSTANCE", fresh_queue)

    # Fresh goal manager pointed at tmp state file
    goal_state = tmp_path / "goal_state.json"
    monkeypatch.setattr(gm, "_DEFAULT_STATE_PATH", goal_state)

    # Reset goal feedback registration + hooks
    hd._HANDLERS.clear()
    gf.reset_for_tests()

    # Inject a fresh manager singleton so feedback writes go there
    # (and so the persistence round-trip step reads the right file)
    fresh_manager = gm.GoalManager(state_path=goal_state)
    monkeypatch.setattr(gf, "_DEFAULT_MANAGER", fresh_manager)

    # Wire goal_feedback handlers to the fresh manager
    gf.register_goal_feedback(manager=fresh_manager)

    yield {
        "queue": fresh_queue,
        "manager": fresh_manager,
        "goal_state": goal_state,
        "tmp": tmp_path,
    }
    fresh_queue._conn.close()


# ─── the test ────────────────────────────────────────────────────


class TestAutonomousLoopEndToEnd:

    def test_full_cycle_engine_to_ema_to_recommender(
        self, isolated_state,
    ):
        """One test, every edge. If this fails, find the broken edge."""
        queue = isolated_state["queue"]
        manager = isolated_state["manager"]
        goal_state = isolated_state["goal_state"]

        # ─ Step 1: engine enqueues an action ──────────────
        # cart_recovery → grow_customers per ENGINE_GOAL_MAP
        action = queue.enqueue(
            engine="cart_recovery",
            action_type="mint_cart_recovery_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params={"token": "cust_e2e", "percentage": 10.0},
            narrative="E2E: 10% recovery code for cust_e2e",
            confidence=0.85,
        )
        assert action.id.startswith("appr_")

        # ─ Step 2: queue stored it ─────────────────────────
        assert queue.get(action.id) is not None
        from core.approval.queue import ApprovalStatus
        assert queue.get(action.id).status == ApprovalStatus.PENDING

        # ─ Step 3: operator approves ───────────────────────
        approved = queue.approve(
            action.id, decided_by="e2e_test", reason="e2e",
        )
        assert approved is not None
        assert approved.status == ApprovalStatus.APPROVED

        # Capture pre-execute EMA for delta verification later
        ema_pre = manager.get_effectiveness("grow_customers")
        assert ema_pre == pytest.approx(0.5)  # neutral default

        # ─ Step 4: dispatcher executes ─────────────────────
        # Stub out the underlying Shopify mutation so we don't
        # need a real router; the hook fan-out is what matters.
        queue.attach_result(
            action.id,
            success=True,
            result={"code": "RECOVER-E2E-1", "discount_id": "gid://X"},
        )
        post_exec = queue.get(action.id)
        assert post_exec.status == ApprovalStatus.EXECUTED

        # ─ Step 5: ``approval.executed`` hook drove EMA ───
        ema_after_exec = manager.get_effectiveness("grow_customers")
        # Should have moved up from 0.5 (positive execute signal)
        assert ema_after_exec > ema_pre, (
            f"approval.executed hook didn't update EMA: "
            f"pre={ema_pre}, post={ema_after_exec}"
        )

        # ─ Step 6: webhook outcome refines EMA ─────────────
        # Simulate a customer redeeming the minted code by feeding
        # the bridge's record_outcome path directly. (We're not
        # exercising webhook HTTP plumbing here — just the
        # queue→hook→feedback edge that landed in PR #114/#115.)
        outcome_ok = queue.record_outcome(
            action.id,
            topic="orders/create",
            polarity="positive",
            metrics={"revenue": 42.50},
            source_event="order_e2e_1",
        )
        assert outcome_ok is True

        outcomes = queue.get_outcomes(action.id)
        assert len(outcomes) == 1
        assert outcomes[0]["metrics"]["revenue"] == 42.50

        ema_after_outcome = manager.get_effectiveness("grow_customers")
        # Outcome event also fires through goal_feedback, so EMA
        # should refine further with the revenue signal.
        assert ema_after_outcome >= ema_after_exec, (
            "approval.outcome.recorded didn't propagate to EMA"
        )

        # ─ Step 7: EMA persisted to disk ───────────────────
        assert goal_state.exists(), (
            "GoalManager didn't save state to disk after EMA update"
        )

        # ─ Step 8: durability — fresh manager reads same EMA ─
        from core.goals.goal_manager import GoalManager
        reloaded = GoalManager(state_path=goal_state)
        assert reloaded.get_effectiveness("grow_customers") == (
            pytest.approx(ema_after_outcome, abs=1e-9)
        )

        # ─ Step 9: recommender uses EMA ────────────────────
        from core.brain.engine_recommender import recommend_engines
        result = recommend_engines(
            goal="grow_customers",
            manager=reloaded,
            limit=10,
            include_alternatives=False,
        )
        # cart_recovery is in the grow_customers map; should
        # show up in the primary picks now that grow_customers
        # has accumulated outcomes
        primary_engines = {r.engine for r in result.primary}
        assert "cart_recovery" in primary_engines

        # And the priority should be ABOVE neutral baseline
        cart_pick = next(
            r for r in result.primary if r.engine == "cart_recovery"
        )
        assert cart_pick.priority > 0.75, (
            f"recommender didn't honour learned EMA: "
            f"priority={cart_pick.priority}, EMA={ema_after_outcome}"
        )


# ─── individual edge sanity tests ────────────────────────────────


class TestEdgeSanity:
    """Per-edge tests so a failure in the e2e points at a specific
    edge rather than just 'the loop is broken'."""

    def test_edge_enqueue_to_pending(self, isolated_state):
        """Engine → queue → PENDING state visible immediately."""
        queue = isolated_state["queue"]
        a = queue.enqueue(
            engine="cart_recovery", action_type="x",
            capability="SHOPIFY_CREATE_DISCOUNT", params={},
            narrative="",
        )
        pending = queue.list_pending(engine="cart_recovery")
        assert any(p.id == a.id for p in pending)

    def test_edge_executed_hook_fires(self, isolated_state):
        """approval.executed hook reaches goal_feedback."""
        queue = isolated_state["queue"]
        manager = isolated_state["manager"]

        a = queue.enqueue(
            engine="cart_recovery", action_type="x",
            capability="X", params={}, narrative="",
        )
        queue.approve(a.id, decided_by="t")
        manager.record_goal_outcome = MagicMock(
            side_effect=manager.record_goal_outcome,
        )
        queue.attach_result(a.id, success=True, result={"code": "X"})
        assert manager.record_goal_outcome.called

    def test_edge_outcome_hook_refines_with_revenue(
        self, isolated_state,
    ):
        """approval.outcome.recorded → goal_feedback called
        with revenue_delta in metrics."""
        queue = isolated_state["queue"]
        manager = isolated_state["manager"]

        a = queue.enqueue(
            engine="cart_recovery", action_type="mint",
            capability="X", params={}, narrative="",
        )
        queue.approve(a.id)
        queue.attach_result(a.id, success=True, result={"code": "X"})
        # Clear the executed-hook call so we can isolate the
        # outcome-hook call
        manager.record_goal_outcome = MagicMock(
            side_effect=manager.record_goal_outcome,
        )
        queue.record_outcome(
            a.id, topic="orders/create",
            polarity="positive",
            metrics={"revenue": 25.0},
        )
        assert manager.record_goal_outcome.called
        # Inspect the recorded call
        call = manager.record_goal_outcome.call_args
        assert call.args[0] == "grow_customers"
        metrics = call.args[1]
        assert metrics.get("revenue_delta") == 25.0

    def test_edge_persistence_roundtrip(self, isolated_state):
        """EMA written by one manager is read by another."""
        from core.goals.goal_manager import GoalManager
        m1 = isolated_state["manager"]
        m1.record_goal_outcome(
            "grow_customers", {"health_delta": 1.0},
        )
        ema = m1.get_effectiveness("grow_customers")

        m2 = GoalManager(state_path=isolated_state["goal_state"])
        assert m2.get_effectiveness("grow_customers") == (
            pytest.approx(ema, abs=1e-9)
        )

    def test_edge_recommender_consumes_ema(self, isolated_state):
        """recommend_engines respects per-goal EMA from the
        injected manager."""
        from core.brain.engine_recommender import recommend_engines

        manager = isolated_state["manager"]
        # Drive grow_customers EMA up with several positive outcomes
        for _ in range(5):
            manager.record_goal_outcome(
                "grow_customers", {"health_delta": 1.0},
            )

        result = recommend_engines(
            goal="grow_customers",
            manager=manager,
            limit=10,
            include_alternatives=False,
        )
        cart = next(
            (r for r in result.primary if r.engine == "cart_recovery"),
            None,
        )
        assert cart is not None
        # priority = alignment * (0.5 + 0.5 * effectiveness)
        # alignment=1.0, effectiveness > 0.5 → priority > 0.75
        assert cart.priority > 0.75
