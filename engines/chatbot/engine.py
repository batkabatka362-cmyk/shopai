"""
Chatbot Engine

Purpose: Process customer queries and generate intelligent chatbot responses
Input:   ['customer_query', 'context']
Output:  ['response', 'suggested_actions']

Flow: Analyzer (Mistral) -> Worker (Qwen) -> Creative (LLaMA) -> Validator (Mistral)
"""

from __future__ import annotations

from typing import Any

from engines.base import BaseEngine, EngineStep, StepResult, EngineStatus
from models.routing.model_router import ModelRouter


class ChatbotEngine(BaseEngine):
    engine_name = "chatbot"
    required_input_fields = ['customer_query', 'context']
    required_output_fields = ['response', 'suggested_actions']

    def __init__(self) -> None:
        self._model_router = ModelRouter()
        super().__init__()

    def define_steps(self) -> None:
        self.flow.add_step(EngineStep(
            name="analyze", model_role="analyzer",
            description="Analyze customer query intent and context",
            required=True, stop_on_reject=True,
        ))
        self.flow.register_executor("analyze", self._step_analyze)

        self.flow.add_step(EngineStep(
            name="execute", model_role="worker",
            description="Generate response and suggested actions",
            required=True,
        ))
        self.flow.register_executor("execute", self._step_execute)

        self.flow.add_step(EngineStep(
            name="enhance", model_role="creative",
            description="Enhance response with conversational warmth",
            required=False,
        ))
        self.flow.register_executor("enhance", self._step_enhance)

        self.flow.add_step(EngineStep(
            name="validate", model_role="validator",
            description="Validate response accuracy and helpfulness",
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
            "analyze": """You are a conversational AI analyst. Analyze the customer query to determine intent and required context.

Evaluate:
1. Primary intent (purchase, support, information, complaint)
2. Sentiment and urgency level
3. Relevant context from conversation history
4. Entity extraction (product, order, account)
5. Escalation need assessment

Customer query: {customer_query}
Context: {context}

Return: intent classification, entities extracted, sentiment, urgency level, and context requirements.""",
            "execute": """Based on the analysis, generate an appropriate response and suggested actions.

Analysis results: {analysis}
Customer query: {customer_query}
Context: {context}

Provide:
- response_text (natural, helpful, on-brand)
- confidence_score
- suggested_actions (buttons, links, escalation)
- follow_up_questions
- knowledge_base_references

Return as structured JSON with response and suggested_actions objects.""",
            "enhance": """Enhance the chatbot response with warmth and personality.

Improve:
- Conversational tone while staying professional
- Empathy acknowledgments where appropriate
- Proactive helpful suggestions
- Smooth transition to next steps

Current output: {execution}""",
            "validate": """Validate the chatbot response for accuracy and helpfulness.

Check:
1. Response directly addresses the customer's question
2. Information is factually accurate
3. Tone is appropriate for the sentiment detected
4. Suggested actions are relevant and helpful
5. No hallucinated information or false promises

Output to validate: {enhanced}""",
        }
        template = templates.get(step, "")
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str(data)

    # --- Domain helpers ---

    @staticmethod
    def _classify_intent(query: str) -> str:
        query_lower = query.lower()
        intent_keywords = {
            "purchase": ["buy", "order", "purchase", "add to cart", "checkout", "price"],
            "support": ["help", "issue", "problem", "broken", "not working", "error"],
            "shipping": ["shipping", "delivery", "track", "where is", "when will"],
            "return": ["return", "refund", "exchange", "send back", "money back"],
            "information": ["what is", "how does", "tell me", "information", "details"],
        }
        for intent, keywords in intent_keywords.items():
            if any(kw in query_lower for kw in keywords):
                return intent
        return "general"

    @staticmethod
    def _extract_entities(query: str) -> dict:
        entities: dict[str, list[str]] = {"order_ids": [], "product_mentions": [], "dates": []}
        words = query.split()
        for word in words:
            cleaned = word.strip("#").strip()
            if cleaned.startswith("ORD") or (cleaned.isdigit() and len(cleaned) >= 6):
                entities["order_ids"].append(cleaned)
        return entities
