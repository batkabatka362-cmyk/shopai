"""
Marketplace Engine

Purpose: Optimize product listings and strategies across marketplaces
Input:   ['product_data', 'marketplace_config']
Output:  ['listings', 'marketplace_strategy']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class MarketplaceEngine(BaseEngine):
    engine_name = "marketplace"
    required_input_fields = ['product_data', 'marketplace_config']
    required_output_fields = ['listings', 'marketplace_strategy']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze product fit and marketplace requirements",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate optimized listings and marketplace strategy",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance listings with compelling copy and visuals",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate listings comply with marketplace rules",
            required=True,
        ))
        self.flow.register_executor("validate", self._step_validate)

    def _step_analyze(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("analyze", data)
        result = self._model_router.execute("analyzer", prompt, context=data)
        return StepResult(step_name=step_name, model_used="mistral", status=EngineStatus.COMPLETED, output={"analysis": result})

    def _step_execute(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("execute", data)
        result = self._model_router.execute("worker", prompt, context=data)
        return StepResult(step_name=step_name, model_used="qwen", status=EngineStatus.COMPLETED, output={"execution": result})

    def _step_enhance(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("enhance", data)
        result = self._model_router.execute("creative", prompt, context=data)
        return StepResult(step_name=step_name, model_used="llama", status=EngineStatus.COMPLETED, output={"enhanced": result})

    def _step_validate(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("validate", data)
        result = self._model_router.execute("validator", prompt, context=data)
        return StepResult(step_name=step_name, model_used="mistral", status=EngineStatus.COMPLETED, output={"validation": result})

    def _build_prompt(self, step: str, data: dict[str, Any]) -> str:
        templates = {
            "analyze": """You are a marketplace optimization expert. Analyze product data and marketplace configurations.

Evaluate:
1. Product-marketplace fit (Amazon, eBay, Etsy, Walmart, etc.)
2. Category competition and saturation
3. Pricing competitiveness per marketplace
4. Fulfillment requirements and options
5. Marketplace fee structures and profitability

Product data: {product_data}
Marketplace config: {marketplace_config}

Return: marketplace suitability scores, competitive analysis, fee breakdown, and listing strategy recommendations.""",
            "execute": """Based on the analysis, generate optimized listings and marketplace strategy.

Analysis results: {analysis}
Product data: {product_data}
Marketplace config: {marketplace_config}

For each listing provide:
- marketplace, product_id, title, description
- bullet_points, keywords, category
- price, fulfillment_method
- image_requirements, a_plus_content

Return as structured JSON with listings and marketplace_strategy arrays.""",
            "enhance": """Enhance marketplace listings with compelling content and differentiation.

Add:
- A+ / enhanced brand content suggestions
- Keyword-rich bullet points
- Competitive differentiation angles
- Cross-marketplace consistency checks

Current output: {execution}""",
            "validate": """Validate marketplace listings for compliance and quality.

Check:
1. Titles meet marketplace character limits
2. Required fields are populated per marketplace
3. Pricing accounts for all marketplace fees
4. Category selections are accurate
5. No restricted keywords or claims

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _optimize_listing(title: str, max_length: int = 200) -> str:
        if len(title) <= max_length:
            return title
        words = title.split()
        optimized = []
        current_len = 0
        for word in words:
            if current_len + len(word) + 1 <= max_length:
                optimized.append(word)
                current_len += len(word) + 1
            else:
                break
        return " ".join(optimized)

    @staticmethod
    def _calculate_marketplace_fees(sale_price: float, marketplace: str) -> dict:
        fee_structures = {
            "amazon": {"referral_pct": 15.0, "fixed": 0.99},
            "ebay": {"referral_pct": 12.9, "fixed": 0.30},
            "etsy": {"referral_pct": 6.5, "fixed": 0.20},
            "walmart": {"referral_pct": 8.0, "fixed": 0.0},
        }
        structure = fee_structures.get(marketplace.lower(), {"referral_pct": 10.0, "fixed": 0.0})
        referral_fee = sale_price * structure["referral_pct"] / 100
        total_fees = referral_fee + structure["fixed"]
        net_revenue = sale_price - total_fees
        return {"referral_fee": round(referral_fee, 2), "fixed_fee": structure["fixed"], "total_fees": round(total_fees, 2), "net_revenue": round(net_revenue, 2)}
