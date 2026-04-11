"""SMS adapter for ShopAI — wraps Twilio-style SMS APIs."""

import time
import uuid

from tools.base import (
    BaseToolAdapter,
    HealthStatus,
    RateConfig,
    ToolMetadata,
    ToolResult,
)


class SMSAdapter(BaseToolAdapter):
    tool_name = "sms"
    tool_category = "messaging"
    version = "1.0.0"

    BASE_URL = "https://api.twilio.com/2010-04-01"

    def __init__(self) -> None:
        self._credentials: dict = {}
        self._account_sid: str = ""
        self._from_number: str = ""

    def configure(self, credentials: dict) -> None:
        self._credentials = credentials
        self._account_sid = credentials.get("account_sid", "")
        self._from_number = credentials.get("from_number", "")

    def capabilities(self) -> list[str]:
        return [
            "send_sms",
            "send_bulk_sms",
            "check_delivery_status",
            "manage_opt_in",
            "manage_opt_out",
            "get_usage",
        ]

    def execute(self, action: str, params: dict) -> ToolResult:
        dispatch = {
            "send_sms": self._send_sms,
            "send_bulk_sms": self._send_bulk_sms,
            "check_delivery_status": self._check_delivery_status,
            "manage_opt_in": self._manage_opt_in,
            "manage_opt_out": self._manage_opt_out,
            "get_usage": self._get_usage,
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
        healthy = bool(self._credentials.get("auth_token") and self._account_sid)
        latency = (time.monotonic() - start) * 1000 + 90.0
        return HealthStatus(
            healthy=healthy,
            latency_ms=latency,
            last_check=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            error=None if healthy else "No Twilio credentials configured",
        )

    def get_rate_config(self) -> RateConfig:
        return RateConfig(requests_per_second=1.0, burst=10, daily_quota=10000)

    # ── handlers ──────────────────────────────────────────────

    def _send_sms(self, params: dict) -> dict:
        if "to" not in params or "body" not in params:
            raise ValueError("to and body are required")
        body = params["body"]
        if len(body) > 1600:
            raise ValueError("SMS body exceeds 1600-character limit")
        return {
            "endpoint": f"{self.BASE_URL}/Accounts/{self._account_sid}/Messages.json",
            "method": "POST",
            "payload": {
                "To": params["to"],
                "From": params.get("from_number", self._from_number),
                "Body": body,
                "StatusCallback": params.get("status_callback"),
            },
            "message_sid": f"SM{uuid.uuid4().hex[:32]}",
            "status": "queued",
            "segments": (len(body) // 160) + 1,
        }

    def _send_bulk_sms(self, params: dict) -> dict:
        if "recipients" not in params or "body" not in params:
            raise ValueError("recipients and body are required")
        recipients = params["recipients"]
        if not isinstance(recipients, list) or len(recipients) == 0:
            raise ValueError("recipients must be a non-empty list of phone numbers")
        body = params["body"]
        if len(body) > 1600:
            raise ValueError("SMS body exceeds 1600-character limit")
        return {
            "endpoint": f"{self.BASE_URL}/Accounts/{self._account_sid}/Messages.json",
            "method": "POST",
            "recipient_count": len(recipients),
            "body_preview": body[:80],
            "batch_id": str(uuid.uuid4()),
            "estimated_cost_usd": len(recipients) * 0.0079,
        }

    def _check_delivery_status(self, params: dict) -> dict:
        if "message_sid" not in params:
            raise ValueError("message_sid is required")
        return {
            "endpoint": f"{self.BASE_URL}/Accounts/{self._account_sid}/Messages/{params['message_sid']}.json",
            "method": "GET",
            "message_sid": params["message_sid"],
            "status": "delivered",
            "error_code": None,
            "error_message": None,
        }

    def _manage_opt_in(self, params: dict) -> dict:
        if "phone_number" not in params:
            raise ValueError("phone_number is required")
        return {
            "action": "opt_in",
            "phone_number": params["phone_number"],
            "consent_source": params.get("consent_source", "web_form"),
            "consent_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "opted_in",
        }

    def _manage_opt_out(self, params: dict) -> dict:
        if "phone_number" not in params:
            raise ValueError("phone_number is required")
        return {
            "action": "opt_out",
            "phone_number": params["phone_number"],
            "opt_out_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "opted_out",
        }

    def _get_usage(self, params: dict) -> dict:
        category = params.get("category", "sms")
        start_date = params.get("start_date", "2024-01-01")
        end_date = params.get("end_date", "2024-01-31")
        return {
            "endpoint": f"{self.BASE_URL}/Accounts/{self._account_sid}/Usage/Records.json",
            "method": "GET",
            "query": {
                "Category": category,
                "StartDate": start_date,
                "EndDate": end_date,
            },
            "usage": {
                "total_messages": 0,
                "total_cost_usd": 0.0,
                "inbound": 0,
                "outbound": 0,
            },
        }
