"""Tests for audit-pass-18 fixes in core/state.

  1. StateManager.create_session/close_session used the
     `dict.get(k, {})` antipattern. If active_sessions wasn't
     initialized in global_state, .get returned a brand-new
     ephemeral dict and the session_id assignment was
     immediately discarded — sessions silently never registered.
  2. RuntimeState.update_task incremented the tasks_completed /
     tasks_failed counters every time the method was called,
     not only on the first transition into a terminal state.
     A retry that re-marked "completed" inflated the metric.
  3. RuntimeState had no thread lock — concurrent register_task
     and update_task calls could race on _tasks dict mutations
     and on `+=1` on the metric counters.
  4. GlobalState.snapshot() returned a SHALLOW copy. Mutating
     nested dicts in the snapshot poisoned the canonical state.
"""
import threading

import pytest


# Reset the GlobalState singleton between tests so state from
# one test never leaks into another.
@pytest.fixture(autouse=True)
def _reset_global_state():
    from core.state.global_state import GlobalState
    gs = GlobalState()
    gs.reset()
    yield
    gs.reset()


# ── StateManager dict.get(k, {}) antipattern ────────────────


class TestStateManagerSessionRegistration:
    def test_create_session_registers_in_global_state(self):
        """Regression: previously this assignment went into an
        ephemeral default dict and was immediately discarded
        when active_sessions wasn't already in global_state."""
        from core.state.state_manager import StateManager
        sm = StateManager()
        # Don't call initialize() — the bug appeared specifically
        # when active_sessions wasn't pre-populated.
        session = sm.create_session("s1")

        active = sm.global_state.get("active_sessions")
        assert isinstance(active, dict)
        assert active.get("s1") is True

    def test_close_session_removes_from_global_state(self):
        from core.state.state_manager import StateManager
        sm = StateManager()
        sm.create_session("s1")
        sm.create_session("s2")
        sm.close_session("s1")

        active = sm.global_state.get("active_sessions")
        assert "s1" not in active
        assert "s2" in active

    def test_create_session_after_initialize_works(self):
        """The fix must not regress the already-initialized path."""
        from core.state.state_manager import StateManager
        sm = StateManager()
        sm.initialize({})
        sm.create_session("s1")
        assert "s1" in sm.global_state.get("active_sessions")


# ── RuntimeState double-counting ─────────────────────────────


class TestRuntimeStateMetrics:
    def test_re_completing_task_does_not_double_count(self):
        """Regression: previously calling update_task("x",
        "completed") twice incremented tasks_completed twice."""
        from core.state.runtime_state import RuntimeState
        rs = RuntimeState()
        rs.register_task("t1", "demo")
        rs.update_task("t1", "completed")
        rs.update_task("t1", "completed")  # idempotent retry
        rs.update_task("t1", "completed")
        metrics = rs.get_metrics()
        assert metrics["tasks_completed"] == 1

    def test_failed_to_completed_does_not_double_count(self):
        """If a task moves between terminal states, only the
        first terminal transition counts."""
        from core.state.runtime_state import RuntimeState
        rs = RuntimeState()
        rs.register_task("t1", "demo")
        rs.update_task("t1", "failed")
        # Operator manually fixes and marks completed — should
        # NOT also increment tasks_completed because the task
        # already counted toward tasks_failed.
        rs.update_task("t1", "completed")
        metrics = rs.get_metrics()
        assert metrics["tasks_failed"] == 1
        assert metrics["tasks_completed"] == 0

    def test_separate_tasks_counted_independently(self):
        from core.state.runtime_state import RuntimeState
        rs = RuntimeState()
        for i in range(5):
            rs.register_task(f"t{i}", "demo")
            rs.update_task(f"t{i}", "completed")
        for i in range(3):
            rs.register_task(f"f{i}", "demo")
            rs.update_task(f"f{i}", "failed")
        metrics = rs.get_metrics()
        assert metrics["tasks_started"] == 8
        assert metrics["tasks_completed"] == 5
        assert metrics["tasks_failed"] == 3


# ── RuntimeState defensive copy ──────────────────────────────


class TestRuntimeStateDefensiveCopy:
    def test_get_task_returns_copy(self):
        from core.state.runtime_state import RuntimeState
        rs = RuntimeState()
        rs.register_task("t1", "demo")
        snap = rs.get_task("t1")
        snap["status"] = "POISONED"
        # Original state untouched
        again = rs.get_task("t1")
        assert again["status"] == "pending"

    def test_get_active_tasks_returns_copies(self):
        from core.state.runtime_state import RuntimeState
        rs = RuntimeState()
        rs.register_task("t1", "demo")
        active = rs.get_active_tasks()
        active["t1"]["status"] = "POISONED"
        again = rs.get_active_tasks()
        assert again["t1"]["status"] == "pending"


# ── RuntimeState thread safety ───────────────────────────────


class TestRuntimeStateThreadSafety:
    def test_concurrent_register_no_lost_tasks(self):
        from core.state.runtime_state import RuntimeState
        rs = RuntimeState()

        def worker(start):
            for i in range(50):
                rs.register_task(f"t_{start}_{i}", "demo")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        metrics = rs.get_metrics()
        # 4 threads * 50 = 200 tasks counted, none lost
        assert metrics["tasks_started"] == 200

    def test_concurrent_update_no_lost_completions(self):
        from core.state.runtime_state import RuntimeState
        rs = RuntimeState()
        for i in range(100):
            rs.register_task(f"t{i}", "demo")

        def worker(start):
            for i in range(start, start + 25):
                rs.update_task(f"t{i}", "completed")

        threads = [threading.Thread(target=worker, args=(i,)) for i in (0, 25, 50, 75)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        metrics = rs.get_metrics()
        assert metrics["tasks_completed"] == 100


# ── GlobalState snapshot deep-copy ───────────────────────────


class TestGlobalStateSnapshotDeepCopy:
    def test_snapshot_mutation_does_not_poison_state(self):
        """Regression: previously snapshot returned a shallow
        copy so mutating active_sessions in the snapshot also
        mutated the canonical state."""
        from core.state.global_state import GlobalState
        gs = GlobalState()
        gs.initialize({})
        gs.set("active_sessions", {"s1": True})

        snap = gs.snapshot()
        snap["active_sessions"]["POISONED"] = True
        snap["config"]["leak"] = "yes"

        # Canonical state is untouched
        assert "POISONED" not in gs.get("active_sessions")
        assert "leak" not in gs.get("config")

    def test_snapshot_returns_full_data(self):
        from core.state.global_state import GlobalState
        gs = GlobalState()
        gs.initialize({"env": "test"})
        snap = gs.snapshot()
        assert snap["system_status"] == "initializing"
        assert snap["config"]["env"] == "test"
