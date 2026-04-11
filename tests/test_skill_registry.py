"""Tests for the runtime SkillRegistry."""
import threading

import pytest


def _registry(**kwargs):
    from core.cognitive.skill_registry import SkillRegistry
    return SkillRegistry(**kwargs)


# ── Skill dataclass ───────────────────────────────────────────


class TestSkillDataclass:
    def test_to_dict_includes_success_rate(self):
        from core.cognitive.skill_registry import Skill
        s = Skill(name="x", use_count=10, success_count=8)
        d = s.to_dict()
        assert d["success_rate"] == 0.8
        assert d["use_count"] == 10

    def test_success_rate_zero_when_no_uses(self):
        from core.cognitive.skill_registry import Skill
        d = Skill(name="x").to_dict()
        assert d["success_rate"] == 0.0


# ── propose() ─────────────────────────────────────────────────


class TestPropose:
    def test_proposes_in_unvalidated_state(self):
        r = _registry()
        skill = r.propose("greet", lambda i: {"status": "ok", "msg": "hi"})
        assert skill.state == "unvalidated"
        assert r.get("greet") is skill

    def test_proposes_with_tags_and_signature(self):
        r = _registry()
        skill = r.propose(
            "x", lambda i: {"status": "ok"},
            description="A skill", tags=["greeting", "test"],
            signature={"input": {"name": "str"}},
        )
        assert "greeting" in skill.tags
        assert skill.signature == {"input": {"name": "str"}}
        assert skill.description == "A skill"

    def test_empty_name_raises(self):
        r = _registry()
        with pytest.raises(ValueError):
            r.propose("", lambda i: {})
        with pytest.raises(ValueError):
            r.propose("   ", lambda i: {})

    def test_non_callable_implementation_raises(self):
        r = _registry()
        with pytest.raises(ValueError):
            r.propose("x", "not callable")  # type: ignore

    def test_re_propose_overwrites(self):
        r = _registry()
        r.propose("x", lambda i: {"status": "ok"})
        r.propose("x", lambda i: {"status": "ok", "v": 2})
        result = r.invoke_force("x", {}) if False else None
        # State should be reset to unvalidated
        assert r.get("x").state == "unvalidated"


# ── validate() ────────────────────────────────────────────────


class TestValidate:
    def test_validates_and_promotes(self):
        r = _registry(min_accuracy=0.5)
        r.propose("greet", lambda i: {"status": "ok"})
        episodes = [{"input": {"x": 1}}, {"input": {"x": 2}}]
        accuracy = r.validate("greet", episodes)
        assert accuracy == 1.0
        assert r.get("greet").state == "validated"
        assert r.get("greet").validated_against == 2

    def test_does_not_promote_below_threshold(self):
        r = _registry(min_accuracy=0.8)
        # Implementation only succeeds half the time
        toggle = {"flag": False}

        def impl(inputs):
            toggle["flag"] = not toggle["flag"]
            return {"status": "ok"} if toggle["flag"] else {"status": "fail"}

        r.propose("flaky", impl)
        accuracy = r.validate("flaky", [{"input": {}} for _ in range(10)])
        assert accuracy == 0.5
        assert r.get("flaky").state == "unvalidated"

    def test_custom_predicate(self):
        r = _registry(min_accuracy=0.5)

        def impl(inputs):
            return {"answer": inputs.get("n", 0) * 2}

        r.propose("double", impl)
        accuracy = r.validate(
            "double",
            [{"input": {"n": 1}}, {"input": {"n": 2}}],
            success_predicate=lambda res: res.get("answer", 0) > 0,
        )
        assert accuracy == 1.0
        assert r.get("double").state == "validated"

    def test_implementation_exceptions_count_as_failures(self):
        r = _registry(min_accuracy=0.5)

        def boom(inputs):
            raise RuntimeError("boom")

        r.propose("crash", boom)
        accuracy = r.validate("crash", [{"input": {}} for _ in range(5)])
        assert accuracy == 0.0
        assert r.get("crash").state == "unvalidated"

    def test_unknown_skill_raises(self):
        from core.cognitive.skill_registry import SkillNotFound
        r = _registry()
        with pytest.raises(SkillNotFound):
            r.validate("ghost", [{"input": {}}])

    def test_min_accuracy_override(self):
        r = _registry(min_accuracy=0.8)

        def impl(inputs):
            return {"status": "ok" if inputs.get("good") else "fail"}

        r.propose("opt", impl)
        # Default 0.8 → not promoted at 60% accuracy
        eps = [{"input": {"good": i < 6}} for i in range(10)]
        r.validate("opt", eps)
        assert r.get("opt").state == "unvalidated"
        # Override to 0.5 → promoted
        r.validate("opt", eps, min_accuracy=0.5)
        assert r.get("opt").state == "validated"

    def test_no_episodes_yields_zero_accuracy(self):
        r = _registry()
        r.propose("x", lambda i: {"status": "ok"})
        accuracy = r.validate("x", [])
        assert accuracy == 0.0

    def test_episodes_without_input_skipped(self):
        r = _registry(min_accuracy=0.5)
        r.propose("x", lambda i: {"status": "ok"})
        # Mix of valid and invalid episode shapes
        episodes = [
            {"input": {"a": 1}},
            {"no_input_key": True},  # skipped
            "not a dict",  # skipped
            {"input": {"b": 2}},
        ]
        accuracy = r.validate("x", episodes)
        # Only 2 valid episodes, both succeeded
        assert accuracy == 1.0
        assert r.get("x").validated_against == 2


