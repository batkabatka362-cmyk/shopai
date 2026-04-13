"""EngineKernel — the internal architecture every engine SHOULD have.

Current engines: 1 file (engine.py) with prompt templates.
EngineKernel vision: modules + code + logic + rules + data + knowledge.

Each engine should have:
  - modules/: Independent computation modules (no AI needed)
  - rules/: Declarative business rules (YAML/Python)
  - data/: Engine-specific learned data
  - knowledge/: Domain knowledge base

EngineKernel provides the base framework for building rich engines.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("engines.kernel")


class ModuleBase:
    """Base class for engine computation modules."""

    def __init__(self, name: str) -> None:
        self.name = name

    def compute(self, data: dict[str, Any]) -> dict[str, Any]:
        """Override in subclass. Pure computation, no AI."""
        return {}


class RuleBase:
    """Base class for engine business rules."""

    def __init__(self) -> None:
        self._rules: list[dict[str, Any]] = []

    def add_rule(self, name: str, condition: dict[str, Any], action: str, priority: int = 5) -> None:
        self._rules.append({"name": name, "condition": condition, "action": action, "priority": priority})
        self._rules.sort(key=lambda r: r["priority"])

    def evaluate(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Evaluate all rules against data. Returns triggered rules."""
        triggered = []
        for rule in self._rules:
            if self._check_condition(rule["condition"], data):
                triggered.append({"rule": rule["name"], "action": rule["action"], "priority": rule["priority"]})
        return triggered

    def _check_condition(self, condition: dict[str, Any], data: dict[str, Any]) -> bool:
        """Check if all conditions are met."""
        for key, expected in condition.items():
            actual = data.get(key)
            if actual is None:
                return False
            if isinstance(expected, dict):
                for op, val in expected.items():
                    if op == "gt" and not (actual > val):
                        return False
                    if op == "lt" and not (actual < val):
                        return False
                    if op == "gte" and not (actual >= val):
                        return False
                    if op == "eq" and actual != val:
                        return False
            elif actual != expected:
                return False
        return True


class KnowledgeBase:
    """Base class for engine domain knowledge."""

    def __init__(self) -> None:
        self._knowledge: dict[str, Any] = {}

    def add(self, key: str, value: Any) -> None:
        self._knowledge[key] = value

    def query(self, key: str, default: Any = None) -> Any:
        return self._knowledge.get(key, default)

    def get_all(self) -> dict[str, Any]:
        return dict(self._knowledge)


class EngineMemory:
    """Engine-specific learned data storage."""

    def __init__(self) -> None:
        self._patterns: list[dict[str, Any]] = []
        self._baselines: dict[str, float] = {}

    def record_success(self, input_data: dict[str, Any], output: dict[str, Any]) -> None:
        self._patterns.append({"type": "success", "input": input_data, "output": output})
        if len(self._patterns) > 500:
            self._patterns = self._patterns[-500:]

    def record_failure(self, input_data: dict[str, Any], error: str) -> None:
        self._patterns.append({"type": "failure", "input": input_data, "error": error})

    def get_success_patterns(self) -> list[dict[str, Any]]:
        return [p for p in self._patterns if p["type"] == "success"]

    def set_baseline(self, metric: str, value: float) -> None:
        self._baselines[metric] = value

    def get_baselines(self) -> dict[str, float]:
        return dict(self._baselines)


class EngineKernel:
    """Framework for building rich engines with modules, rules, data, knowledge.

    Usage:
        # In a specific engine (e.g., pricing engine):
        class PricingKernel(EngineKernel):
            def __init__(self):
                super().__init__("pricing")
                self.add_module("margin_calc", MarginCalculator())
                self.add_module("demand_est", DemandEstimator())
                self.add_rule("min_margin", {"margin": {"lt": 0}}, "reject")
                self.add_knowledge("charm_pricing", "+4% conversion")
    """

    def __init__(self, engine_name: str) -> None:
        self.engine_name = engine_name
        self.modules: dict[str, ModuleBase] = {}
        self.rules = RuleBase()
        self.knowledge = KnowledgeBase()
        self.memory = EngineMemory()

    def add_module(self, name: str, module: ModuleBase) -> None:
        self.modules[name] = module

    def add_rule(self, name: str, condition: dict[str, Any], action: str, priority: int = 5) -> None:
        self.rules.add_rule(name, condition, action, priority)

    def add_knowledge(self, key: str, value: Any) -> None:
        self.knowledge.add(key, value)

    def process(self, data: dict[str, Any]) -> dict[str, Any]:
        """Run full kernel processing: modules → rules → knowledge → AI synthesis.

        1. Run all computation modules (pure math, no AI)
        2. Evaluate business rules
        3. Query domain knowledge
        4. Return enriched result for AI synthesis
        """
        result: dict[str, Any] = {"engine": self.engine_name}

        # Step 1: Run modules
        module_results = {}
        for name, module in self.modules.items():
            try:
                module_results[name] = module.compute(data)
            except Exception as exc:
                module_results[name] = {"error": str(exc)}
        result["module_outputs"] = module_results

        # Step 2: Evaluate rules
        all_module_data = {**data}
        for mr in module_results.values():
            if isinstance(mr, dict):
                all_module_data.update(mr)
        result["triggered_rules"] = self.rules.evaluate(all_module_data)

        # Step 3: Query relevant knowledge
        result["knowledge"] = self.knowledge.get_all()

        # Step 4: Check for blocking rules
        blocked = [r for r in result["triggered_rules"] if r["action"] in ("reject", "block")]
        result["blocked"] = len(blocked) > 0
        result["block_reasons"] = [r["rule"] for r in blocked]

        return result

    def get_status(self) -> dict[str, Any]:
        return {
            "engine": self.engine_name,
            "modules": list(self.modules.keys()),
            "rules": len(self.rules._rules),
            "knowledge_entries": len(self.knowledge._knowledge),
            "patterns_learned": len(self.memory._patterns),
        }
