"""Model Worker System — routes every task to the right local model.

Models are WORKERS, not bosses. The AI brain decides WHAT to do,
models do the HOW.

Role assignment:
  ANALYZER (Mistral)  — evaluate, score, compare, detect patterns
  WORKER (Qwen)       — calculate, process, transform, extract
  CREATOR (LLaMA)     — write descriptions, generate content, brainstorm
  LEARNER (any)       — pattern detection, rule generation, simulation

Every task:
  1. Classify task type
  2. Route to best model
  3. Execute with data context
  4. Record result in memory
  5. Learn from outcome
"""
from __future__ import annotations
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("model.workers")


ROLE_MODELS = {
    "analyzer": {"model": "mistral", "tasks": [
        "evaluate", "score", "compare", "detect", "analyze",
        "classify", "assess", "rank", "review", "audit",
    ]},
    "worker": {"model": "qwen", "tasks": [
        "calculate", "process", "transform", "extract", "parse",
        "format", "convert", "merge", "filter", "aggregate",
    ]},
    "creator": {"model": "llama", "tasks": [
        "write", "generate", "describe", "create", "brainstorm",
        "compose", "design", "suggest", "name", "title",
    ]},
    "learner": {"model": "mistral", "tasks": [
        "learn", "pattern", "rule", "simulate", "predict",
        "forecast", "optimize", "correlate", "cluster", "segment",
    ]},
}

TASK_TEMPLATES = {
    "analyze_product": {
        "role": "analyzer",
        "prompt": "Analyze this product: {name}, price ${price}, cost ${cost}. "
                  "Evaluate: margin quality, pricing strategy, market fit.",
        "data_keys": ["name", "price", "cost", "category"],
    },
    "write_description": {
        "role": "creator",
        "prompt": "Write a compelling product description for: {name}. "
                  "Category: {category}. Highlight benefits, not features.",
        "data_keys": ["name", "category", "price"],
    },
    "score_opportunity": {
        "role": "analyzer",
        "prompt": "Score this business opportunity (1-10): {description}. "
                  "Consider: market size, competition, margin potential.",
        "data_keys": ["description", "market_size", "competition"],
    },
    "generate_tags": {
        "role": "creator",
        "prompt": "Generate SEO tags for: {name} in {category} category. "
                  "Return comma-separated tags, max 10.",
        "data_keys": ["name", "category"],
    },
    "forecast_demand": {
        "role": "learner",
        "prompt": "Based on this data, forecast next 30 day demand: "
                  "current inventory={inventory}, price=${price}, "
                  "trend={trend}.",
        "data_keys": ["inventory", "price", "trend"],
    },
    "pricing_decision": {
        "role": "analyzer",
        "prompt": "Current price: ${price}, cost: ${cost}, margin: {margin}%. "
                  "Competitor avg: ${comp_price}. Recommend: keep/raise/lower and why.",
        "data_keys": ["price", "cost", "margin", "comp_price"],
    },
    "customer_message": {
        "role": "creator",
        "prompt": "Write a {message_type} email for customer segment: {segment}. "
                  "Store sells: {store_category}. Be personal and actionable.",
        "data_keys": ["message_type", "segment", "store_category"],
    },
    "competitive_analysis": {
        "role": "analyzer",
        "prompt": "Analyze competitive position: our avg price ${our_price}, "
                  "competitor avg ${comp_price}. {advantages}. Recommend strategy.",
        "data_keys": ["our_price", "comp_price", "advantages"],
    },
}