# ── invoke() ──────────────────────────────────────────────────


class TestInvoke:
    def _validated(self, registry, name="greet"):
        registry.propose(name, lambda i: {"status": "ok", "echo": i})
        registry.validate(name, [{"input": {}}, {"input": {}}])

    def test_invokes_validated_skill(self):
        r = _registry()
        self._validated(r)
        result = r.invoke("greet", {"hello": "world"})
        assert result["status"] == "ok"
        assert result["echo"] == {"hello": "world"}
        skill = r.get("greet")
        assert skill.use_count == 1
        assert skill.success_count == 1
        assert skill.last_used > 0

    def test_invocation_failures_increment_use_not_success(self):
        r = _registry()
        r.propose("greet", lambda i: {"status": "fail"})
        r.validate("greet", [{"input": {}}], min_accuracy=0.0)
        # State is validated even though accuracy=0 because we
        # passed min_accuracy=0.0 explicitly
        r.invoke("greet", {})
        skill = r.get("greet")
        assert skill.use_count == 1
        assert skill.success_count == 0

    def test_invoke_unknown_raises(self):
        from core.cognitive.skill_registry import SkillNotFound
        r = _registry()
        with pytest.raises(SkillNotFound):
            r.invoke("ghost", {})

    def test_invoke_unvalidated_raises(self):
        from core.cognitive.skill_registry import SkillNotInvocable
        r = _registry()
        r.propose("x", lambda i: {"status": "ok"})
        with pytest.raises(SkillNotInvocable):
            r.invoke("x", {})

    def test_invoke_retired_raises(self):
        from core.cognitive.skill_registry import SkillNotInvocable
        r = _registry()
        self._validated(r)
        r.retire("greet", reason="deprecated")
        with pytest.raises(SkillNotInvocable):
            r.invoke("greet", {})

    def test_invoke_handles_implementation_exception(self):
        r = _registry()
        r.propose("crash", lambda i: (_ for _ in ()).throw(RuntimeError("x")))
        r.validate("crash", [{"input": {}}], min_accuracy=0.0)
        result = r.invoke("crash", {})
        assert result["status"] == "error"
        # use_count still incremented
        assert r.get("crash").use_count == 1

    def test_invoke_non_dict_result(self):
        r = _registry()
        r.propose("bad", lambda i: "not a dict")  # type: ignore
        r.validate("bad", [{"input": {}}], min_accuracy=0.0)
        result = r.invoke("bad", {})
        assert result["status"] == "error"

    def test_custom_success_predicate(self):
        r = _registry()
        r.propose("calc", lambda i: {"answer": i.get("a", 0) + i.get("b", 0)})
        r.validate(
            "calc",
            [{"input": {"a": 1, "b": 2}}],
            success_predicate=lambda res: "answer" in res,
        )
        # Now invoke with a different predicate
        result = r.invoke(
            "calc", {"a": 5, "b": 5},
            success_predicate=lambda res: res.get("answer") == 10,
        )
        assert r.get("calc").success_count == 1


# ── compose() ─────────────────────────────────────────────────


