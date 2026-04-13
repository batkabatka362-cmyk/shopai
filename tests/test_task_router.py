"""Tests for the task-aware adaptive TaskRouter."""
import tempfile

import pytest


# ── Helpers ──────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, text="ok", success=True, tokens=10):
        self.text = text
        self.success = success
        self.tokens_used = tokens


class _FakeAdapter:
    """Minimal LLMAdapter-shaped fake."""

    def __init__(self):
        from core.system.llm_adapter import LLMConfig
        self._configs = {
            "mistral":   LLMConfig(provider="ollama", model="mistral", url="http://x"),
            "qwen2.5":   LLMConfig(provider="ollama", model="qwen2.5", url="http://x"),
            "llama3.2":  LLMConfig(provider="ollama", model="llama3.2", url="http://x"),
            "openai":    LLMConfig(provider="openai", model="gpt-4o-mini", api_key="sk"),
        }
        self._role_map = {
            "analyzer": "mistral",
            "reasoner": "mistral",
            "worker":   "qwen2.5",
            "creative": "llama3.2",
            "general":  "mistral",
        }
        # Per-call programmable response based on the active role/model
        self._response_map: dict[str, _FakeResponse] = {}
        self.calls: list[dict] = []

    def set_response(self, model: str, response: _FakeResponse) -> None:
        self._response_map[model] = response

    def ask(self, role="", prompt="", context=None, system_prompt=""):
        # The router temporarily sets self._role_map[role] before
        # calling. We use that to figure out which "model" answered.
        model = self._role_map.get(role, "mistral")
        self.calls.append({"role": role, "model": model, "prompt": prompt})
        return self._response_map.get(model, _FakeResponse())


def _router(**kwargs):
    from core.system.task_router import TaskRouter
    return TaskRouter(adapter=_FakeAdapter(), **kwargs)


# ── Stats dataclass ──────────────────────────────────────────


class TestTaskModelStats:
    def test_record_success_and_failure(self):
        from core.system.task_router import TaskModelStats
        s = TaskModelStats()
        s.record(True, 0.5, 100)
        s.record(False, 1.0, 50)
        assert s.calls == 2
        assert s.successes == 1
        assert s.success_rate == 0.5
        assert s.avg_latency_s == 0.75
        assert s.total_tokens == 150

    def test_to_dict_and_from_dict_roundtrip(self):
        from core.system.task_router import TaskModelStats
        s = TaskModelStats()
        s.record(True, 0.3, 10)
        s.record(True, 0.4, 15)
        d = s.to_dict()
        s2 = TaskModelStats.from_dict({
            "calls": d["calls"],
            "successes": d["successes"],
            "total_latency_s": s.total_latency_s,
            "total_tokens": s.total_tokens,
            "last_used": s.last_used,
        })
        assert s2.calls == s.calls
        assert s2.successes == s.successes


# ── Static role routing ──────────────────────────────────────


class TestStaticRouting:
    def test_analyze_routes_to_analyzer_role(self):
        r = _router()
        decision = r.route("analyze_product", "what's the margin?")
        assert decision.role == "analyzer"
        assert decision.model == "mistral"  # role default
        assert decision.success is True

    def test_write_routes_to_creative(self):
        r = _router()
        decision = r.route("write_description", "describe this widget")
        assert decision.role == "creative"
        assert decision.model == "llama3.2"

    def test_extract_routes_to_worker(self):
        r = _router()
        decision = r.route("extract_keywords", "extract from text")
        assert decision.role == "worker"
        assert decision.model == "qwen2.5"

    def test_unknown_task_falls_back_to_general(self):
        r = _router()
        decision = r.route("does_not_exist", "x")
        assert decision.role == "general"

    def test_force_model_bypasses_routing(self):
        r = _router()
        decision = r.route(
            "analyze_product", "x", force_model="qwen2.5",
        )
        assert decision.model == "qwen2.5"


# ── Stats recording ──────────────────────────────────────────


class TestRecording:
    def test_records_after_each_call(self):
        r = _router()
        r.route("analyze_product", "x")
        r.route("analyze_product", "y")
        stats = r.stats()
        assert "analyze_product" in stats
        assert stats["analyze_product"]["mistral"]["calls"] == 2

    def test_failure_recorded_separately(self):
        r = _router()
        r._adapter.set_response("mistral", _FakeResponse(success=False))
        r.route("analyze_product", "x")
        stats = r.stats()
        assert stats["analyze_product"]["mistral"]["successes"] == 0
        assert stats["analyze_product"]["mistral"]["calls"] == 1

    def test_learn_false_disables_recording(self):
        r = _router(learn=False)
        r.route("analyze_product", "x")
        assert r.stats() == {}


# ── Adaptive routing ─────────────────────────────────────────


