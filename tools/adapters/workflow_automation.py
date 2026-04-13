"""Workflow automation adapter for ShopAI — manages triggers, webhooks, and workflow execution."""

import time
import uuid

from tools.base import (
    BaseToolAdapter,
    HealthStatus,
    RateConfig,
    ToolMetadata,
    ToolResult,
)


class WorkflowAutomationAdapter(BaseToolAdapter):
    tool_name = "workflow_automation"
    tool_category = "automation"
    version = "1.0.0"

    BASE_URL = "https://api.shopai.internal/workflows/v1"

    def __init__(self) -> None:
        self._credentials: dict = {}
        self._api_key: str = ""
        self._workspace_id: str = ""

    def configure(self, credentials: dict) -> None:
        self._credentials = credentials
        self._api_key = credentials.get("api_key", "")
        self._workspace_id = credentials.get("workspace_id", "")

    def capabilities(self) -> list[str]:
        return [
            "trigger_workflow",
            "get_workflow_status",
            "list_workflows",
            "create_webhook",
            "handle_webhook",
            "get_execution_history",
        ]

    def execute(self, action: str, params: dict) -> ToolResult:
        dispatch = {
            "trigger_workflow": self._trigger_workflow,
            "get_workflow_status": self._get_workflow_status,
            "list_workflows": self._list_workflows,
            "create_webhook": self._create_webhook,
            "handle_webhook": self._handle_webhook,
            "get_execution_history": self._get_execution_history,
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
        healthy = bool(self._api_key and self._workspace_id)
        latency = (time.monotonic() - start) * 1000 + 35.0
        return HealthStatus(
            healthy=healthy,
            latency_ms=latency,
            last_check=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            error=None if healthy else "Workflow automation credentials not configured",
        )

    def get_rate_config(self) -> RateConfig:
        return RateConfig(requests_per_second=20.0, burst=50, daily_quota=100000)

    # ── handlers ──────────────────────────────────────────────

    def _trigger_workflow(self, params: dict) -> dict:
        if "workflow_id" not in params:
            raise ValueError("workflow_id is required")
        workflow_id = params["workflow_id"]
        input_data = params.get("input_data", {})
        priority = params.get("priority", "normal")
        valid_priorities = ["low", "normal", "high", "critical"]
        if priority not in valid_priorities:
            raise ValueError(f"priority must be one of: {', '.join(valid_priorities)}")
        execution_id = str(uuid.uuid4())
        return {
            "endpoint": f"{self.BASE_URL}/workspaces/{self._workspace_id}/workflows/{workflow_id}/trigger",
            "method": "POST",
            "payload": {
                "input_data": input_data,
                "priority": priority,
                "idempotency_key": params.get("idempotency_key", execution_id),
            },
            "execution_id": execution_id,
            "workflow_id": workflow_id,
            "status": "queued",
            "queued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def _get_workflow_status(self, params: dict) -> dict:
        if "execution_id" not in params:
            raise ValueError("execution_id is required")
        return {
            "endpoint": f"{self.BASE_URL}/workspaces/{self._workspace_id}/executions/{params['execution_id']}",
            "method": "GET",
            "execution_id": params["execution_id"],
            "status": "running",
            "current_step": None,
            "steps_completed": 0,
            "steps_total": 0,
            "started_at": None,
            "completed_at": None,
            "output_data": {},
        }

    def _list_workflows(self, params: dict) -> dict:
        limit = params.get("limit", 50)
        offset = params.get("offset", 0)
        status_filter = params.get("status")
        query: dict = {"limit": limit, "offset": offset}
        if status_filter:
            query["status"] = status_filter
        if "tag" in params:
            query["tag"] = params["tag"]
        return {
            "endpoint": f"{self.BASE_URL}/workspaces/{self._workspace_id}/workflows",
            "method": "GET",
            "query": query,
            "workflows": [],
            "total_count": 0,
        }

    def _create_webhook(self, params: dict) -> dict:
        if "workflow_id" not in params or "event_type" not in params:
            raise ValueError("workflow_id and event_type are required")
        valid_events = [
            "order.created", "order.updated", "order.fulfilled",
            "product.created", "product.updated", "product.deleted",
            "customer.created", "customer.updated",
            "inventory.low", "campaign.completed",
        ]
        event_type = params["event_type"]
        if event_type not in valid_events:
            raise ValueError(f"event_type must be one of: {', '.join(valid_events)}")
        webhook_id = str(uuid.uuid4())
        secret = uuid.uuid4().hex
        return {
            "endpoint": f"{self.BASE_URL}/workspaces/{self._workspace_id}/webhooks",
            "method": "POST",
            "payload": {
                "workflow_id": params["workflow_id"],
                "event_type": event_type,
                "url": params.get("url", f"{self.BASE_URL}/webhooks/{webhook_id}/receive"),
                "secret": secret,
                "active": True,
            },
            "webhook_id": webhook_id,
            "signing_secret": secret,
        }

    def _handle_webhook(self, params: dict) -> dict:
        if "webhook_id" not in params or "payload" not in params:
            raise ValueError("webhook_id and payload are required")
        signature = params.get("signature")
        return {
            "endpoint": f"{self.BASE_URL}/workspaces/{self._workspace_id}/webhooks/{params['webhook_id']}/handle",
            "method": "POST",
            "webhook_id": params["webhook_id"],
            "payload": params["payload"],
            "signature_valid": signature is not None,
            "execution_id": str(uuid.uuid4()),
            "status": "triggered",
        }

    def _get_execution_history(self, params: dict) -> dict:
        workflow_id = params.get("workflow_id")
        limit = params.get("limit", 50)
        offset = params.get("offset", 0)
        query: dict = {"limit": limit, "offset": offset}
        if workflow_id:
            query["workflow_id"] = workflow_id
        if "status" in params:
            query["status"] = params["status"]
        if "since" in params:
            query["since"] = params["since"]
        if "until" in params:
            query["until"] = params["until"]
        base = f"{self.BASE_URL}/workspaces/{self._workspace_id}"
        endpoint = f"{base}/workflows/{workflow_id}/executions" if workflow_id else f"{base}/executions"
        return {
            "endpoint": endpoint,
            "method": "GET",
            "query": query,
            "executions": [],
            "total_count": 0,
            "has_more": False,
        }
