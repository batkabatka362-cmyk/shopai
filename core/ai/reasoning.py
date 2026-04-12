"""AIReasoning — connects engines to real LLM intelligence.

Instead of hardcoded formulas, engines call AIReasoning to get
actual AI analysis, decisions, and creative output.

Works with: Ollama (local), or falls back to smart heuristics.

Usage in engines:
    from core.ai.reasoning import ai_reason
    result = ai_reason("pricing", products=products, competitors=competitors)
"""
from __future__ import annotations

import json
import os
import threading as _threading
import time
from typing import Any

from utils.finance import margin as _margin
from utils.logger import get_logger

logger = get_logger("ai.reasoning")

# Cache to avoid redundant LLM calls
_reasoning_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 300  # 5 minutes


class AIReasoning:
    """Central AI reasoning engine — wraps LLM calls for all engines."""

    def __init__(self) -> None:
        self._router = None
        self._ollama_url = os.environ.get("SHOPAI_OLLAMA_URL", "http://localhost:11434")
        self._available = None  # lazy check

    def _get_router(self):
        if self._router is None:
            try:
                from models.routing.model_router import ModelRouter
                self._router = ModelRouter()
            except Exception as exc:
                logger.debug("ModelRouter init failed: %s", exc)
        return self._router

    def is_llm_available(self) -> bool:
        """Check if any LLM backend is available."""
        if self._available is not None:
            return self._available

        # Try Ollama
        try:
            import urllib.request
            req = urllib.request.Request(f"{self._ollama_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                models = [m.get("name", "") for m in data.get("models", [])]
                self._available = len(models) > 0
                if self._available:
                    logger.info("LLM available via Ollama: %s", models)
                return self._available
        except Exception as exc:
            logger.debug("Ollama availability check failed: %s", exc)

        self._available = False
        return False

    # ── Main reasoning interface ─────────────────────────────

    def reason(self, task: str, role: str = "analyzer", **data: Any) -> dict[str, Any]:
        """Ask the AI to reason about a task with given data.

        Args:
            task: What to analyze (e.g. "pricing_optimization", "product_evaluation")
            role: LLM role ("analyzer", "worker", "creative")
            **data: Context data for the reasoning

        Returns:
            Dict with AI analysis, recommendations, confidence, reasoning
        """
        # Check cache
        cache_key = f"{task}:{hash(json.dumps(data, default=str, sort_keys=True)[:500])}"
        if cache_key in _reasoning_cache:
            cached_time, cached_result = _reasoning_cache[cache_key]
            if time.time() - cached_time < _CACHE_TTL:
                return {**cached_result, "source": "cache"}

        # Build prompt
        prompt = self._build_prompt(task, data)

        # Try LLM
        if self.is_llm_available():
            result = self._llm_reason(prompt, role, data)
            if result and not result.get("error"):
                result["source"] = "llm"
                _reasoning_cache[cache_key] = (time.time(), result)
                return result

        # Fallback: enhanced heuristic reasoning
        result = self._heuristic_reason(task, data)
        result["source"] = "heuristic"
        _reasoning_cache[cache_key] = (time.time(), result)
        return result

    # ── LLM Reasoning ────────────────────────────────────────

    def _llm_reason(self, prompt: str, role: str, context: dict) -> dict[str, Any] | None:
        """Call LLM — direct Ollama first (faster), ModelRouter as fallback."""
        # Direct Ollama call first (no middleware timeout issues)
        try:
            return self._direct_ollama_call(prompt)
        except Exception as exc:
            logger.debug("Direct Ollama: %s", exc)

        # Fallback to ModelRouter
        router = self._get_router()
        if router:
            try:
                result = router.execute(role, prompt, context)
                if not result.get("error"):
                    return self._parse_llm_response(result)
            except Exception as exc:
                logger.debug("ModelRouter: %s", exc)

        return None

    def _direct_ollama_call(self, prompt: str) -> dict[str, Any]:
        """Direct HTTP call to Ollama API."""
        import urllib.request

        payload = json.dumps({
            "model": "mistral",
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 800},
        }).encode()

        req = urllib.request.Request(
            f"{self._ollama_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read())
            text = data.get("response", "")
            return self._parse_text_response(text)

    def _parse_llm_response(self, result: dict[str, Any]) -> dict[str, Any]:
        """Parse ModelRouter response into structured format."""
        text = result.get("text", "")
        if text:
            return self._parse_text_response(text)
        return {
            "analysis": result.get("reason", ""),
            "recommendations": [],
            "confidence": result.get("score", 0) / 10 if result.get("score") else 0.5,
            "reasoning": result.get("decision", ""),
        }

    def _parse_text_response(self, text: str) -> dict[str, Any]:
        """Parse raw LLM text into structured dict."""
        # Try JSON parse first
        try:
            # Find JSON in response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = json.loads(text[start:end])
                if isinstance(parsed, dict):
                    return {
                        "analysis": parsed.get("analysis", parsed.get("reason", text[:200])),
                        "recommendations": parsed.get("recommendations", []),
                        "confidence": float(parsed.get("confidence", parsed.get("score", 5)) or 5) / 10,
                        "reasoning": parsed.get("reasoning", parsed.get("decision", "")),
                        "raw": text,
                    }
        except (json.JSONDecodeError, ValueError) as exc:
            logger.debug("LLM response JSON parse failed: %s", exc)

        # Plain text response
        return {
            "analysis": text[:500],
            "recommendations": self._extract_recommendations(text),
            "confidence": 0.6,
            "reasoning": text[:200],
            "raw": text,
        }

    @staticmethod
    def _extract_recommendations(text: str) -> list[dict[str, Any]]:
        """Extract actionable recommendations from free-form text."""
        recs = []
        lines = text.split("\n")
        for line in lines:
            line = line.strip()
            if line and (line.startswith("-") or line.startswith("*") or
                         line.startswith("1") or line.startswith("2") or
                         line.startswith("3") or "recommend" in line.lower() or
                         "should" in line.lower()):
                recs.append({"action": line.lstrip("-*0123456789. "), "confidence": 0.6})
        return recs[:10]

    # ── Enhanced Heuristic Reasoning ─────────────────────────

    def _heuristic_reason(self, task: str, data: dict) -> dict[str, Any]:
        """Smart heuristic reasoning when LLM is not available.

        Unlike the old hardcoded formulas, this provides contextual analysis
        with explanations and multiple options.
        """
        task_lower = task.lower()

        if "pricing" in task_lower or "price" in task_lower:
            return self._reason_pricing(data)
        elif "product" in task_lower and ("select" in task_lower or "find" in task_lower or "eval" in task_lower):
            return self._reason_product_selection(data)
        elif "customer" in task_lower or "segment" in task_lower:
            return self._reason_customer(data)
        elif "inventory" in task_lower or "stock" in task_lower:
            return self._reason_inventory(data)
        elif "market" in task_lower or "trend" in task_lower:
            return self._reason_market(data)
        else:
            return self._reason_general(task, data)

    def _reason_pricing(self, data: dict) -> dict[str, Any]:
        products = data.get("products", [])
        competitors = data.get("competitors", [])

        recommendations = []
        analysis_parts = []

        for p in products[:20]:
            price = float(p.get("price", 0) or 0)
            cost = float(p.get("cost", 0) or 0)
            name = p.get("name", p.get("title", "Unknown"))

            if cost <= 0:
                analysis_parts.append(f"{name}: cost unknown, cannot optimize")
                continue

            margin = _margin(price, cost, require_cost=False)
            optimal_margin = 0.4  # 40% target

            # Multi-factor analysis
            inventory = int(p.get("inventory_quantity", 0) or 0)
            velocity = float(p.get("velocity", p.get("sales_velocity", 0)) or 0)
            competition = float(p.get("competition", 5) or 5)

            # Dynamic pricing logic
            if margin < 0.15:
                new_price = round(cost / (1 - optimal_margin), 2)
                reason = f"Margin too low ({margin:.0%}). Raise to achieve {optimal_margin:.0%} margin."
                confidence = 0.85
            elif margin > 0.7 and inventory > 100:
                new_price = round(cost / (1 - 0.45), 2)
                reason = f"High margin ({margin:.0%}) but slow movement. Lower to increase velocity."
                confidence = 0.7
            elif inventory < 10 and velocity > 2:
                new_price = round(price * 1.10, 2)
                reason = f"Low stock ({inventory}) + high demand. Raise 10% while restocking."
                confidence = 0.75
            elif competition > 7:
                new_price = round(price * 0.95, 2)
                reason = f"High competition ({competition}/10). Small reduction to stay competitive."
                confidence = 0.65
            else:
                continue

            recommendations.append({
                "product": name,
                "product_id": p.get("id", ""),
                "current_price": price,
                "recommended_price": new_price,
                "current_margin": round(margin, 3),
                "new_margin": round((new_price - cost) / new_price, 3) if new_price > 0 else 0,
                "reason": reason,
                "confidence": confidence,
            })
            analysis_parts.append(f"{name}: ${price} → ${new_price} ({reason})")

        return {
            "analysis": "\n".join(analysis_parts) or "No pricing changes needed",
            "recommendations": recommendations,
            "confidence": 0.7,
            "reasoning": f"Analyzed {len(products)} products. Found {len(recommendations)} pricing opportunities.",
            "factors_considered": ["margin", "inventory", "velocity", "competition"],
        }

    def _reason_product_selection(self, data: dict) -> dict[str, Any]:
        products = data.get("products", [])
        market_data = data.get("market_data", {})

        scored = []
        for p in products:
            score = 0
            reasons = []

            margin = 0
            price = float(p.get("price", 0) or 0)
            cost = float(p.get("cost", 0) or 0)
            margin = _margin(price, cost, default=-1.0)
            if margin >= 0:
                if margin > 0.5:
                    score += 30
                    reasons.append(f"High margin ({margin:.0%})")
                elif margin > 0.3:
                    score += 20

            search_vol = int(p.get("search_volume", 0) or 0)
            if search_vol > 10000:
                score += 25
                reasons.append(f"High search volume ({search_vol:,})")
            elif search_vol > 5000:
                score += 15

            competition = float(p.get("competition", 5) or 5)
            if competition < 4:
                score += 20
                reasons.append(f"Low competition ({competition}/10)")

            rating = float(p.get("rating", 0) or 0)
            if rating > 4.5:
                score += 15
                reasons.append(f"Excellent rating ({rating})")

            reviews = int(p.get("reviews", 0) or 0)
            if reviews > 200:
                score += 10
                reasons.append(f"Social proof ({reviews} reviews)")

            scored.append({
                "product": p.get("name", p.get("title", "")),
                "score": score,
                "reasons": reasons,
                "verdict": "strong_buy" if score > 70 else "buy" if score > 50 else "consider" if score > 30 else "skip",
                "margin": round(margin, 3),
            })

        scored.sort(key=lambda x: x["score"], reverse=True)

        return {
            "analysis": f"Evaluated {len(products)} products across margin, demand, competition, and reviews.",
            "recommendations": scored[:10],
            "confidence": 0.7,
            "reasoning": f"Top pick: {scored[0]['product']} (score {scored[0]['score']})" if scored else "No products to evaluate",
        }

    def _reason_customer(self, data: dict) -> dict[str, Any]:
        customers = data.get("customer_data", data.get("customers", []))

        segments = {"champions": [], "loyal": [], "at_risk": [], "new": [], "lost": []}

        for c in customers:
            orders = int(c.get("orders", c.get("orders_count", 0)) or 0)
            spent = float(c.get("total_spent", 0) or 0)
            days_since = int(c.get("days_since_last_order", 999) or 999)

            if orders >= 5 and spent > 300 and days_since < 30:
                segments["champions"].append(c)
            elif orders >= 3 and days_since < 60:
                segments["loyal"].append(c)
            elif orders >= 2 and days_since > 60:
                segments["at_risk"].append(c)
            elif orders <= 1 and days_since < 30:
                segments["new"].append(c)
            else:
                segments["lost"].append(c)

        recommendations = []
        if segments["at_risk"]:
            recommendations.append({
                "action": "win_back_campaign",
                "target": f"{len(segments['at_risk'])} at-risk customers",
                "reason": "These customers bought before but haven't returned. Send win-back email with discount.",
                "confidence": 0.8,
            })
        if segments["champions"]:
            recommendations.append({
                "action": "vip_program",
                "target": f"{len(segments['champions'])} champion customers",
                "reason": "Your best customers. Offer exclusive deals, early access, loyalty rewards.",
                "confidence": 0.9,
            })
        if segments["new"]:
            recommendations.append({
                "action": "onboarding_sequence",
                "target": f"{len(segments['new'])} new customers",
                "reason": "First-time buyers. Send welcome series to convert to repeat buyers.",
                "confidence": 0.85,
            })

        return {
            "analysis": f"Segmented {len(customers)} customers into {sum(len(v) for v in segments.values())} groups.",
            "segments": {k: len(v) for k, v in segments.items()},
            "recommendations": recommendations,
            "confidence": 0.75,
            "reasoning": f"Champions: {len(segments['champions'])}, At-risk: {len(segments['at_risk'])}, New: {len(segments['new'])}",
        }

    def _reason_inventory(self, data: dict) -> dict[str, Any]:
        products = data.get("products", [])
        recommendations = []

        for p in products:
            qty = int(p.get("inventory_quantity", 0) or 0)
            velocity = float(p.get("velocity", p.get("sales_velocity", 0)) or 0)
            name = p.get("name", p.get("title", "Unknown"))

            if qty == 0:
                recommendations.append({
                    "product": name, "action": "urgent_restock",
                    "reason": "OUT OF STOCK — losing sales now",
                    "confidence": 0.95, "priority": "critical",
                })
            elif qty < 10 and velocity > 1:
                days_left = qty / velocity if velocity > 0 else 999
                recommendations.append({
                    "product": name, "action": "restock",
                    "reason": f"Only {qty} left, selling {velocity:.1f}/day. {days_left:.0f} days until stockout.",
                    "confidence": 0.85, "priority": "high",
                })
            elif qty > 200 and velocity < 0.5:
                recommendations.append({
                    "product": name, "action": "reduce_or_discount",
                    "reason": f"Overstocked ({qty} units) with low demand ({velocity:.1f}/day). Consider clearance.",
                    "confidence": 0.7, "priority": "medium",
                })

        return {
            "analysis": f"Analyzed inventory for {len(products)} products.",
            "recommendations": recommendations,
            "confidence": 0.8,
            "reasoning": f"Found {len(recommendations)} inventory issues.",
            "critical_count": len([r for r in recommendations if r.get("priority") == "critical"]),
        }

    def _reason_market(self, data: dict) -> dict[str, Any]:
        return {
            "analysis": "Market analysis based on available data.",
            "recommendations": [
                {"action": "monitor_trends", "reason": "Track trending products in your niche", "confidence": 0.6},
                {"action": "competitor_prices", "reason": "Regular competitor price monitoring", "confidence": 0.7},
            ],
            "confidence": 0.5,
            "reasoning": "Limited market data available. Recommend setting up competitor monitoring.",
        }

    def _reason_general(self, task: str, data: dict) -> dict[str, Any]:
        return {
            "analysis": f"General analysis for task: {task}",
            "recommendations": [],
            "confidence": 0.5,
            "reasoning": f"Processed {len(data)} data fields for {task}.",
        }

    # ── Prompt Building ──────────────────────────────────────

    def _build_prompt(self, task: str, data: dict) -> str:
        """Build a structured prompt for the LLM."""
        # Summarize data to fit context window
        summary = self._summarize_data(data)

        return f"""You are an expert e-commerce AI analyst specializing in dropshipping. Analyze the following data and provide actionable recommendations.

TASK: {task}

DATA:
{summary}

Respond in JSON format:
{{
  "analysis": "Brief analysis (2-3 sentences)",
  "recommendations": [
    {{"action": "what to do", "product": "which product", "reason": "why", "confidence": 0.8, "impact": "high/medium/low"}}
  ],
  "confidence": 0.7,
  "reasoning": "Your reasoning (1-2 sentences)"
}}

Focus on actionable, specific recommendations. Consider margins, competition, and demand. Max 5 recommendations."""

    @staticmethod
    def _summarize_data(data: dict, max_items: int = 10) -> str:
        """Summarize data dict to fit in LLM context."""
        parts = []
        for key, value in data.items():
            if isinstance(value, list):
                items = value[:max_items]
                parts.append(f"\n{key} ({len(value)} total, showing {len(items)}):")
                for item in items:
                    if isinstance(item, dict):
                        compact = {k: v for k, v in item.items()
                                   if k not in ("raw_data", "_raw", "variants", "body_html", "description")
                                   and v is not None and v != "" and v != 0}
                        parts.append(f"  - {json.dumps(compact, default=str)}")
                    else:
                        parts.append(f"  - {item}")
            elif isinstance(value, dict):
                parts.append(f"\n{key}: {json.dumps(value, default=str)[:200]}")
            elif isinstance(value, (str, int, float, bool)):
                parts.append(f"{key}: {value}")
        return "\n".join(parts)


# ── Module-level convenience function ────────────────────────

_instance: AIReasoning | None = None
_instance_lock = _threading.Lock()


def ai_reason(task: str, role: str = "analyzer", **data: Any) -> dict[str, Any]:
    """Module-level convenience function for AI reasoning.

    Usage:
        from core.ai.reasoning import ai_reason
        result = ai_reason("pricing", products=products)
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = AIReasoning()
    return _instance.reason(task, role, **data)


def is_llm_available() -> bool:
    """Check if LLM is available."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = AIReasoning()
    return _instance.is_llm_available()