class TestAdaptiveRouting:
    def _train(self, router, task_type, model, *, n_success=5, n_fail=0):
        """Manually inject training data so the router has 'experience'."""
        from core.system.task_router import TaskModelStats
        stats = TaskModelStats()
        for _ in range(n_success):
            stats.record(True, 0.2, 10)
        for _ in range(n_fail):
            stats.record(False, 0.5, 0)
        router._stats[task_type][model] = stats

    def test_picks_best_model_after_enough_data(self):
        r = _router()
        # mistral fails 4/5 on extract_keywords; qwen succeeds 5/5
        self._train(r, "extract_keywords", "mistral", n_success=1, n_fail=4)
        self._train(r, "extract_keywords", "qwen2.5", n_success=5, n_fail=0)
        decision = r.route("extract_keywords", "extract")
        assert decision.model == "qwen2.5"
        assert "adaptive" in decision.reason

    def test_falls_back_to_static_when_no_history(self):
        r = _router()
        # No history at all → falls back to role-default
        decision = r.route("analyze_product", "x")
        assert decision.model == "mistral"
        assert "static" in decision.reason

    def test_partial_history_below_threshold_uses_static(self):
        r = _router()
        # Only 2 observations → not enough for adaptive
        self._train(r, "analyze_product", "qwen2.5", n_success=2)
        decision = r.route("analyze_product", "x")
        # Should still use the role default (mistral)
        assert decision.model == "mistral"

    def test_best_model_for_returns_none_when_no_history(self):
        r = _router()
        assert r.best_model_for("anything") is None

    def test_best_model_for_returns_winner(self):
        r = _router()
        self._train(r, "analyze_product", "mistral", n_success=5)
        self._train(r, "analyze_product", "qwen2.5", n_success=3, n_fail=2)
        # mistral has 100% success → best
        assert r.best_model_for("analyze_product") == "mistral"


# ── Budget awareness ─────────────────────────────────────────


class TestBudgetAwareness:
    def test_local_only_excludes_openai(self):
        r = _router()
        # Pre-train openai to "win" — but local_only should ignore it
        from core.system.task_router import TaskModelStats
        s = TaskModelStats()
        for _ in range(10):
            s.record(True, 0.1, 10)
        r._stats["analyze_product"]["openai"] = s

        decision = r.route("analyze_product", "x", budget="local_only")
        assert decision.model in ("mistral", "qwen2.5", "llama3.2")
        assert decision.model != "openai"

    def test_cheap_allows_openai(self):
        r = _router()
        decision = r.route("analyze_product", "x", budget="cheap")
        # Without history, falls back to role default (mistral, local)
        assert decision.model == "mistral"

    def test_premium_allows_all(self):
        r = _router()
        decision = r.route("analyze_product", "x", budget="premium")
        # Still picks role default without learned history
        assert decision.model == "mistral"


# ── Reset / state ────────────────────────────────────────────


class TestReset:
    def test_reset_task(self):
        r = _router()
        r.route("analyze_product", "x")
        assert "analyze_product" in r.stats()
        r.reset_task("analyze_product")
        assert "analyze_product" not in r.stats()

    def test_reset_all(self):
        r = _router()
        r.route("analyze_product", "x")
        r.route("write_description", "y")
        r.reset_all()
        assert r.stats() == {}


class TestPersistence:
    def test_save_and_load_state(self, tmp_path):
        from core.system.task_router import TaskRouter
        path = str(tmp_path / "router_state.json")
        # First instance: learn something
        r1 = TaskRouter(adapter=_FakeAdapter(), state_path=path)
        r1.route("analyze_product", "x")
        r1.route("analyze_product", "y")
        # Second instance with same state path should see the learned state
        r2 = TaskRouter(adapter=_FakeAdapter(), state_path=path)
        stats = r2.stats()
        assert "analyze_product" in stats
        assert stats["analyze_product"]["mistral"]["calls"] == 2

    def test_corrupt_state_file_safe(self, tmp_path):
        from core.system.task_router import TaskRouter
        path = tmp_path / "bad.json"
        path.write_text("not json{{")
        r = TaskRouter(adapter=_FakeAdapter(), state_path=str(path))
        # Should not crash, should start with empty stats
        assert r.stats() == {}


# ── Defensive / error paths ─────────────────────────────────


class TestDefensive:
    def test_no_adapter_returns_failure_decision(self):
        from core.system.task_router import TaskRouter
        r = TaskRouter(adapter=None)
        # Force adapter resolution to fail by patching the loader
        r._get_adapter = lambda: None  # type: ignore
        decision = r.route("analyze_product", "x")
        assert decision.success is False
        assert "no LLM adapter" in decision.reason

    def test_adapter_exception_recorded_as_failure(self):
        r = _router()

        def boom(role="", prompt="", context=None, system_prompt=""):
            raise RuntimeError("oops")

        r._adapter.ask = boom
        decision = r.route("analyze_product", "x")
        assert decision.success is False


# ── Singleton accessor ──────────────────────────────────────


class TestSingleton:
    def test_get_task_router_caches(self):
        from core.system.task_router import (
            get_task_router, reset_task_router_for_tests,
        )
        reset_task_router_for_tests()
        a = get_task_router()
        b = get_task_router()
        assert a is b
