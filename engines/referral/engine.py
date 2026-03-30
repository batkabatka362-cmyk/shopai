"""
Referral Engine — Manage referral systems — incentive design, tracking, optimization
"""
from __future__ import annotations
from typing import Any
from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class ReferralEngine(BaseEngine):
    engine_name = "referral"
    required_input_fields = ['referral_data', 'incentive_data']
    required_output_fields = ['referral_program', 'growth_projections']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(name="analyze", model_role="analyzer", description="Domain analysis", required=True, stop_on_reject=True))
        self.flow.register_executor("analyze", self._step_analyze)
        self.flow.add_step(EngineStep(name="execute", model_role="worker", description="Generate structured output", required=True))
        self.flow.register_executor("execute", self._step_execute)
        self.flow.add_step(EngineStep(name="enhance", model_role="creative", description="Creative enhancement", required=False))
        self.flow.register_executor("enhance", self._step_enhance)
        self.flow.add_step(EngineStep(name="validate", model_role="validator", description="Quality validation", required=True))
        self.flow.register_executor("validate", self._step_validate)

    def _step_analyze(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("analyze", data)
        r = self._model_router.execute("analyzer", prompt, context=data)
        return StepResult(step_name=step_name, model_used="mistral", status=EngineStatus.COMPLETED, output={"analysis": r})

    def _step_execute(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("execute", data)
        r = self._model_router.execute("worker", prompt, context=data)
        return StepResult(step_name=step_name, model_used="qwen", status=EngineStatus.COMPLETED, output={"execution": r})

    def _step_enhance(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("enhance", data)
        r = self._model_router.execute("creative", prompt, context=data)
        return StepResult(step_name=step_name, model_used="llama", status=EngineStatus.COMPLETED, output={"enhanced": r})

    def _step_validate(self, step_name: str, data: dict[str, Any]) -> StepResult:
        prompt = self._build_prompt("validate", data)
        r = self._model_router.execute("validator", prompt, context=data)
        return StepResult(step_name=step_name, model_used="mistral", status=EngineStatus.COMPLETED, output={"validation": r})

    def _build_prompt(self, step: str, data: dict[str, Any]) -> str:
        templates = {"analyze": """Analyze referrals: current referral rate, incentive effectiveness, viral coefficient, channel performance, fraud detection.\n\nReferrals: {referral_data}\nIncentives: {incentive_data}""", "execute": """Generate referral program: incentive structure (two-sided), sharing mechanics, milestone rewards, fraud prevention, tracking.\nAnalysis: {analysis}""", "enhance": """Enhance: social proof, status rewards, gamification, community challenges.\nProgram: {execution}""", "validate": """Validate: unit economics positive, fraud controls in place, incentives not cannibalistic.\nOutput: {enhanced}"""}
        t = templates.get(step, "")
        try:
            return t.format(**data)
        except KeyError:
            return t + "\nData: " + str(data)

    @staticmethod
    def _referral_rate(referrals: int, customers: int) -> float:
        if customers == 0: return 0.0
        return round(referrals / customers * 100, 2)

    @staticmethod
    def _cac_with_referral(spend: float, new_customers: int, referral_cost: float, referred_customers: int) -> float:
        total_cost = spend + referral_cost
        total_customers = new_customers + referred_customers
        if total_customers == 0: return 0.0
        return round(total_cost / total_customers, 2)
