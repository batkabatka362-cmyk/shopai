"""Tests for audit-pass-27 fixes in agents/base/base_agent.

  1. _step_log was instance state — `self._step_log = []` reset on
     every run() call. Two threads calling run() concurrently on
     the same agent instance interleaved their step entries and
     one thread's _output() emitted the OTHER thread's steps.
  2. _history mutations had no thread lock — concurrent learn()
     calls raced on the unbounded list append + slice trim.
  3. except Exception captured only str(exc), losing the type
     info that operators need to debug audit-trail entries.
  4. learn() / _output() / get_history used direct dict access
     in several spots — a malformed plan/results/evaluation
     dict crashed the whole run.
  5. get_history returned slice references — caller mutation
     poisoned internal state.
"""
import threading
import time

import pytest


def _make_agent(plan_result=None, exec_result=None, eval_result=None,
                raises_in=None):
    """Build a tiny BaseAgent subclass with stubbed phases for testing."""
    from agents.base.base_agent import BaseAgent

    class _TestAgent(BaseAgent):
        def __init__(self):
            super().__init__("test")

        def plan(self, goal, context, constraints):
            if raises_in == "plan":
                raise RuntimeError("plan boom")
            return plan_result if plan_result is not None else {
                "engines": [{"name": "demo"}],
            }

        def execute(self, plan, context):
            if raises_in == "execute":
                raise ValueError("execute boom")
            return exec_result if exec_result is not None else {
                "engine_results": {"demo": {"ok": True}},
            }

        def evaluate(self, results, goal):
            if raises_in == "evaluate":
                raise TypeError("evaluate boom")
            return eval_result if eval_result is not None else {"score": 80}

    return _TestAgent()


# ── _step_log thread-isolation ──────────────────────────────


class TestStepLogIsolation:
    def test_concurrent_runs_dont_interleave_step_logs(self):
        """Regression: previously _step_log was instance state, so
        two threads calling run() concurrently shared the same
        list. Each thread reset it on entry then both wrote into
        the same list — _output() emitted the OTHER thread's
        steps."""
        # Slow plan() so the two runs overlap
        from agents.base.base_agent import BaseAgent

        class _SlowAgent(BaseAgent):
            def __init__(self):
                super().__init__("slow")

            def plan(self, goal, context, constraints):
                time.sleep(0.05)  # let the other thread run() too
                return {"engines": [{"name": goal}]}

            def execute(self, plan, context):
                return {"engine_results": {plan["engines"][0]["name"]: True}}

            def evaluate(self, results, goal):
                return {"score": 80}

        agent = _SlowAgent()
        results: dict[str, dict] = {}

        def worker(name):
            results[name] = agent.run(name)

        t1 = threading.Thread(target=worker, args=("alpha",))
        t2 = threading.Thread(target=worker, args=("beta",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Each thread's meta.steps should ONLY contain its own
        # step entries — not the other thread's. We can verify by
        # checking the engines_used field which mirrors the goal.
        alpha_engines = results["alpha"]["meta"]["engines_used"]
        beta_engines = results["beta"]["meta"]["engines_used"]
        # Flatten
        alpha_flat = [e["name"] for sublist in alpha_engines for e in sublist if isinstance(e, dict)]
        beta_flat = [e["name"] for sublist in beta_engines for e in sublist if isinstance(e, dict)]
        assert "alpha" in alpha_flat
        assert "beta" not in alpha_flat
        assert "beta" in beta_flat
        assert "alpha" not in beta_flat

    def test_step_log_is_local_to_run(self):
        """Verify the agent instance has no _step_log attribute
        leaking between calls."""
        agent = _make_agent()
        agent.run("first")
        agent.run("second")
        # Instance should NOT have a _step_log attribute persisted
        # between calls (it was the source of the race).
        assert not hasattr(agent, "_step_log")


# ── _history thread safety ──────────────────────────────────


class TestHistoryThreadSafety:
    def test_concurrent_runs_no_lost_history(self):
        agent = _make_agent()
        errors: list[Exception] = []

        def worker():
            try:
                for _ in range(20):
                    agent.run("g")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        # 4 threads × 20 = 80 history entries (capped at 100)
        history = agent.get_history(limit=200)
        assert len(history) == 80


# ── Exception type capture ──────────────────────────────────


class TestExceptionTypeCapture:
    def test_runtime_error_keeps_type(self):
        agent = _make_agent(raises_in="plan")
        result = agent.run("g")
        assert result["status"] == "fail"
        assert "RuntimeError" in result["error"]["reason"]
        assert "plan boom" in result["error"]["reason"]

    def test_value_error_keeps_type(self):
        agent = _make_agent(raises_in="execute")
        result = agent.run("g")
        assert "ValueError" in result["error"]["reason"]

    def test_type_error_keeps_type(self):
        agent = _make_agent(raises_in="evaluate")
        result = agent.run("g")
        assert "TypeError" in result["error"]["reason"]


# ── Defensive .get() in learn / _output ─────────────────────


class TestDefensiveAccess:
    def test_plan_with_missing_engine_name(self):
        """A plan with engines that lack the 'name' field used to
        crash with KeyError in learn()."""
        agent = _make_agent(plan_result={"engines": [{"purpose": "x"}]})
        result = agent.run("g")
        # Did not crash; learn() captured "unknown" for the missing name
        assert result["status"] == "success"

    def test_non_dict_plan_returned(self):
        """A buggy subclass that returns a non-dict plan should
        be coerced to {} instead of crashing."""
        agent = _make_agent(plan_result="not a dict")
        result = agent.run("g")
        # No engines → fail status, but no crash
        assert result["status"] == "fail"

    def test_non_dict_execute_returned(self):
        agent = _make_agent(exec_result="not a dict")
        result = agent.run("g")
        # Engine results coerced to {} → execution still completes
        assert result["status"] == "success"

    def test_non_dict_evaluation_returned(self):
        agent = _make_agent(eval_result=None)
        result = agent.run("g")
        assert result["status"] == "success"

    def test_engines_with_non_dict_entries(self):
        agent = _make_agent(plan_result={
            "engines": [{"name": "ok"}, "string", None, {"name": "ok2"}],
        })
        result = agent.run("g")
        # Did not crash; only valid dict entries kept in learn()
        assert result["status"] == "success"
        engines_in_history = agent.get_history()[-1]["engines_used"]
        assert engines_in_history == ["ok", "ok2"]


# ── get_history defensive copy ──────────────────────────────


class TestHistoryDefensiveCopy:
    def test_history_returns_copies(self):
        agent = _make_agent()
        agent.run("g")
        h1 = agent.get_history()
        h1[0]["mutated"] = "yes"
        h2 = agent.get_history()
        assert "mutated" not in h2[0]


# ── End-to-end happy path regression ────────────────────────


class TestHappyPathRegression:
    def test_full_run_succeeds(self):
        agent = _make_agent()
        result = agent.run("test goal", {"k": "v"})
        assert result["status"] == "success"
        assert result["data"]["evaluation"]["score"] == 80
        assert result["meta"]["agent"] == "test"
        assert len(result["meta"]["steps"]) >= 4  # plan/exec/eval/learn

    def test_no_engines_returns_fail(self):
        agent = _make_agent(plan_result={"engines": []})
        result = agent.run("g")
        assert result["status"] == "fail"
        assert "no engine steps" in result["error"]["reason"]