class ModelWorkerSystem:
    """Routes tasks to the right model with data context."""

    def __init__(self) -> None:
        self._llm = None
        self._task_log: list[dict] = []
        self._model_stats: dict[str, dict] = {
            "analyzer": {"tasks": 0, "success": 0, "total_time": 0},
            "worker": {"tasks": 0, "success": 0, "total_time": 0},
            "creator": {"tasks": 0, "success": 0, "total_time": 0},
            "learner": {"tasks": 0, "success": 0, "total_time": 0},
        }

    def _get_llm(self):
        if not self._llm:
            try:
                from core.system.llm_adapter import get_llm
                self._llm = get_llm()
            except Exception as exc:
                logger.debug("ModelWorkers LLM init failed: %s", exc)
        return self._llm

    def execute_task(self, task_name: str, data: dict,
                     store_id: str = "") -> dict[str, Any]:
        """Execute a task by routing to the right model."""
        start = time.monotonic()

        # Get template
        template = TASK_TEMPLATES.get(task_name)
        if not template:
            return self._fallback_execute(task_name, data)

        role = template["role"]
        model_info = ROLE_MODELS.get(role, ROLE_MODELS["worker"])

        # Build prompt from template + data
        prompt = template["prompt"]
        for key in template["data_keys"]:
            val = str(data.get(key, "unknown"))
            prompt = prompt.replace("{" + key + "}", val)

        # Add memory context
        memory_context = self._get_memory_context(task_name, data)
        if memory_context:
            prompt += " Past experience: {}".format(memory_context)

        # Execute via LLM
        llm = self._get_llm()
        result = {}
        if llm:
            try:
                response = llm.ask(prompt, role=role)
                result = {
                    "response": response,
                    "model": model_info["model"],
                    "role": role,
                    "success": True,
                }
            except Exception as exc:
                result = {
                    "response": self._heuristic_response(task_name, data),
                    "model": "heuristic",
                    "role": role,
                    "success": True,
                    "fallback": True,
                }
        else:
            # No LLM available — use heuristic
            result = {
                "response": self._heuristic_response(task_name, data),
                "model": "heuristic",
                "role": role,
                "success": True,
                "fallback": True,
            }

        elapsed = time.monotonic() - start
        result["duration_s"] = round(elapsed, 3)
        result["task"] = task_name

        # Record
        self._record_task(task_name, role, data, result, store_id)
        self._model_stats[role]["tasks"] += 1
        if result.get("success"):
            self._model_stats[role]["success"] += 1
        self._model_stats[role]["total_time"] += elapsed

        return result

    def classify_and_execute(self, description: str, data: dict,
                             store_id: str = "") -> dict[str, Any]:
        """Auto-classify a task description and route to best model."""
        desc_lower = description.lower()

        # Find best role by keyword matching
        best_role = "worker"
        best_score = 0
        for role, info in ROLE_MODELS.items():
            score = sum(1 for t in info["tasks"] if t in desc_lower)
            if score > best_score:
                best_score = score
                best_role = role

        # Find closest template
        best_template = None
        for name, tmpl in TASK_TEMPLATES.items():
            if tmpl["role"] == best_role:
                best_template = name
                break

        if best_template:
            return self.execute_task(best_template, data, store_id)

        return self._fallback_execute(description, data)

    def batch_execute(self, tasks: list[dict],
                      store_id: str = "") -> dict[str, Any]:
        """Execute multiple tasks, routing each to the best model."""
        results = []
        for task in tasks:
            name = task.get("task", task.get("name", ""))
            data = task.get("data", {})
            r = self.execute_task(name, data, store_id)
            results.append(r)
        return {
            "total": len(results),
            "success": sum(1 for r in results if r.get("success")),
            "by_role": {role: stats["tasks"]
                        for role, stats in self._model_stats.items()},
            "results": results,
        }

    @staticmethod
    def _get_memory_context(task_name: str, data: dict) -> str:
        try:
            from core.memory.intelligence import get_memory_intelligence
            mi = get_memory_intelligence()
            rules = mi.get_rules(task_name.split("_")[0])
            if rules:
                top = rules[0].get("content", {})
                if isinstance(top, dict):
                    return top.get("rule", "")[:80]
        except Exception as exc:
            logger.debug("ModelWorkers rule retrieval failed: %s", exc)
        return ""

    @staticmethod
    def _heuristic_response(task_name: str, data: dict) -> str:
        """Fallback heuristic response when no LLM available."""
        if task_name == "analyze_product":
            from utils.finance import margin as _margin
            price = float(data.get("price", 0))
            cost = float(data.get("cost", 0))
            margin = _margin(price, cost)
            if margin > 0.5:
                return "High margin product ({:.0%}). Good profit potential. Consider promotion.".format(margin)
            elif margin > 0.2:
                return "Moderate margin ({:.0%}). Standard pricing. Monitor competitors.".format(margin)
            else:
                return "Low margin ({:.0%}). Consider raising price or reducing cost.".format(margin)

        elif task_name == "write_description":
            name = data.get("name", "Product")
            cat = data.get("category", "")
            return "Discover the {} — premium quality {} for your everyday needs.".format(name, cat)

        elif task_name == "generate_tags":
            name = data.get("name", "")
            words = [w.lower() for w in name.split() if len(w) > 3][:5]
            cat = data.get("category", "").lower()
            if cat:
                words.append(cat)
            return ", ".join(words)

        elif task_name == "pricing_decision":
            margin = float(data.get("margin", 30))
            if margin > 50:
                return "Keep price. Margin is healthy at {:.0f}%.".format(margin)
            elif margin > 20:
                return "Consider small increase. Margin at {:.0f}%.".format(margin)
            else:
                return "Raise price urgently. Margin only {:.0f}%.".format(margin)

        return "Task {} completed with heuristic.".format(task_name)

    def _fallback_execute(self, task_name: str, data: dict) -> dict:
        return {
            "response": self._heuristic_response(task_name, data),
            "model": "heuristic",
            "role": "worker",
            "task": task_name,
            "success": True,
            "fallback": True,
        }

    @staticmethod
    def _record_task(task_name, role, data, result, store_id):
        try:
            from core.data.architecture import get_data_architecture
            da = get_data_architecture()
            da.capture("tool_usage", {
                "tool_name": "model_{}".format(role),
                "engine_name": result.get("model", "unknown"),
                "input_size": len(str(data)),
                "output_size": len(str(result.get("response", ""))),
                "success": result.get("success", False),
            }, source="model_worker", store_id=store_id, score=4.0 if result.get("success") else 2.0)
        except Exception as exc:
            logger.debug("ModelWorkers DA capture failed: %s", exc)

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_tasks": sum(s["tasks"] for s in self._model_stats.values()),
            "by_role": dict(self._model_stats),
            "task_templates": len(TASK_TEMPLATES),
        }


_instance = None
def get_model_workers():
    global _instance
    if _instance is None:
        _instance = ModelWorkerSystem()
    return _instance
