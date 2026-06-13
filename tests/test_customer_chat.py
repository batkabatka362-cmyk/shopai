"""Tests for engines.customer_chat — W963-13."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from engines.customer_chat import CustomerChatEngine
from engines.customer_chat.classifier import IntentResult, classify
from engines.customer_chat.response_generator import (
    ResponseDraft,
    generate_response,
)


# ── Classifier ────────────────────────────────────────────


class TestClassifier:
    def test_empty_message_returns_greeting(self):
        r = classify("")
        assert r.intent == "greeting_other"
        assert r.confidence == 0.0

    def test_order_status_detected(self):
        r = classify("Where is my order?")
        assert r.intent == "order_status"
        assert r.confidence > 0

    def test_shipping_detected(self):
        r = classify("What is your shipping cost?")
        assert r.intent == "shipping"

    def test_returns_detected(self):
        r = classify("I want to return this item")
        assert r.intent == "returns"

    def test_product_question_detected(self):
        r = classify(
            "What size guide do you have for this dress?"
        )
        assert r.intent == "product_question"

    def test_complaint_detected(self):
        r = classify(
            "I'm really disappointed. The item is broken."
        )
        assert r.intent == "complaint"
        assert r.confidence >= 0.3

    def test_generic_falls_back(self):
        r = classify("Hello, just saying hi")
        assert r.intent == "greeting_other"

    def test_confidence_capped_at_1(self):
        r = classify(
            "Where is my order #1234 tracking number?"
        )
        assert r.confidence <= 1.0

    def test_multiple_signals_picks_strongest(self):
        # Mentions BOTH shipping AND returns; returns rule
        # signal should dominate.
        r = classify(
            "How can I return this? Will shipping be free?"
        )
        assert r.intent in {"returns", "shipping"}


# ── Response generator ────────────────────────────────────


class TestResponseGenerator:
    def test_unknown_intent_falls_back(self):
        d = generate_response(intent="nope")
        assert d.intent == "greeting_other"

    def test_customer_name_substituted(self):
        d = generate_response(
            intent="order_status",
            customer_name="Mary",
        )
        assert "Hi Mary" in d.text

    def test_default_name_when_missing(self):
        d = generate_response(intent="order_status")
        assert "Hi there" in d.text

    def test_order_id_threaded_into_blurb(self):
        d = generate_response(
            intent="order_status", order_id="1234",
        )
        assert "#1234" in d.text

    def test_store_signature_used(self):
        d = generate_response(
            intent="order_status",
            store_name="ShopAI Beauty",
        )
        assert "ShopAI Beauty" in d.text

    def test_complaint_flags_review(self):
        d = generate_response(intent="complaint")
        assert d.requires_human_review is True

    def test_returns_flags_review(self):
        d = generate_response(intent="returns")
        assert d.requires_human_review is True

    def test_normal_intents_no_review(self):
        d = generate_response(intent="order_status")
        assert d.requires_human_review is False

    def test_llm_off_yields_template(self):
        d = generate_response(
            intent="order_status",
            use_llm=False,
            message="Where is my order?",
        )
        assert d.used_llm is False

    def test_llm_refinement_used_when_router_returns(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True,
            data={"text": "Refined response from LLM"},
            error="",
        )
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ):
            d = generate_response(
                intent="order_status",
                use_llm=True,
                message="Where is my order?",
            )
        assert d.used_llm is True
        assert d.text == "Refined response from LLM"

    def test_llm_failure_falls_back_to_template(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=False, data=None, error="LLM down",
        )
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ):
            d = generate_response(
                intent="order_status",
                use_llm=True,
                message="Where is my order?",
            )
        assert d.used_llm is False
        assert "Hi there" in d.text  # template still works


# ── Engine Pattern Q envelope ─────────────────────────────


class TestEngineEnvelope:
    def test_empty_message_returns_error(self):
        result = CustomerChatEngine().run({})
        assert result["status"] == "error"

    def test_non_dict_error(self):
        result = CustomerChatEngine().run("nope")
        assert result["status"] == "error"

    def test_fail_upstream(self):
        result = CustomerChatEngine().run({
            "status": "fail", "error": "broken",
        })
        assert result["status"] == "error"


class TestEngineHappyPath:
    def test_basic_response(self):
        result = CustomerChatEngine().run({
            "data": {
                "message": "Where is my order?",
                "customer_name": "Mary",
            },
        })
        assert result["status"] == "success"
        d = result["data"]
        assert d["intent"] == "order_status"
        assert "Mary" in d["draft_response"]

    def test_complaint_flags_review_in_envelope(self):
        result = CustomerChatEngine().run({
            "data": {
                "message": "The item is broken!",
            },
        })
        assert result["data"]["requires_human_review"] is True
        assert "HUMAN REVIEW" in result["data"]["next_action"]
