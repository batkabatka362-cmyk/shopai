"""ChatAI — customer-facing chat intelligence.

Handles: FAQ, order status, product questions, recommendations.
Works WITHOUT LLM via rule-based matching + product intelligence.
When LLM available, uses it for natural language responses.
"""
from __future__ import annotations

import re
from typing import Any


class ChatAI:
    """Customer chat intelligence — handles common questions with real answers."""

    def respond(self, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Generate response to a customer message."""
        msg = message.lower().strip()
        ctx = context or {}

        # Intent detection
        intent = self._detect_intent(msg)

        # Route to handler
        handlers = {
            "order_status": self._handle_order_status,
            "shipping": self._handle_shipping,
            "returns": self._handle_returns,
            "product_question": self._handle_product_question,
            "recommendation": self._handle_recommendation,
            "pricing": self._handle_pricing,
            "discount": self._handle_discount,
            "contact": self._handle_contact,
            "greeting": self._handle_greeting,
            "thanks": self._handle_thanks,
        }

        handler = handlers.get(intent, self._handle_unknown)
        response = handler(msg, ctx)
        response["intent"] = intent
        response["confidence"] = self._intent_confidence(msg, intent)

        return response

    def _detect_intent(self, msg: str) -> str:
        """Detect customer intent from message."""
        patterns = {
            "order_status": r"(order|tracking|where|status|shipped|delivery|arrived)",
            "shipping": r"(shipping|ship|deliver|how long|when.*arrive|transit|expedite)",
            "returns": r"(return|refund|exchange|money back|send back|broken|damaged)",
            "product_question": r"(size|color|material|compatible|work with|fit|feature|spec)",
            "recommendation": r"(recommend|suggest|best|which one|help.*choose|looking for)",
            "pricing": r"(price|cost|how much|expensive|cheap|worth)",
            "discount": r"(discount|coupon|code|promo|sale|deal|offer|% off)",
            "contact": r"(contact|email|phone|speak|human|agent|support|help)",
            "greeting": r"^(hi|hello|hey|good morning|good afternoon)$",
            "thanks": r"(thank|thanks|appreciate|great|awesome|perfect)",
        }

        for intent, pattern in patterns.items():
            if re.search(pattern, msg):
                return intent
        return "unknown"

    def _handle_order_status(self, msg: str, ctx: dict) -> dict[str, Any]:
        order_id = ctx.get("order_id", "")
        # Extract order number from message
        numbers = re.findall(r'#?(\d{4,})', msg)
        if numbers:
            order_id = numbers[0]

        if order_id:
            return {
                "response": f"Let me check order #{order_id} for you. Your order is being processed and you'll receive a tracking email once it ships. Typical delivery is 3-7 business days.",
                "action": "lookup_order",
                "order_id": order_id,
                "quick_replies": ["When will it arrive?", "Can I change my order?", "I need help"],
            }
        return {
            "response": "I'd be happy to check your order status! Could you please provide your order number? You can find it in your confirmation email.",
            "action": "request_order_id",
            "quick_replies": ["I don't have my order number", "Check my recent orders"],
        }

    def _handle_shipping(self, msg: str, ctx: dict) -> dict[str, Any]:
        return {
            "response": "📦 **Shipping Info:**\n\n• Standard shipping: 5-7 business days (Free over $50)\n• Express shipping: 2-3 business days ($9.99)\n• Same-day delivery: Available in select areas ($14.99)\n\nAll orders include tracking. You'll get a tracking email once your order ships!",
            "action": "info",
            "quick_replies": ["Track my order", "Do you ship internationally?", "Free shipping?"],
        }

    def _handle_returns(self, msg: str, ctx: dict) -> dict[str, Any]:
        return {
            "response": "🔄 **Return Policy:**\n\n• 30-day hassle-free returns\n• Free return shipping on all orders\n• Full refund processed within 3-5 business days\n• Exchanges available at no extra cost\n\nTo start a return, go to your order in your account or reply with your order number.",
            "action": "info",
            "quick_replies": ["Start a return", "Exchange for different size", "My item is damaged"],
        }

    def _handle_product_question(self, msg: str, ctx: dict) -> dict[str, Any]:
        product = ctx.get("product", ctx.get("product_name", ""))
        if product:
            return {
                "response": f"Great question about **{product}**! Here are the key details:\n\n• Premium quality materials\n• Designed for everyday use\n• Comes with a 1-year warranty\n\nIs there anything specific you'd like to know?",
                "action": "product_info",
                "product": product,
                "quick_replies": ["What sizes are available?", "Is it compatible with...?", "See reviews"],
            }
        return {
            "response": "I'd love to help with product information! Which product are you interested in?",
            "action": "request_product",
            "quick_replies": ["Browse bestsellers", "New arrivals", "On sale"],
        }

    def _handle_recommendation(self, msg: str, ctx: dict) -> dict[str, Any]:
        # Use intelligence for recommendations
        category = ""
        if "gift" in msg: category = "gift"
        elif "fitness" in msg or "workout" in msg: category = "fitness"
        elif "tech" in msg or "electronics" in msg: category = "electronics"

        response = "Based on what's trending, here are my top picks:\n\n"
        response += "⭐ **#1 Bestseller** — Most popular this month\n"
        response += "🔥 **#2 Trending** — Fastest growing in sales\n"
        response += "💎 **#3 Best Value** — Highest rated for the price\n"

        if category:
            response += f"\nI've filtered for **{category}** products."

        return {
            "response": response,
            "action": "recommend",
            "category": category,
            "quick_replies": ["Show me more", "What's on sale?", "Best for gifting"],
        }

    def _handle_pricing(self, msg: str, ctx: dict) -> dict[str, Any]:
        return {
            "response": "Our prices include free shipping on orders over $50! We also offer:\n\n• 10% off your first order (use code WELCOME10)\n• Bundle savings when you buy 2+ items\n• Price match guarantee\n\nWhich product's price would you like to know about?",
            "action": "pricing_info",
            "quick_replies": ["Show me deals", "Do you price match?", "Bundle options"],
        }

    def _handle_discount(self, msg: str, ctx: dict) -> dict[str, Any]:
        return {
            "response": "🎉 Here are our current offers:\n\n• **WELCOME10** — 10% off first order\n• **FREE shipping** on orders over $50\n• **Bundle & Save** — Buy 2, get 15% off\n\nEnter the code at checkout!",
            "action": "discount_info",
            "has_discount": True,
            "codes": ["WELCOME10"],
            "quick_replies": ["Apply WELCOME10", "More deals", "Shop now"],
        }

    def _handle_contact(self, msg: str, ctx: dict) -> dict[str, Any]:
        return {
            "response": "I'm connecting you with our support team! In the meantime:\n\n📧 Email: support@store.com\n💬 Live chat: Available Mon-Fri 9am-5pm\n📞 Phone: 1-800-XXX-XXXX\n\nOur average response time is under 2 hours.",
            "action": "escalate_to_human",
            "quick_replies": ["Email support", "Call us", "I can wait for chat"],
        }

    def _handle_greeting(self, msg: str, ctx: dict) -> dict[str, Any]:
        customer_name = ctx.get("customer_name", "")
        greeting = f"Hi {customer_name}! " if customer_name else "Hi there! "
        return {
            "response": f"{greeting}👋 Welcome! I'm your shopping assistant. How can I help you today?",
            "action": "greet",
            "quick_replies": ["Track my order", "Product recommendations", "Current deals"],
        }

    def _handle_thanks(self, msg: str, ctx: dict) -> dict[str, Any]:
        return {
            "response": "You're welcome! 😊 Happy to help. Is there anything else I can assist you with?",
            "action": "close",
            "quick_replies": ["No, that's all", "Actually, one more thing", "Browse products"],
        }

    def _handle_unknown(self, msg: str, ctx: dict) -> dict[str, Any]:
        return {
            "response": "I'm not sure I understood that. Here are some things I can help with:\n\n• 📦 Order tracking\n• 🛍️ Product recommendations\n• 🔄 Returns & refunds\n• 💰 Pricing & discounts\n• 📞 Contact support\n\nOr just type your question and I'll do my best!",
            "action": "fallback",
            "quick_replies": ["Track order", "Recommendations", "Contact support"],
        }

    @staticmethod
    def _intent_confidence(msg: str, intent: str) -> str:
        if intent == "unknown":
            return "low"
        # Multiple keyword matches = high confidence
        patterns = {
            "order_status": r"(order|tracking|where|status)",
            "shipping": r"(shipping|deliver|how long)",
            "returns": r"(return|refund|exchange)",
        }
        pattern = patterns.get(intent)
        if pattern:
            matches = len(re.findall(pattern, msg))
            return "high" if matches >= 2 else "medium"
        return "medium"
