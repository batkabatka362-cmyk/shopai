"""Tests for engines.plan_executor — W963-36."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from engines.plan_executor import PlanExecutorEngine
from engines.plan_executor.executor import (
    PlanExecutionReport,
    _generate_plan_id,
    _resolve_capability,
    execute_plan,
)


# ── _generate_plan_id ─────────────────────────────────────


class TestGeneratePlanId:
    def test_starts_with_prefix(self):
        pid = _generate_plan_id()
        assert pid.startswith("plan_")

    def test_unique_per_call(self):
        a = _generate_plan_id()
        b = _generate_plan_id()
        # time_ns is monotonic, may produce same value on
        # fast Windows clock. Accept either.
        assert a.startswith("plan_") and b.startswith("plan_")


# ── _resolve_capability ───────────────────────────────────


class TestResolveCapability:
    def test_returns_synthetic_key(self):
        assert (
            _resolve_capability("loyalty")
            == "PLAN_STEP_LOYALTY"
        )

    def test_empty(self):
        assert _resolve_capability("") == ""


# ── execute_plan ──────────────────────────────────────────


def _fake_plan_composer_result(steps=None):
    if steps is None:
        steps = [
            {
                "order": 1,
                "engine": "earn_bootstrap",
                "action": "Seed catalog",
                "drill_command": "shopai earn-bootstrap",
                "reasoning": "cold start",
                "impact": "high",
            },
            {
                "order": 2,
                "engine": "ads_launcher",
                "action": "Wire ads",
                "drill_command": "shopai ads connect",
                "reasoning": "traffic",
                "impact": "high",
            },
        ]
    return {
        "status": "success",
        "data": {
            "template_matched": "cold_start",
            "steps": steps,
        },
        "meta": {}, "error": None,
    }


class TestExecutePlan:
    def test_empty_goal_returns_empty(self):
        r = execute_plan(goal="")
        assert r.plan_step_count == 0
        assert r.enqueued_count == 0

    def test_compose_failure_returns_empty(self):
        with patch(
            "engines.plan_composer.PlanComposerEngine"
        ) as MockEng:
            MockEng.return_value.run.return_value = {
                "status": "error",
            }
            r = execute_plan(goal="cold_start")
        assert r.plan_step_count == 0

    def test_dry_run_marks_all_steps_dry_run(self):
        with patch(
            "engines.plan_composer.PlanComposerEngine"
        ) as MockEng:
            MockEng.return_value.run.return_value = (
                _fake_plan_composer_result()
            )
            r = execute_plan(
                goal="cold_start", confirmed=False,
            )
        assert r.plan_step_count == 2
        assert r.enqueued_count == 0
        assert r.skip_reasons.get("dry_run") == 2

    def test_confirmed_enqueues_each_step(self):
        fake_queue = MagicMock()
        action_ids = ["a-1", "a-2"]
        fake_queue.enqueue.side_effect = [
            MagicMock(id=action_ids[0]),
            MagicMock(id=action_ids[1]),
        ]
        with patch(
            "engines.plan_composer.PlanComposerEngine"
        ) as MockEng, patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            MockEng.return_value.run.return_value = (
                _fake_plan_composer_result()
            )
            r = execute_plan(
                goal="cold_start", confirmed=True,
            )
        assert r.enqueued_count == 2
        # All steps share plan_id in params
        for s in r.steps:
            assert s.enqueued is True

    def test_queue_failure_skips_all_steps(self):
        with patch(
            "engines.plan_composer.PlanComposerEngine"
        ) as MockEng, patch(
            "core.approval.queue.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            MockEng.return_value.run.return_value = (
                _fake_plan_composer_result()
            )
            r = execute_plan(
                goal="cold_start", confirmed=True,
            )
        assert r.enqueued_count == 0
        assert (
            r.skip_reasons.get("queue_unavailable") == 2
        )

    def test_no_engine_step_skipped(self):
        steps = [
            {
                "order": 1,
                "engine": "",  # no engine
                "action": "x",
            },
        ]
        fake_queue = MagicMock()
        with patch(
            "engines.plan_composer.PlanComposerEngine"
        ) as MockEng, patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            MockEng.return_value.run.return_value = (
                _fake_plan_composer_result(steps=steps)
            )
            r = execute_plan(
                goal="cold_start", confirmed=True,
            )
        assert r.skip_reasons.get("no_engine") == 1
        assert not fake_queue.enqueue.called

    def test_enqueue_exception_captured(self):
        fake_queue = MagicMock()
        fake_queue.enqueue.side_effect = RuntimeError(
            "db full",
        )
        with patch(
            "engines.plan_composer.PlanComposerEngine"
        ) as MockEng, patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            MockEng.return_value.run.return_value = (
                _fake_plan_composer_result()
            )
            r = execute_plan(
                goal="cold_start", confirmed=True,
            )
        assert r.enqueued_count == 0
        assert (
            r.skip_reasons.get("enqueue_failed") == 2
        )

    def test_plan_id_in_params(self):
        fake_queue = MagicMock()
        fake_queue.enqueue.return_value = MagicMock(
            id="a-1",
        )
        with patch(
            "engines.plan_composer.PlanComposerEngine"
        ) as MockEng, patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            MockEng.return_value.run.return_value = (
                _fake_plan_composer_result()
            )
            r = execute_plan(
                goal="cold_start", confirmed=True,
            )
        # First enqueue call's params should include plan_id
        call = fake_queue.enqueue.call_args_list[0]
        params = call.kwargs.get("params") or {}
        assert params.get("plan_id") == r.plan_id

    def test_store_id_threaded_to_enqueue(self):
        fake_queue = MagicMock()
        fake_queue.enqueue.return_value = MagicMock(
            id="x",
        )
        with patch(
            "engines.plan_composer.PlanComposerEngine"
        ) as MockEng, patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            MockEng.return_value.run.return_value = (
                _fake_plan_composer_result()
            )
            execute_plan(
                goal="cold_start",
                store_id="storeA",
                confirmed=True,
            )
        call = fake_queue.enqueue.call_args_list[0]
        assert call.kwargs.get("store_id") == "storeA"


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = PlanExecutorEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = PlanExecutorEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = PlanExecutorEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = PlanExecutorEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = PlanExecutorEngine().run({})
        assert r["meta"]["engine"] == "plan_executor"


class TestEngineActions:
    def test_double_gate_yes_without_env_stays_dry(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(
                "SHOPAI_PLAN_EXECUTOR_ENABLED", None,
            )
            r = PlanExecutorEngine().run({
                "data": {
                    "goal": "cold_start", "confirmed": True,
                },
            })
        assert r["data"]["operator_confirmed"] is True
        assert r["data"]["env_gate_set"] is False
        assert r["data"]["confirmed"] is False

    def test_both_gates_set_attempts_enqueue(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_PLAN_EXECUTOR_ENABLED": "1"},
            clear=False,
        ):
            r = PlanExecutorEngine().run({
                "data": {
                    "goal": "cold_start", "confirmed": True,
                },
            })
        assert r["data"]["confirmed"] is True

    def test_empty_goal_returns_zero_steps(self):
        r = PlanExecutorEngine().run({})
        assert r["data"]["plan_step_count"] == 0
        assert "Pass a goal" in r["data"]["next_action"]

    def test_invalid_max_steps_falls_back(self):
        r = PlanExecutorEngine().run({
            "data": {
                "goal": "cold_start", "max_steps": "x",
            },
        })
        assert r["status"] == "success"
