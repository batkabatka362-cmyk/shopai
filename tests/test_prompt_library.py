"""Tests for the centralized PromptLibrary."""
import pytest


def _fresh_library():
    """Build a fresh library so version registration tests don't share state."""
    from core.system.prompt_library import PromptLibrary
    return PromptLibrary()


def _template(name="t1", version=1, system="sys", template="ask {x}",
              placeholders=None, role="general"):
    from core.system.prompt_library import PromptTemplate
    return PromptTemplate(
        name=name,
        version=version,
        purpose="test",
        system=system,
        template=template,
        placeholders=placeholders if placeholders is not None else ["x"],
        role=role,
    )


# ── PromptTemplate.render ────────────────────────────────────


class TestRender:
    def test_substitutes_placeholder(self):
        t = _template(template="ask {x}")
        rendered = t.render(x="something")
        assert rendered.user == "ask something"

    def test_missing_placeholder_warned(self):
        t = _template(template="ask {x}")
        rendered = t.render()
        assert "missing placeholders" in rendered.user
        assert "x" in rendered.user

    def test_extra_kwargs_ignored(self):
        t = _template(template="ask {x}")
        rendered = t.render(x="hi", y="ignored")
        assert rendered.user == "ask hi"

    def test_render_carries_metadata(self):
        t = _template(name="alpha", version=3)
        rendered = t.render(x="ok")
        assert rendered.name == "alpha"
        assert rendered.version == 3
        assert rendered.system == "sys"

    def test_render_to_dict(self):
        t = _template()
        d = t.render(x="hi").to_dict()
        assert d["name"] == "t1"
        assert d["version"] == 1
        assert d["user"] == "ask hi"

    def test_template_to_dict(self):
        t = _template(name="x", version=2, role="reasoner")
        d = t.to_dict()
        assert d["name"] == "x"
        assert d["version"] == 2
        assert d["role"] == "reasoner"
        assert d["placeholders"] == ["x"]


# ── PromptLibrary registration ──────────────────────────────


class TestRegistration:
    def test_register_and_get(self):
        lib = _fresh_library()
        t = _template()
        lib.register(t)
        assert lib.get("t1") is t

    def test_register_no_name_raises(self):
        lib = _fresh_library()
        with pytest.raises(ValueError):
            lib.register(_template(name=""))

    def test_register_overwrites_same_version(self):
        lib = _fresh_library()
        t1 = _template(version=1, template="v1")
        t2 = _template(version=1, template="v2")
        lib.register(t1)
        lib.register(t2)
        # Same version → overwrite, no archival
        current = lib.get("t1")
        assert current is t2
        history = lib.history("t1")
        assert len(history) == 1

    def test_new_version_archives_old(self):
        lib = _fresh_library()
        v1 = _template(version=1, template="v1")
        v2 = _template(version=2, template="v2")
        lib.register(v1)
        lib.register(v2)
        # Current is v2
        assert lib.get("t1") is v2
        # v1 is in history
        assert lib.get("t1", version=1) is v1
        history = lib.history("t1")
        assert len(history) == 2
        assert [h.version for h in history] == [1, 2]

    def test_get_unknown_version_returns_none(self):
        lib = _fresh_library()
        lib.register(_template(version=1))
        assert lib.get("t1", version=99) is None

    def test_get_unknown_name(self):
        lib = _fresh_library()
        assert lib.get("ghost") is None

    def test_list_prompts_alphabetical(self):
        lib = _fresh_library()
        lib.register(_template(name="b"))
        lib.register(_template(name="a"))
        lib.register(_template(name="c"))
        names = [p.name for p in lib.list_prompts()]
        assert names == ["a", "b", "c"]


# ── Built-in prompts ─────────────────────────────────────────


class TestBuiltIns:
    def test_planner_prompt_present(self):
        from core.system.prompt_library import get_prompt
        p = get_prompt("planner.decompose_goal")
        assert p is not None
        assert "decompose" in p.purpose.lower() or "step" in p.purpose.lower()
        assert "goal_what" in p.placeholders

    def test_planner_prompt_renders(self):
        from core.system.prompt_library import render_prompt
        rendered = render_prompt(
            "planner.decompose_goal",
            goal_what="Improve engine.pricing",
            context_block="",
        )
        assert rendered is not None
        assert "engine.pricing" in rendered.user
        assert "JSON" in rendered.system

    def test_reflection_prompt_present(self):
        from core.system.prompt_library import get_prompt
        p = get_prompt("reflection.summarize_episodes")
        assert p is not None
        assert "lessons" in p.schema_hint.lower()

    def test_imagination_prompt_present(self):
        from core.system.prompt_library import get_prompt
        p = get_prompt("imagination.evaluate_step")
        assert p is not None
        assert "step_description" in p.placeholders

    def test_theory_of_mind_prompt_present(self):
        from core.system.prompt_library import get_prompt
        p = get_prompt("theory_of_mind.predict_response")
        assert p is not None
        assert "agent_name" in p.placeholders
        assert "action" in p.placeholders

    def test_curiosity_prompt_present(self):
        from core.system.prompt_library import get_prompt
        p = get_prompt("curiosity.pick_target")
        assert p is not None

    def test_decision_pricing_prompt_present(self):
        from core.system.prompt_library import get_prompt
        p = get_prompt("decision.pricing_recommendation")
        assert p is not None
        assert "price" in p.placeholders

    def test_mind_think_prompt_present(self):
        from core.system.prompt_library import get_prompt
        p = get_prompt("mind.think")
        assert p is not None

    def test_all_built_ins_have_versions(self):
        from core.system.prompt_library import BUILT_IN_PROMPTS
        for tmpl in BUILT_IN_PROMPTS:
            assert tmpl.version >= 1
            assert tmpl.purpose
            assert tmpl.system
            assert tmpl.template

    def test_all_built_ins_have_unique_names(self):
        from core.system.prompt_library import BUILT_IN_PROMPTS
        names = [t.name for t in BUILT_IN_PROMPTS]
        assert len(names) == len(set(names))


# ── Shortcut helpers ─────────────────────────────────────────


class TestShortcuts:
    def test_render_prompt_shortcut(self):
        from core.system.prompt_library import render_prompt
        rendered = render_prompt(
            "planner.decompose_goal",
            goal_what="X",
            context_block="",
        )
        assert rendered is not None
        assert rendered.name == "planner.decompose_goal"

    def test_render_unknown_returns_none(self):
        from core.system.prompt_library import render_prompt
        assert render_prompt("ghost.prompt") is None

    def test_get_library_singleton(self):
        from core.system import prompt_library as mod
        mod._library = None
        a = mod.get_library()
        b = mod.get_library()
        assert a is b

    def test_library_loads_built_ins_on_init(self):
        from core.system import prompt_library as mod
        mod._library = None
        lib = mod.get_library()
        assert lib.get("planner.decompose_goal") is not None
        assert lib.get("reflection.summarize_episodes") is not None
