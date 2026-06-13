"""Tests for ``core.capability_planner.llm_planner``.

The LLM planner wraps the deterministic planner with
semantic seed selection. These tests lock in:

  - LLM unavailable -> falls back to deterministic with note
  - LLM returns invalid response -> falls back with note
  - LLM returns valid seeds -> uses them for chain expansion
  - LLM hallucinates a name -> filtered out (validated
    against registry)
  - JSON extractor handles wrapped output (prose around
    array)
  - Composition walk + verification still appended
    (deterministic machinery reused)
"""
from __future__ import annotations

import pytest

from core.capability_registry import (
    Capability,
    CapabilityKind,
    register_capability,
)
from core.capability_registry.bootstrap import (
    reset_for_tests,
)
from core.capability_planner.llm_planner import (
    LLMPlanner,
    _parse_capability_list,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    reset_for_tests()
    yield
    reset_for_tests()


class FakeBackend:
    """Stand-in for ``OllamaBackend``. Tests construct it
    with a canned response."""

    def __init__(
        self,
        response_text: str = "",
        *,
        available: bool = True,
        raise_on_generate: bool = False,
    ):
        self._response = response_text
        self._available = available
        self._raise = raise_on_generate
        self.calls: list[dict] = []

    def is_available(self) -> bool:
        return self._available

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self._raise:
            raise RuntimeError("simulated backend error")
        return {"text": self._response}


# ── JSON parser ───────────────────────────────────────────


class TestParseList:

    def test_pure_json_array(self):
        text = '["a", "b", "c"]'
        assert _parse_capability_list(text) == ["a", "b", "c"]

    def test_prose_wrapped(self):
        text = "Here are the names: [\"x\", \"y\"]"
        assert _parse_capability_list(text) == ["x", "y"]

    def test_markdown_wrapped(self):
        text = '```json\n["one"]\n```'
        # The regex hunts inside the markdown; should find
        # the inner array
        assert _parse_capability_list(text) == ["one"]

    def test_filters_non_strings(self):
        text = '["a", 5, null, "b"]'
        # Only valid strings survive
        assert _parse_capability_list(text) == ["a", "b"]

    def test_empty_text(self):
        assert _parse_capability_list("") == []

    def test_no_brackets(self):
        assert _parse_capability_list("just words") == []

    def test_malformed_json(self):
        assert _parse_capability_list("[a, b]") == []


# ── Fallback paths ────────────────────────────────────────


class TestFallback:

    def _seed_registry(self):
        register_capability(Capability(
            name="x_engine",
            kind=CapabilityKind.ENGINE,
            description="x engine",
            when_to_use="use for x",
            module_path="m:x",
            composes_with=["x_apply"],
            tags=["x"],
        ))
        register_capability(Capability(
            name="x_apply",
            kind=CapabilityKind.APPLIER,
            description="x writer",
            when_to_use="pairs with x_engine",
            module_path="m:x_apply",
            composes_with=["x_engine"],
            audit_checks_closed=["x_check"],
            tags=["x"],
        ))
        register_capability(Capability(
            name="audit_store",
            kind=CapabilityKind.AUDIT,
            description="audit",
            when_to_use="verify",
            module_path="m:audit_store",
        ))

    def test_backend_unavailable_falls_back(self):
        self._seed_registry()
        planner = LLMPlanner(
            backend=FakeBackend(available=False),
            skip_bootstrap=True,
        )
        plan = planner.plan_for_goal("x")
        # Deterministic walker still produces a plan
        names = {s.capability_name for s in plan.steps}
        assert "x_engine" in names
        assert any(
            "LLM planner unavailable" in n for n in plan.notes
        )

    def test_backend_raise_falls_back_silently(self):
        self._seed_registry()
        planner = LLMPlanner(
            backend=FakeBackend(
                response_text="ignored",
                raise_on_generate=True,
            ),
            skip_bootstrap=True,
        )
        plan = planner.plan_for_goal("x")
        # Fell back -> deterministic seeds still found
        assert plan.steps
        assert any(
            "no valid seeds" in n.lower() or
            "fell back" in n.lower()
            for n in plan.notes
        )

    def test_empty_response_falls_back(self):
        self._seed_registry()
        planner = LLMPlanner(
            backend=FakeBackend(response_text=""),
            skip_bootstrap=True,
        )
        plan = planner.plan_for_goal("x")
        assert plan.steps  # deterministic backup ran

    def test_empty_goal_returns_empty_plan(self):
        self._seed_registry()
        planner = LLMPlanner(
            backend=FakeBackend(response_text='["x_engine"]'),
            skip_bootstrap=True,
        )
        plan = planner.plan_for_goal("")
        # Empty goal -> deterministic returns empty plan
        assert plan.steps == []


# ── LLM-driven happy path ─────────────────────────────────


class TestLLMSeedSelection:

    def _seed_registry(self):
        register_capability(Capability(
            name="store_design_engine",
            kind=CapabilityKind.ENGINE,
            description="design engine",
            when_to_use="theme + mobile",
            module_path="m:design",
            composes_with=["apply_design"],
        ))
        register_capability(Capability(
            name="apply_design",
            kind=CapabilityKind.APPLIER,
            description="writes theme files",
            when_to_use="pairs with engine",
            module_path="m:apply_design",
            audit_checks_closed=["design_tokens"],
            composes_with=["store_design_engine"],
        ))
        register_capability(Capability(
            name="audit_store",
            kind=CapabilityKind.AUDIT,
            description="audit",
            when_to_use="verify",
            module_path="m:audit_store",
        ))

    def test_llm_picks_seed_chain_expands(self):
        self._seed_registry()
        planner = LLMPlanner(
            backend=FakeBackend(
                response_text='["store_design_engine"]',
            ),
            skip_bootstrap=True,
        )
        plan = planner.plan_for_goal("mobile-app design")
        names = [s.capability_name for s in plan.steps]
        # LLM picked store_design_engine; chain walk expanded
        # to apply_design + audit_store verification
        assert "store_design_engine" in names
        assert "apply_design" in names
        assert "audit_store" in names
        # Note carries the LLM-picked seeds
        assert any(
            "LLM-driven planner picked seeds" in n
            for n in plan.notes
        )

    def test_llm_hallucinated_names_filtered(self):
        self._seed_registry()
        planner = LLMPlanner(
            backend=FakeBackend(
                response_text=(
                    '["store_design_engine", '
                    '"ghost_capability", '
                    '"another_ghost"]'
                ),
            ),
            skip_bootstrap=True,
        )
        plan = planner.plan_for_goal("design")
        names = {s.capability_name for s in plan.steps}
        # Hallucinated names absent
        assert "ghost_capability" not in names
        assert "another_ghost" not in names
        # Real one present + its chain
        assert "store_design_engine" in names
        # The notes' picked-seeds line ONLY lists real names
        seeds_note = next(
            n for n in plan.notes
            if "LLM-driven planner picked seeds" in n
        )
        assert "ghost" not in seeds_note

    def test_llm_all_hallucinations_falls_back(self):
        """When EVERY name is hallucinated, fall back to
        deterministic."""
        self._seed_registry()
        planner = LLMPlanner(
            backend=FakeBackend(
                response_text='["ghost", "ghost2"]',
            ),
            skip_bootstrap=True,
        )
        plan = planner.plan_for_goal("design")
        # Fell back -> deterministic substring match on
        # "design" found store_design_engine
        names = {s.capability_name for s in plan.steps}
        assert "store_design_engine" in names

    def test_llm_orchestrator_shortcut(self):
        """When the LLM picks (or its chain reveals) an
        orchestrator, the planner emits the single-CLI
        orchestrator path instead of per-step CLIs."""
        # Add an orchestrator that covers store_design_engine
        register_capability(Capability(
            name="design_orchestrator",
            kind=CapabilityKind.ORCHESTRATOR,
            description="all design steps",
            when_to_use="full design pipeline",
            module_path="m:design_orchestrator",
            composes_with=["store_design_engine",
                           "apply_design"],
            cli_commands=["shopai design-do-it-all"],
        ))
        self._seed_registry()
        planner = LLMPlanner(
            backend=FakeBackend(
                response_text=(
                    '["design_orchestrator"]'
                ),
            ),
            skip_bootstrap=True,
        )
        plan = planner.plan_for_goal("design overhaul")
        steps = {s.capability_name for s in plan.steps}
        assert "design_orchestrator" in steps
        # CLI sequence collapses to the orchestrator's CLI
        assert any(
            "shopai design-do-it-all" in c
            for c in plan.cli_sequence
        )


class TestPromptCatalogShape:
    """Sanity-check the catalog the LLM sees -- one line per
    capability, ``name: blurb`` shape."""

    def _seed_registry(self):
        register_capability(Capability(
            name="alpha",
            kind=CapabilityKind.ENGINE,
            description="aaa",
            when_to_use="alpha use",
            module_path="m:alpha",
        ))
        register_capability(Capability(
            name="beta",
            kind=CapabilityKind.APPLIER,
            description="bbb",
            when_to_use="beta use",
            module_path="m:beta",
        ))
        register_capability(Capability(
            name="audit_store",
            kind=CapabilityKind.AUDIT,
            description="audit",
            when_to_use="verify",
            module_path="m:audit_store",
        ))

    def test_catalog_has_one_line_per_capability(self):
        self._seed_registry()
        planner = LLMPlanner(
            backend=FakeBackend(),
            skip_bootstrap=True,
        )
        catalog = planner._build_compressed_catalog()
        assert "- alpha: alpha use" in catalog
        assert "- beta: beta use" in catalog

    def test_catalog_passed_to_backend(self):
        self._seed_registry()
        backend = FakeBackend(response_text='["alpha"]')
        planner = LLMPlanner(
            backend=backend, skip_bootstrap=True,
        )
        planner.plan_for_goal("any goal")
        # The backend received exactly one call with the
        # catalog embedded in the prompt
        assert len(backend.calls) == 1
        sent_prompt = backend.calls[0]["prompt"]
        assert "alpha: alpha use" in sent_prompt
        assert "beta: beta use" in sent_prompt