class TestCompose:
    def _build_two_skills(self, r):
        r.propose("step1", lambda i: {"status": "ok", "a": i.get("x", 0) + 1})
        r.propose("step2", lambda i: {"status": "ok", "b": i.get("a", 0) * 10})
        r.validate("step1", [{"input": {"x": 1}}], min_accuracy=0.5)
        r.validate("step2", [{"input": {"a": 2}}], min_accuracy=0.5)

    def test_chains_outputs(self):
        r = _registry()
        self._build_two_skills(r)
        r.compose("pipeline", ["step1", "step2"])
        # Compose creates an unvalidated skill — validate it first
        r.validate("pipeline", [{"input": {"x": 1}}], min_accuracy=0.5)
        result = r.invoke("pipeline", {"x": 5})
        # x=5 → step1 a=6 → step2 b=60
        assert result["a"] == 6
        assert result["b"] == 60

    def test_empty_children_raises(self):
        r = _registry()
        with pytest.raises(ValueError):
            r.compose("p", [])

    def test_unknown_child_raises(self):
        from core.cognitive.skill_registry import SkillNotFound
        r = _registry()
        with pytest.raises(SkillNotFound):
            r.compose("p", ["ghost"])

    def test_unvalidated_child_raises(self):
        from core.cognitive.skill_registry import SkillNotInvocable
        r = _registry()
        r.propose("x", lambda i: {"status": "ok"})
        with pytest.raises(SkillNotInvocable):
            r.compose("p", ["x"])

    def test_composed_records_children(self):
        r = _registry()
        self._build_two_skills(r)
        skill = r.compose("p", ["step1", "step2"])
        assert skill.composed_of == ["step1", "step2"]

    def test_composed_invocation_updates_child_use_count(self):
        r = _registry()
        self._build_two_skills(r)
        r.compose("p", ["step1", "step2"])
        r.validate("p", [{"input": {"x": 1}}], min_accuracy=0.5)
        # Reset child counts (validation called them)
        r.get("step1").use_count = 0
        r.get("step2").use_count = 0
        r.invoke("p", {"x": 1})
        # Each child invoked once via the chain
        assert r.get("step1").use_count == 1
        assert r.get("step2").use_count == 1


# ── retire() + lifecycle ──────────────────────────────────────


class TestLifecycle:
    def test_retire_changes_state(self):
        r = _registry()
        r.propose("x", lambda i: {"status": "ok"})
        r.validate("x", [{"input": {}}], min_accuracy=0.0)
        r.retire("x", reason="deprecated")
        assert r.get("x").state == "retired"

    def test_retire_unknown_safe(self):
        r = _registry()
        r.retire("ghost")  # no exception


# ── Read API ──────────────────────────────────────────────────


class TestReads:
    def test_list_skills_filters_by_state(self):
        r = _registry()
        r.propose("a", lambda i: {"status": "ok"})
        r.propose("b", lambda i: {"status": "ok"})
        r.validate("b", [{"input": {}}], min_accuracy=0.0)
        proposed = r.list_skills(state="unvalidated")
        validated = r.list_skills(state="validated")
        assert [s.name for s in proposed] == ["a"]
        assert [s.name for s in validated] == ["b"]

    def test_list_filters_by_tag(self):
        r = _registry()
        r.propose("a", lambda i: {"status": "ok"}, tags=["x"])
        r.propose("b", lambda i: {"status": "ok"}, tags=["y"])
        out = r.list_skills(tag="x")
        assert [s.name for s in out] == ["a"]

    def test_stats(self):
        r = _registry()
        r.propose("a", lambda i: {"status": "ok"})
        r.validate("a", [{"input": {}}], min_accuracy=0.0)
        r.propose("b", lambda i: {"status": "ok"})  # unvalidated
        r.invoke("a", {})
        stats = r.stats()
        assert stats["total"] == 2
        assert stats["validated"] == 1
        assert stats["total_invocations"] == 1
        assert stats["total_successes"] == 1


# ── Concurrency ───────────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_invocations_dont_lose_counts(self):
        r = _registry()
        r.propose("x", lambda i: {"status": "ok"})
        r.validate("x", [{"input": {}}], min_accuracy=0.0)

        def worker():
            for _ in range(20):
                r.invoke("x", {})

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        skill = r.get("x")
        assert skill.use_count == 100
        assert skill.success_count == 100


class TestSingleton:
    def test_get_skill_registry_caches(self):
        from core.cognitive import skill_registry as mod
        mod._instance = None
        a = mod.get_skill_registry()
        b = mod.get_skill_registry()
        assert a is b
