"""Tests for audit-pass-32 fixes — defensive hardening across all 7
domain agent executors (product, marketing, content, finance,
operations, customer, research).

  Each of the 7 executors had the SAME 3 anti-patterns:
    1. step["name"] / step["input"] direct dict access — KeyError
       on a malformed step entry.
    2. result.get(...) directly after engine.run(...) — if engine
       returned None (a buggy stub), AttributeError.
    3. result.get("error", {}).get("reason", ...) — the
       dict.get(k, {}) antipattern; an explicit error=None bled
       through to a .get() crash.

  The fix is identical in all 7 files, so this audit pass uses a
  parametrized test that drives each executor through the same
  set of malformed inputs.
"""
import importlib

import pytest


AGENT_MODULES = [
    "agents.product.executor",
    "agents.marketing.executor",
    "agents.content.executor",
    "agents.finance.executor",
    "agents.operations.executor",
    "agents.customer.executor",
    "agents.research.executor",
]


def _patch_engine(monkeypatch, module_path: str, engine_factory):
    """Inject a fake engine into the global registry.

    After audit pass 33, all 7 executors use
    `engines.registry.get_engine` (the Lego principle was
    enforced — no more local `_get_engine` helpers with
    hardcoded engine maps). One patch point covers every
    executor.
    """
    import engines.registry as reg
    monkeypatch.setattr(reg, "get_engine", lambda name: engine_factory())
    importlib.import_module(module_path)


# ── Defensive step shape ────────────────────────────────────


@pytest.mark.parametrize("module_path", AGENT_MODULES)
class TestDefensiveStepShape:
    def test_malformed_step_entries_skipped(self, module_path, monkeypatch):
        """Regression: previously a step without 'name' or 'input'
        crashed the entire execution with KeyError."""
        mod = importlib.import_module(module_path)

        class _StubEngine:
            def run(self, inp):
                return {"status": "success", "data": {}, "error": None}

        _patch_engine(monkeypatch, module_path, _StubEngine)

        result = mod.execute_plan(
            plan={
                "engines": [
                    None,                                # not a dict
                    "string-step",                       # also not a dict
                    {"input": {}},                       # missing name
                    {"name": ""},                        # empty name
                    {"name": "real_engine", "input": {}},  # OK
                ]
            },
            context={},
        )
        # Only the one valid step ran
        assert result["completed_steps"] == 1
        assert result["failed_steps"] == 0
        assert "real_engine" in result["engine_results"]

    def test_non_dict_step_input_coerced(self, module_path, monkeypatch):
        mod = importlib.import_module(module_path)
        captured = {}

        class _CapturingEngine:
            def run(self, inp):
                captured["input"] = inp
                return {"status": "success", "data": {}, "error": None}

        _patch_engine(monkeypatch, module_path, _CapturingEngine)

        mod.execute_plan(
            plan={"engines": [{"name": "x", "input": "not a dict"}]},
            context={},
        )
        # Step input was coerced to {} so the engine got a real
        # dict instead of the raw string.
        assert captured["input"] == {}


# ── Engine returns None ─────────────────────────────────────


@pytest.mark.parametrize("module_path", AGENT_MODULES)
class TestEngineReturnsNone:
    def test_none_result_does_not_crash(self, module_path, monkeypatch):
        """Regression: engine.run() returning None made the next
        result.get(...) call crash with AttributeError."""
        mod = importlib.import_module(module_path)

        class _NoneEngine:
            def run(self, inp):
                return None  # buggy stub

        _patch_engine(monkeypatch, module_path, _NoneEngine)

        result = mod.execute_plan(
            plan={"engines": [{"name": "x", "input": {}}]},
            context={},
        )
        # Did not crash; the step is recorded as failed
        assert result["failed_steps"] == 1
        assert result["completed_steps"] == 0


# ── Engine returns error=None (present-but-None) ────────────


@pytest.mark.parametrize("module_path", AGENT_MODULES)
class TestEnginePresentButNoneError:
    def test_present_but_none_error_does_not_crash(self, module_path, monkeypatch):
        """Regression: result.get("error", {}).get("reason", ...)
        crashed when error was explicitly None (the dict.get(k, {})
        antipattern)."""
        mod = importlib.import_module(module_path)

        class _BadErrorEngine:
            def run(self, inp):
                return {"status": "fail", "error": None}

        _patch_engine(monkeypatch, module_path, _BadErrorEngine)
        # Should not raise
        result = mod.execute_plan(
            plan={"engines": [{"name": "x", "input": {}}]},
            context={},
        )
        assert result["failed_steps"] == 1

    def test_string_error_does_not_crash(self, module_path, monkeypatch):
        mod = importlib.import_module(module_path)

        class _StringErrorEngine:
            def run(self, inp):
                return {"status": "fail", "error": "raw error message"}

        _patch_engine(monkeypatch, module_path, _StringErrorEngine)
        result = mod.execute_plan(
            plan={"engines": [{"name": "x", "input": {}}]},
            context={},
        )
        assert result["failed_steps"] == 1


# ── Enrichment function raises ───────────────────────────────


@pytest.mark.parametrize("module_path", AGENT_MODULES)
class TestEnrichmentRaises:
    def test_enrichment_exception_does_not_crash_plan(self, module_path, monkeypatch):
        """Regression: a buggy ``_enrich_from_dependencies`` used
        to take down the entire plan. Audit pass 34 moved
        enrichment behind a try/except in the shared base so a
        single bad step is recorded as failed and the runner
        moves on."""
        mod = importlib.import_module(module_path)

        class _OkEngine:
            def run(self, inp):
                return {"status": "success", "data": {}, "error": None}

        _patch_engine(monkeypatch, module_path, _OkEngine)

        # Force the agent's enrichment to blow up by handing it
        # a non-list ``depends_on`` it can't iterate cleanly.
        # Every agent's enrichment opens with ``for dep_name in
        # dependencies`` — passing an int triggers TypeError.
        result = mod.execute_plan(
            plan={
                "engines": [
                    {"name": "x", "input": {}, "depends_on": 12345},
                    {"name": "y", "input": {}},  # this one should still run
                ],
            },
            context={},
        )
        # The bad step is failed, the good step ran.
        assert result["completed_steps"] == 1
        assert result["failed_steps"] == 1
        assert "y" in result["engine_results"]


# ── Engine raises ────────────────────────────────────────────


@pytest.mark.parametrize("module_path", AGENT_MODULES)
class TestEngineRaises:
    def test_exception_captured_with_type(self, module_path, monkeypatch):
        mod = importlib.import_module(module_path)

        class _BoomEngine:
            def run(self, inp):
                raise ValueError("kaboom")

        _patch_engine(monkeypatch, module_path, _BoomEngine)
        result = mod.execute_plan(
            plan={"engines": [{"name": "x", "input": {}}]},
            context={},
        )
        assert result["failed_steps"] == 1
        # Failure entry includes the engine name
        details = result["step_details"][0]
        assert details["engine"] == "x"
        assert details["success"] is False
