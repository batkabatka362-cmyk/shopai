"""
CustomerSupport Engine

Purpose: Manage support tickets with automated categorization and resolution planning
Input:   ['ticket_data', 'support_config']
Output:  ['resolution_plan', 'response_draft']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class CustomerSupportEngine(BaseEngine):
    engine_name = "customer_support"
    required_input_fields = ['ticket_data', 'support_config']
    required_output_fields = ['resolution_plan', 'response_draft']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze support tickets for categorization and priority",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate resolution plans and response drafts",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance responses with empathetic communication",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate resolution plans and response quality",
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
            "analyze": """You are a customer support manager. Analyze support tickets for categorization, priority, and resolution approach.

Evaluate:
1. Issue category (billing, technical, shipping, product, account)
2. Priority level based on urgency and impact
3. Customer history and loyalty tier
4. Resolution complexity and required resources
5. SLA compliance requirements

Ticket data: {ticket_data}
Support config: {support_config}

Return: ticket categorization, priority assignment, resolution approach, and resource requirements.""",
            "execute": """Based on the analysis, generate resolution plans and response drafts.

Analysis results: {analysis}
Ticket data: {ticket_data}
Support config: {support_config}

For each ticket provide:
- ticket_id, category, priority, assigned_team
- resolution_steps, estimated_resolution_time
- response_draft, escalation_needed
- follow_up_actions, knowledge_base_update

Return as structured JSON with resolution_plan and response_draft arrays.""",
            "enhance": """Enhance support responses with empathetic and solution-focused communication.

For each response, improve:
- Empathy and acknowledgment of frustration
- Clear step-by-step resolution guidance
- Proactive additional help offers
- Professional yet warm closing

Current output: {execution}""",
            "validate": """Validate the resolution plans and response quality.

Check:
1. All tickets have assigned categories and priorities
2. Resolution steps are actionable and complete
3. Response tone matches the situation severity
4. SLA timelines are respected
5. Escalation criteria are properly applied

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _categorize_ticket(subject: str, body: str) -> str:
        text = (subject + " " + body).lower()
        categories = {
            "billing": ["charge", "invoice", "payment", "refund", "billing", "subscription"],
            "technical": ["error", "bug", "crash", "not working", "broken", "glitch"],
            "shipping": ["shipping", "delivery", "tracking", "lost package", "delayed"],
            "product": ["quality", "defective", "damaged", "wrong item", "missing"],
            "account": ["login", "password", "account", "access", "verification"],
        }
        for category, keywords in categories.items():
            if any(kw in text for kw in keywords):
                return category
        return "general"

    @staticmethod
    def _estimate_resolution_time(category: str, priority: str) -> int:
        base_hours = {"billing": 4, "technical": 8, "shipping": 24, "product": 12, "account": 2, "general": 6}
        priority_multiplier = {"critical": 0.25, "high": 0.5, "medium": 1.0, "low": 2.0}
        base = base_hours.get(category, 6)
        multiplier = priority_multiplier.get(priority, 1.0)
        return max(1, int(base * multiplier))
