"""Chain of Thought Reasoning — structured multi-step thinking.

Makes AI thinking transparent and debuggable.
Each decision shows the full reasoning chain.
"""
from __future__ import annotations
import threading as _threading
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("brain.chain_of_thought")


class ChainOfThought:
    """Structured reasoning with visible thought chains."""

    def __init__(self) -> None:
        self._chains: list[dict] = []

    def reason(self, question: str, context: dict) -> dict[str, Any]:
        """Reason through a question step by step."""
        steps = []

        # Step 1: Understand the question
        steps.append({
            "step": 1, "type": "understand",
            "thought": "Question: {}".format(question),
            "data_available": list(context.keys()),
        })

        # Step 2: Gather relevant facts
        facts = self._extract_facts(context)
        steps.append({
            "step": 2, "type": "gather_facts",
            "thought": "Found {} relevant facts".format(len(facts)),
            "facts": facts[:5],
        })

        # Step 3: Apply rules
        applicable_rules = self._find_rules(question, context)
        steps.append({
            "step": 3, "type": "apply_rules",
            "thought": "{} rules apply".format(len(applicable_rules)),
            "rules": applicable_rules[:3],
        })

        # Step 4: Consider alternatives
        alternatives = self._consider_alternatives(question, facts)
        steps.append({
            "step": 4, "type": "alternatives",
            "thought": "{} alternatives considered".format(len(alternatives)),
            "alternatives": alternatives,
        })

        # Step 5: Reach conclusion
        conclusion = self._conclude(facts, applicable_rules, alternatives)
        steps.append({
            "step": 5, "type": "conclude",
            "thought": conclusion["reasoning"],
            "answer": conclusion["answer"],
            "confidence": conclusion["confidence"],
        })

        chain = {
            "question": question,
            "steps": steps,
            "answer": conclusion["answer"],
            "confidence": conclusion["confidence"],
            "reasoning_length": len(steps),
            "timestamp": time.time(),
        }
        self._chains.append(chain)
        return chain

    @staticmethod
    def _extract_facts(context: dict) -> list[str]:
        facts = []
        products = context.get("products", [])
        if products:
            facts.append("{} products in catalog".format(len(products)))
            prices = [float(p.get("price", 0)) for p in products if p.get("price")]
            if prices:
                facts.append("Price range: ${:.2f} - ${:.2f}".format(min(prices), max(prices)))
            no_img = sum(1 for p in products if not (p.get("images") or p.get("image") or p.get("image_url")))
            if no_img:
                facts.append("{} products without images".format(no_img))

        orders = context.get("orders", context.get("order_data", []))
        facts.append("{} orders recorded".format(len(orders)))

        health = context.get("health_score", 0)
        if health:
            facts.append("Store health: {}".format(health))
        return facts

    @staticmethod
    def _find_rules(question: str, context: dict) -> list[str]:
        rules = []
        try:
            from core.memory.unified_memory import get_unified_memory
            mi = get_unified_memory().get_memory_intelligence()
            learned = mi.get_rules()
            for r in learned[:5]:
                rc = r.get("content", {})
                if isinstance(rc, dict):
                    rules.append(rc.get("rule", str(rc)[:60]))
        except Exception as exc:
            logger.debug("learned rules retrieval failed: %s", exc)
        return rules

    @staticmethod
    def _consider_alternatives(question: str, facts: list) -> list[dict]:
        alts = [
            {"option": "take_action", "pros": "immediate impact", "cons": "may be premature"},
            {"option": "gather_more_data", "pros": "better decision", "cons": "delayed action"},
            {"option": "small_experiment", "pros": "low risk test", "cons": "slower results"},
        ]
        return alts

    @staticmethod
    def _conclude(facts: list, rules: list, alternatives: list) -> dict:
        # Simple heuristic conclusion
        if rules:
            return {
                "answer": "Follow learned rules ({} available)".format(len(rules)),
                "reasoning": "Rules exist from past experience — use them",
                "confidence": min(0.9, 0.5 + len(rules) * 0.1),
            }
        if len(facts) >= 3:
            return {
                "answer": "Enough data to act — run small experiment",
                "reasoning": "{} facts available, experiment is safe".format(len(facts)),
                "confidence": 0.6,
            }
        return {
            "answer": "Gather more data before deciding",
            "reasoning": "Insufficient information ({} facts)".format(len(facts)),
            "confidence": 0.3,
        }

    def get_chains(self, limit: int = 10) -> list[dict]:
        return self._chains[-limit:]

    def get_stats(self) -> dict[str, Any]:
        return {"total_chains": len(self._chains)}


_instance = None
_instance_lock = _threading.Lock()

def get_chain_of_thought():
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ChainOfThought()
    return _instance
