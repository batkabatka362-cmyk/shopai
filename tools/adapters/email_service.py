"""Email service adapter for ShopAI — supports Omnisend (primary) and SendGrid (fallback)."""

import time
import uuid

from tools.base import (
    BaseToolAdapter,
    HealthStatus,
    RateConfig,
    ToolMetadata,
    ToolResult,
)


class EmailServiceAdapter(BaseToolAdapter):
    tool_name = "email_service"
    tool_category = "messaging"
    version = "1.0.0"

    OMNISEND_BASE = "https://api.omnisend.com/v3"
    SENDGRID_BASE = "https://api.sendgrid.com/v3"

    def __init__(self) -> None:
        self._credentials: dict = {}
        self._omnisend_api_key: str = ""
        self._sendgrid_api_key: str = ""
        self._default_from_email: str = ""
        self._provider: str = "omnisend"  # "omnisend" or "sendgrid"

    def configure(self, credentials: dict) -> None:
        self._credentials = credentials
        self._omnisend_api_key = credentials.get("omnisend_api_key", "")
        self._sendgrid_api_key = credentials.get("sendgrid_api_key", "")
        self._default_from_email = credentials.get("from_email", "noreply@shop.com")
        # Use Omnisend when available, fall back to SendGrid
        if self._omnisend_api_key:
            self._provider = "omnisend"
        elif self._sendgrid_api_key:
            self._provider = "sendgrid"

    def capabilities(self) -> list[str]:
        return [
            "send_email",
            "send_bulk",
            "create_campaign",
            "list_subscribers",
            "add_subscriber",
            "remove_subscriber",
            "create_automation",
            "get_campaign_metrics",
        ]

    def execute(self, action: str, params: dict) -> ToolResult:
        dispatch = {
            "send_email": self._send_email,
            "send_bulk": self._send_bulk,
            "create_campaign": self._create_campaign,
            "list_subscribers": self._list_subscribers,
            "add_subscriber": self._add_subscriber,
            "remove_subscriber": self._remove_subscriber,
            "create_automation": self._create_automation,
            "get_campaign_metrics": self._get_campaign_metrics,
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
        healthy = bool(self._omnisend_api_key or self._sendgrid_api_key)
        latency = (time.monotonic() - start) * 1000 + 70.0
        return HealthStatus(
            healthy=healthy,
            latency_ms=latency,
            last_check=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            error=None if healthy else "No email service API key configured",
        )

    def get_rate_config(self) -> RateConfig:
        if self._provider == "omnisend":
            return RateConfig(requests_per_second=10.0, burst=50, daily_quota=None)
        return RateConfig(requests_per_second=3.0, burst=30, daily_quota=100000)

    # ── handlers ──────────────────────────────────────────────

    def _send_email(self, params: dict) -> dict:
        if "to" not in params or "subject" not in params:
            raise ValueError("to and subject are required")
        if self._provider == "omnisend":
            return {
                "provider": "omnisend",
                "endpoint": f"{self.OMNISEND_BASE}/campaigns",
                "method": "POST",
                "payload": {
                    "type": "email",
                    "recipientEmail": params["to"],
                    "subject": params["subject"],
                    "htmlBody": params.get("html_body", ""),
                    "plainBody": params.get("plain_body", ""),
                    "senderEmail": params.get("from_email", self._default_from_email),
                },
                "message_id": str(uuid.uuid4()),
            }
        return {
            "provider": "sendgrid",
            "endpoint": f"{self.SENDGRID_BASE}/mail/send",
            "method": "POST",
            "payload": {
                "personalizations": [{"to": [{"email": params["to"]}]}],
                "from": {"email": params.get("from_email", self._default_from_email)},
                "subject": params["subject"],
                "content": [
                    {"type": "text/plain", "value": params.get("plain_body", "")},
                    {"type": "text/html", "value": params.get("html_body", "")},
                ],
            },
            "message_id": str(uuid.uuid4()),
        }

    def _send_bulk(self, params: dict) -> dict:
        if "recipients" not in params or "subject" not in params:
            raise ValueError("recipients and subject are required")
        recipients = params["recipients"]
        if not isinstance(recipients, list) or len(recipients) == 0:
            raise ValueError("recipients must be a non-empty list of email addresses")
        return {
            "provider": self._provider,
            "endpoint": f"{self.SENDGRID_BASE}/mail/send" if self._provider == "sendgrid"
            else f"{self.OMNISEND_BASE}/campaigns",
            "method": "POST",
            "recipient_count": len(recipients),
            "subject": params["subject"],
            "batch_id": str(uuid.uuid4()),
        }

    def _create_campaign(self, params: dict) -> dict:
        if "name" not in params or "subject" not in params:
            raise ValueError("name and subject are required")
        return {
            "provider": self._provider,
            "endpoint": f"{self.OMNISEND_BASE}/campaigns" if self._provider == "omnisend"
            else f"{self.SENDGRID_BASE}/marketing/singlesends",
            "method": "POST",
            "payload": {
                "name": params["name"],
                "subject": params["subject"],
                "segment_ids": params.get("segment_ids", []),
                "html_body": params.get("html_body", ""),
                "send_at": params.get("send_at"),
            },
            "campaign_id": str(uuid.uuid4()),
        }

    def _list_subscribers(self, params: dict) -> dict:
        limit = params.get("limit", 100)
        offset = params.get("offset", 0)
        return {
            "provider": self._provider,
            "endpoint": f"{self.OMNISEND_BASE}/contacts" if self._provider == "omnisend"
            else f"{self.SENDGRID_BASE}/marketing/contacts",
            "method": "GET",
            "query": {"limit": limit, "offset": offset},
            "subscribers": [],
            "total_count": 0,
        }

    def _add_subscriber(self, params: dict) -> dict:
        if "email" not in params:
            raise ValueError("email is required")
        return {
            "provider": self._provider,
            "endpoint": f"{self.OMNISEND_BASE}/contacts" if self._provider == "omnisend"
            else f"{self.SENDGRID_BASE}/marketing/contacts",
            "method": "POST",
            "payload": {
                "email": params["email"],
                "firstName": params.get("first_name", ""),
                "lastName": params.get("last_name", ""),
                "tags": params.get("tags", []),
                "status": "subscribed",
            },
            "contact_id": str(uuid.uuid4()),
        }

    def _remove_subscriber(self, params: dict) -> dict:
        if "email" not in params:
            raise ValueError("email is required")
        return {
            "provider": self._provider,
            "endpoint": f"{self.OMNISEND_BASE}/contacts/{params['email']}" if self._provider == "omnisend"
            else f"{self.SENDGRID_BASE}/marketing/contacts",
            "method": "DELETE",
            "email": params["email"],
        }

    def _create_automation(self, params: dict) -> dict:
        if "name" not in params or "trigger" not in params:
            raise ValueError("name and trigger are required")
        valid_triggers = ["welcome", "abandoned_cart", "post_purchase", "win_back", "birthday"]
        if params["trigger"] not in valid_triggers:
            raise ValueError(f"trigger must be one of: {', '.join(valid_triggers)}")
        return {
            "provider": self._provider,
            "endpoint": f"{self.OMNISEND_BASE}/automations" if self._provider == "omnisend"
            else f"{self.SENDGRID_BASE}/marketing/automations",
            "method": "POST",
            "payload": {
                "name": params["name"],
                "trigger": params["trigger"],
                "delay_minutes": params.get("delay_minutes", 0),
                "emails": params.get("emails", []),
                "status": "draft",
            },
            "automation_id": str(uuid.uuid4()),
        }

    def _get_campaign_metrics(self, params: dict) -> dict:
        if "campaign_id" not in params:
            raise ValueError("campaign_id is required")
        return {
            "provider": self._provider,
            "endpoint": f"{self.OMNISEND_BASE}/campaigns/{params['campaign_id']}" if self._provider == "omnisend"
            else f"{self.SENDGRID_BASE}/marketing/stats/singlesends/{params['campaign_id']}",
            "method": "GET",
            "campaign_id": params["campaign_id"],
            "metrics": {
                "sent": 0,
                "delivered": 0,
                "opened": 0,
                "clicked": 0,
                "bounced": 0,
                "unsubscribed": 0,
                "open_rate": 0.0,
                "click_rate": 0.0,
            },
        }
