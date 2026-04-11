"""Tests for audit-pass-35 fixes — defensive hardening across
all 7 domain agent planners (product, marketing, content,
finance, operations, customer, research).

Each planner had the same 4 anti-patterns:

  1. ``goal.lower()`` with no isinstance guard — None goal
     crashed the planner with AttributeError before it could
     produce a plan.

  2. ``context.get(...)`` / ``constraints.get(...)`` with no
     isinstance guard — same crash mode for None caller args.

  3. ``ENGINE_CAPABILITIES[engine_name]["provides"][0]``
     direct dict + index access (in 4 of 7 planners). If a
     ``GOAL_ENGINE_MAP`` entry pointed at an engine missing
     from CAPABILITIES, KeyError. The other 3 used
     ``["provides", ["unknown"]][0]`` which still IndexErrors
     when ``provides`` is an empty list (still buggy, just
     less obvious).

  4. ``_build_engine_input`` fallback returning
     ``{"data": context}`` for unknown engine names — leaked
     the entire caller context (potentially auth tokens /
     customer PII / api keys) into the engine input. This
     was a security smell, not just a defensive gap.

The fix pattern is identical in all 7 files, so this audit
pass uses parametrized tests that drive each planner through
the same set of malformed / hostile inputs.
"""
import importlib

import pytest


PLANNER_MODULES = [
    "agents.product.planner",
    "agents.marketing.planner",
    "agents.content.planner",
    "agents.finance.planner",
    "agents.operations.planner",
    "agents.customer.planner",
    "agents.research.planner",
]


# ── Defensive caller-arg coercion ───────────────────────────


@pytest.mark.parametrize("module_path", PLANNER_MODULES)
class TestDefensiveCallerArgs:
    def test_none_goal_does_not_crash(self, module_path):
        """Regression: ``goal.lower()`` used to crash with
        AttributeError when goal was None."""
        mod = importlib.import_module(module_path)
        # Should not raise.
        plan = mod.create_plan(goal=None, context={}, constraints={})
        assert isinstance(plan, dict)
        assert "engines" in plan

    def test_none_context_does_not_crash(self, module_path):
        mod = importlib.import_module(module_path)
        plan = mod.create_plan(goal="full", context=None, constraints={})
        assert isinstance(plan, dict)
        assert "engines" in plan

    def test_none_constraints_does_not_crash(self, module_path):
        mod = importlib.import_module(module_path)
        plan = mod.create_plan(goal="full", context={}, constraints=None)
        assert isinstance(plan, dict)
        assert "engines" in plan

    def test_non_string_goal_does_not_crash(self, module_path):
        mod = importlib.import_module(module_path)
        plan = mod.create_plan(goal=12345, context={}, constraints={})
        assert isinstance(plan, dict)


# ── Engine capability lookup safety ─────────────────────────


@pytest.mark.parametrize("module_path", PLANNER_MODULES)
class TestEngineCapabilityLookup:
    def test_missing_capability_does_not_crash(self, module_path, monkeypatch):
        """Regression: a goal mapping that points at an engine
        missing from ``ENGINE_CAPABILITIES`` used to crash the
        planner with KeyError.

        Stub the goal map to point at an unknown engine and
        confirm planning still produces a step with
        ``purpose == "unknown"``.
        """
        mod = importlib.import_module(module_path)
        monkeypatch.setattr(
            mod, "GOAL_ENGINE_MAP",
            {"audit_test_goal": ["nonexistent_engine_xyz"]},
        )
        plan = mod.create_plan(
            goal="audit_test_goal",
            context={},
            constraints={},
        )
        assert isinstance(plan, dict)
        steps = plan.get("engines", [])
        assert any(
            s.get("name") == "nonexistent_engine_xyz"
            and s.get("purpose") == "unknown"
            for s in steps
        )

    def test_empty_provides_list_does_not_crash(self, module_path, monkeypatch):
        """Regression: ``["provides", ["unknown"]][0]`` only
        defended the missing-key case. An entry with
        ``provides=[]`` still IndexErrored."""
        mod = importlib.import_module(module_path)
        monkeypatch.setattr(
            mod, "GOAL_ENGINE_MAP",
            {"audit_test_goal": ["broken_capability_engine"]},
        )
        # Inject a capability entry whose provides list is empty.
        new_caps = dict(mod.ENGINE_CAPABILITIES)
        new_caps["broken_capability_engine"] = {
            "provides": [],
            "requires": [],
            "optional": [],
        }
        monkeypatch.setattr(mod, "ENGINE_CAPABILITIES", new_caps)

        plan = mod.create_plan(
            goal="audit_test_goal",
            context={},
            constraints={},
        )
        steps = plan.get("engines", [])
        assert any(
            s.get("name") == "broken_capability_engine"
            and s.get("purpose") == "unknown"
            for s in steps
        )


# ── Context-leak fix ────────────────────────────────────────


@pytest.mark.parametrize("module_path", PLANNER_MODULES)
class TestContextLeakFix:
    def test_unknown_engine_does_not_leak_context(self, module_path, monkeypatch):
        """Regression: the ``_build_engine_input`` fallback used
        to return ``{"data": context}`` for unrecognised engine
        names, leaking caller context (api keys, customer PII,
        secrets) into the engine input.

        After audit pass 35 the fallback returns ``{"data": {}}``.
        """
        mod = importlib.import_module(module_path)
        monkeypatch.setattr(
            mod, "GOAL_ENGINE_MAP",
            {"audit_test_goal": ["nonexistent_engine_xyz"]},
        )

        sensitive_context = {
            "api_key": "sk-leaked-token-do-not-share",
            "customer_pii": [{"email": "alice@example.com"}],
            "shopify_token": "shpat_secret_value",
        }
        plan = mod.create_plan(
            goal="audit_test_goal",
            context=sensitive_context,
            constraints={},
        )
        # Find the unknown-engine step
        unknown_step = next(
            (s for s in plan["engines"]
             if s.get("name") == "nonexistent_engine_xyz"),
            None,
        )
        assert unknown_step is not None
        engine_input_data = unknown_step["input"].get("data", {})
        assert "api_key" not in engine_input_data
        assert "customer_pii" not in engine_input_data
        assert "shopify_token" not in engine_input_data
        assert engine_input_data == {}
