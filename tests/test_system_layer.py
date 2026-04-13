"""Tests for System Layer: TaskQueue, SharedMemory, LLMAdapter, SystemOrchestrator."""
import time
import pytest


class TestTaskQueue:
    def test_add_and_get(self):
        from core.system.task_queue import TaskQueue
        q = TaskQueue()
        task = q.add("t1", engine="pricing")
        assert task.id == "t1"
        assert q.get_task("t1") is not None

    def test_execution_order_simple(self):
        from core.system.task_queue import TaskQueue
        q = TaskQueue()
        q.add("a", engine="e1")
        q.add("b", engine="e2", depends_on=["a"])
        q.add("c", engine="e3", depends_on=["b"])
        order = q.get_execution_order()
        assert order.index("a") < order.index("b") < order.index("c")

    def test_execution_order_parallel(self):
        from core.system.task_queue import TaskQueue
        q = TaskQueue()
        q.add("sync", engine="sync")
        q.add("pricing", engine="pricing", depends_on=["sync"])
        q.add("inventory", engine="inventory", depends_on=["sync"])
        order = q.get_execution_order()
        assert order.index("sync") < order.index("pricing")
        assert order.index("sync") < order.index("inventory")

    def test_circular_dependency_detected(self):
        from core.system.task_queue import TaskQueue
        q = TaskQueue()
        q.add("a", depends_on=["b"])
        q.add("b", depends_on=["a"])
        with pytest.raises(ValueError, match="Circular"):
            q.get_execution_order()

    def test_add_chain(self):
        from core.system.task_queue import TaskQueue
        q = TaskQueue()
        tasks = q.add_chain([
            {"id": "a", "engine": "e1"},
            {"id": "b", "engine": "e2"},
            {"id": "c", "engine": "e3"},
        ])
        assert len(tasks) == 3
        assert tasks[1].depends_on == ["a"]
        assert tasks[2].depends_on == ["b"]

    def test_ready_tasks(self):
        from core.system.task_queue import TaskQueue, TaskStatus
        q = TaskQueue()
        q.add("a", engine="e1")
        q.add("b", engine="e2", depends_on=["a"])
        ready = q.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == "a"

    def test_execute_with_custom_executor(self):
        from core.system.task_queue import TaskQueue
        q = TaskQueue()
        q.add("t1", engine="test")
        q.add("t2", engine="test", depends_on=["t1"])
        result = q.execute_all(executor=lambda t: {"ok": True, "task": t.id})
        assert result["completed"] == 2
        assert result["failed"] == 0

    def test_blocked_on_failed_dependency(self):
        from core.system.task_queue import TaskQueue
        q = TaskQueue()
        q.add("t1", engine="test")
        q.add("t2", engine="test", depends_on=["t1"])
        def fail_executor(t):
            if t.id == "t1":
                raise Exception("fail")
            return {"ok": True}
        result = q.execute_all(executor=fail_executor)
        assert result["failed"] == 1
        assert result["blocked"] == 1

    def test_get_status(self):
        from core.system.task_queue import TaskQueue
        q = TaskQueue()
        q.add("a")
        q.add("b")
        status = q.get_status()
        assert status.get("pending", 0) == 2

    def test_clear(self):
        from core.system.task_queue import TaskQueue
        q = TaskQueue()
        q.add("a")
        q.clear()
        assert q.get_all_tasks() == []


