"""Payment adapter for ShopAI — wraps Stripe-style payment APIs."""

import time
import uuid

from tools.base import (
    BaseToolAdapter,
    HealthStatus,
    RateConfig,
    ToolMetadata,
    ToolResult,
)


class PaymentAdapter(BaseToolAdapter):
    tool_name = "payment"
    tool_category = "commerce"
    version = "1.0.0"

    BASE_URL = "https://api.stripe.com/v1"

    def __init__(self) -> None:
        self._credentials: dict = {}
        self._secret_key: str = ""
        self._webhook_secret: str = ""
        self._default_currency: str = "usd"

    def configure(self, credentials: dict) -> None:
        self._credentials = credentials
        self._secret_key = credentials.get("secret_key", "")
        self._webhook_secret = credentials.get("webhook_secret", "")
        self._default_currency = credentials.get("currency", "usd")

    def capabilities(self) -> list[str]:
        return [
            "create_payment_intent",
            "capture_payment",
            "create_refund",
            "list_charges",
            "create_subscription",
            "cancel_subscription",
            "get_balance",
            "list_disputes",
        ]

    def execute(self, action: str, params: dict) -> ToolResult:
        dispatch = {
            "create_payment_intent": self._create_payment_intent,
            "capture_payment": self._capture_payment,
            "create_refund": self._create_refund,
            "list_charges": self._list_charges,
            "create_subscription": self._create_subscription,
            "cancel_subscription": self._cancel_subscription,
            "get_balance": self._get_balance,
            "list_disputes": self._list_disputes,
        }
        handler = dispatch.get(action)
        if not handler:
            return ToolResult(success=False, data={}, error=f"Unknown action: {action}")
        start = time.monotonic()
        try:
            result = handler(params)
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                success=True,
                data=result,
                error=None,
                metadata=ToolMetadata(
                    duration_ms=elapsed,
                    attempt_count=1,
                    rate_limited=False,
                    cost_usd=0.0,
                    tool_name=self.tool_name,
                    action=action,
                ),
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                success=False,
                data={},
                error=str(exc),
                metadata=ToolMetadata(
                    duration_ms=elapsed,
                    attempt_count=1,
                    rate_limited=False,
                    cost_usd=0.0,
                    tool_name=self.tool_name,
                    action=action,
                ),
            )

    def health_check(self) -> HealthStatus:
        start = time.monotonic()
        healthy = bool(self._secret_key)
        latency = (time.monotonic() - start) * 1000 + 50.0
        return HealthStatus(
            healthy=healthy,
            latency_ms=latency,
            last_check=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            error=None if healthy else "No Stripe secret key configured",
        )

    def get_rate_config(self) -> RateConfig:
        return RateConfig(requests_per_second=25.0, burst=100, daily_quota=None)

    # ── handlers ──────────────────────────────────────────────

    def _create_payment_intent(self, params: dict) -> dict:
        if "amount" not in params:
            raise ValueError("amount is required (in smallest currency unit, e.g. cents)")
        amount = params["amount"]
        if not isinstance(amount, int) or amount <= 0:
            raise ValueError("amount must be a positive integer")
        currency = params.get("currency", self._default_currency)
        payload: dict = {
            "amount": amount,
            "currency": currency,
            "payment_method_types": params.get("payment_method_types", ["card"]),
            "capture_method": params.get("capture_method", "automatic"),
        }
        if "customer_id" in params:
            payload["customer"] = params["customer_id"]
        if "metadata" in params:
            payload["metadata"] = params["metadata"]
        if "description" in params:
            payload["description"] = params["description"]
        return {
            "endpoint": f"{self.BASE_URL}/payment_intents",
            "method": "POST",
            "payload": payload,
            "payment_intent_id": f"pi_{uuid.uuid4().hex[:24]}",
            "client_secret": f"pi_{uuid.uuid4().hex[:24]}_secret_{uuid.uuid4().hex[:16]}",
            "status": "requires_payment_method",
        }

    def _capture_payment(self, params: dict) -> dict:
        if "payment_intent_id" not in params:
            raise ValueError("payment_intent_id is required")
        payload: dict = {}
        if "amount_to_capture" in params:
            payload["amount_to_capture"] = params["amount_to_capture"]
        return {
            "endpoint": f"{self.BASE_URL}/payment_intents/{params['payment_intent_id']}/capture",
            "method": "POST",
            "payload": payload,
            "payment_intent_id": params["payment_intent_id"],
            "status": "succeeded",
        }

    def _create_refund(self, params: dict) -> dict:
        if "payment_intent_id" not in params and "charge_id" not in params:
            raise ValueError("payment_intent_id or charge_id is required")
        payload: dict = {}
        if "payment_intent_id" in params:
            payload["payment_intent"] = params["payment_intent_id"]
        if "charge_id" in params:
            payload["charge"] = params["charge_id"]
        if "amount" in params:
            payload["amount"] = params["amount"]
        payload["reason"] = params.get("reason", "requested_by_customer")
        return {
            "endpoint": f"{self.BASE_URL}/refunds",
            "method": "POST",
            "payload": payload,
            "refund_id": f"re_{uuid.uuid4().hex[:24]}",
            "status": "succeeded",
        }

    def _list_charges(self, params: dict) -> dict:
        limit = params.get("limit", 25)
        query: dict = {"limit": limit}
        if "customer_id" in params:
            query["customer"] = params["customer_id"]
        if "created_after" in params:
            query["created[gte]"] = params["created_after"]
        if "created_before" in params:
            query["created[lte]"] = params["created_before"]
        if "starting_after" in params:
            query["starting_after"] = params["starting_after"]
        return {
            "endpoint": f"{self.BASE_URL}/charges",
            "method": "GET",
            "query": query,
            "charges": [],
            "has_more": False,
        }

    def _create_subscription(self, params: dict) -> dict:
        if "customer_id" not in params or "price_id" not in params:
            raise ValueError("customer_id and price_id are required")
        payload: dict = {
            "customer": params["customer_id"],
            "items": [{"price": params["price_id"]}],
        }
        if "trial_period_days" in params:
            payload["trial_period_days"] = params["trial_period_days"]
        if "payment_behavior" in params:
            payload["payment_behavior"] = params["payment_behavior"]
        else:
            payload["payment_behavior"] = "default_incomplete"
        if "metadata" in params:
            payload["metadata"] = params["metadata"]
        return {
            "endpoint": f"{self.BASE_URL}/subscriptions",
            "method": "POST",
            "payload": payload,
            "subscription_id": f"sub_{uuid.uuid4().hex[:24]}",
            "status": "active" if "trial_period_days" not in params else "trialing",
        }

    def _cancel_subscription(self, params: dict) -> dict:
        if "subscription_id" not in params:
            raise ValueError("subscription_id is required")
        cancel_at_period_end = params.get("cancel_at_period_end", True)
        if cancel_at_period_end:
            return {
                "endpoint": f"{self.BASE_URL}/subscriptions/{params['subscription_id']}",
                "method": "POST",
                "payload": {"cancel_at_period_end": True},
                "subscription_id": params["subscription_id"],
                "status": "active",
                "cancel_at_period_end": True,
            }
        return {
            "endpoint": f"{self.BASE_URL}/subscriptions/{params['subscription_id']}",
            "method": "DELETE",
            "subscription_id": params["subscription_id"],
            "status": "canceled",
        }

    def _get_balance(self, params: dict) -> dict:
        return {
            "endpoint": f"{self.BASE_URL}/balance",
            "method": "GET",
            "balance": {
                "available": [],
                "pending": [],
                "connect_reserved": [],
            },
        }

    def _list_disputes(self, params: dict) -> dict:
        limit = params.get("limit", 25)
        query: dict = {"limit": limit}
        if "status" in params:
            query["status"] = params["status"]
        if "created_after" in params:
            query["created[gte]"] = params["created_after"]
        return {
            "endpoint": f"{self.BASE_URL}/disputes",
            "method": "GET",
            "query": query,
            "disputes": [],
            "has_more": False,
        }