class TestSharedMemory:
    def test_put_get(self):
        from core.system.shared_memory import SharedMemory
        mem = SharedMemory()
        mem.put("products", "list", [1, 2, 3])
        assert mem.get("products", "list") == [1, 2, 3]

    def test_missing_key(self):
        from core.system.shared_memory import SharedMemory
        mem = SharedMemory()
        assert mem.get("products", "missing") is None
        assert mem.get("products", "missing", "default") == "default"

    def test_ttl_expiration(self):
        from core.system.shared_memory import SharedMemory
        mem = SharedMemory()
        mem.put("cache", "temp", "value", ttl_seconds=1)
        assert mem.get("cache", "temp") == "value"
        time.sleep(1.1)
        assert mem.get("cache", "temp") is None

    def test_get_all(self):
        from core.system.shared_memory import SharedMemory
        mem = SharedMemory()
        mem.put("products", "a", 1)
        mem.put("products", "b", 2)
        data = mem.get_all("products")
        assert data == {"a": 1, "b": 2}

    def test_delete(self):
        from core.system.shared_memory import SharedMemory
        mem = SharedMemory()
        mem.put("test", "key", "val")
        assert mem.delete("test", "key")
        assert not mem.exists("test", "key")

    def test_load_store_data(self):
        from core.system.shared_memory import SharedMemory
        mem = SharedMemory()
        mem.load_store_data([{"id": 1}], [{"id": 2}], [{"id": 3}], "store1")
        assert mem.get("products", "count") == 1
        assert mem.get("orders", "count") == 1
        assert mem.get("state", "store_id") == "store1"

    def test_context_for_task(self):
        from core.system.shared_memory import SharedMemory
        mem = SharedMemory()
        mem.put("products", "list", [1, 2])
        mem.put("analytics", "report", {"revenue": 100})
        ctx = mem.get_context_for_task("pricing")
        assert "products" in ctx

    def test_record_decision(self):
        from core.system.shared_memory import SharedMemory
        mem = SharedMemory()
        mem.record_decision("d1", {"type": "price_change", "value": 29.99})
        assert mem.get("decisions", "d1") is not None

    def test_stats(self):
        from core.system.shared_memory import SharedMemory
        mem = SharedMemory()
        mem.put("products", "a", 1)
        mem.put("orders", "b", 2)
        stats = mem.get_stats()
        assert stats["total_entries"] == 2

    def test_singleton(self):
        from core.system.shared_memory import get_shared_memory
        m1 = get_shared_memory()
        m2 = get_shared_memory()
        assert m1 is m2


class TestLLMAdapter:
    def test_init(self):
        from core.system.llm_adapter import LLMAdapter
        llm = LLMAdapter()
        assert llm is not None

    def test_auto_configure(self):
        from core.system.llm_adapter import LLMAdapter
        llm = LLMAdapter()
        result = llm.auto_configure()
        assert "configured" in result
        assert "roles" in result

    def test_get_available_models(self):
        from core.system.llm_adapter import LLMAdapter
        llm = LLMAdapter()
        models = llm.get_available_models()
        assert isinstance(models, list)

    def test_response_parse_json(self):
        from core.system.llm_adapter import LLMResponse
        resp = LLMResponse('Some text {"action": "raise", "reason": "low margin"} end',
                          "mistral", "ollama", success=True)
        parsed = resp.parse_json()
        assert parsed["action"] == "raise"

    def test_response_parse_json_invalid(self):
        from core.system.llm_adapter import LLMResponse
        resp = LLMResponse("no json here", "mistral", "ollama", success=True)
        parsed = resp.parse_json()
        assert "raw" in parsed

    def test_stats(self):
        from core.system.llm_adapter import LLMAdapter
        llm = LLMAdapter()
        stats = llm.get_stats()
        assert "models" in stats
        # Adapter upgraded: field renamed to role_map (more specific)
        assert "role_map" in stats

    def test_singleton(self):
        from core.system.llm_adapter import get_llm
        l1 = get_llm()
        l2 = get_llm()
        assert l1 is l2


class TestSystemOrchestrator:
    def test_init(self):
        from core.system.orchestrator import SystemOrchestrator
        orch = SystemOrchestrator()
        result = orch.initialize()
        assert result["status"] == "initialized"

    def test_get_state(self):
        from core.system.orchestrator import SystemOrchestrator
        orch = SystemOrchestrator()
        orch.initialize()
        state = orch.get_state()
        assert state["initialized"] is True
        assert "memory" in state
        assert "llm" in state

    def test_run_flow_unknown(self):
        from core.system.orchestrator import SystemOrchestrator
        orch = SystemOrchestrator()
        orch.initialize()
        result = orch.run_flow("nonexistent")
        assert result["status"] == "error"
        assert "available" in result

    def test_singleton(self):
        from core.system.orchestrator import get_orchestrator
        o1 = get_orchestrator()
        o2 = get_orchestrator()
        assert o1 is o2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
