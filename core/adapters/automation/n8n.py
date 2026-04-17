"""N8NAdapter — n8n workflow automation (self-hosted or cloud).

n8n is a fair-code workflow automation platform ("Zapier for
developers") that connects 400+ apps. Unlike Zapier, n8n is
self-hostable and source-available, which matters for stores
handling PII (EU merchants, HIPAA workflows).

This adapter supports two trigger modes:

  * **Webhook trigger** — POST a JSON payload to a workflow's
    webhook node (no API key needed beyond the URL; n8n cloud
    and self-hosted both support this). Use by setting
    ``webhook_url`` in params, or ``webhook_path`` to combine
    with ``N8N_BASE_URL``.
  * **Workflow execute** — POST to
    ``/api/v1/workflows/{id}/execute`` using the
    ``X-N8N-API-KEY`` header. Requires ``N8N_API_KEY``.

Capabilities:
  * AUTOMATION_TRIGGER   — fire a workflow (webhook OR execute)
  * AUTOMATION_LIST_ZAPS — list active workflows on the instance

Authentication: ``X-N8N-API-KEY`` header (self-hosted API key or
cloud personal access token).

Reference: https://docs.n8n.io/api/
"""
from __future__ import annotations

from typing import Any

from ..base import AdapterResult, Capability
from ..config import get_config
from ..errors import AdapterNotConfigured, AdapterValidationError
from ._base import AutomationBaseAdapter


class N8NAdapter(AutomationBaseAdapter):
    name = "n8n"
    config_alias = "n8n_api_key"

    priority = 80
    cost_per_call = 0.0

    @property
    def base_url(self) -> str:  # type: ignore[override]
        url = get_config().get("n8n_url")
        return url.rstrip("/") if url else ""

    def is_configured(self) -> bool:
        # n8n works in two modes:
        #  - webhook-only: only N8N_BASE_URL is strictly required
        #    (individual webhooks may be secured by the workflow).
        #  - API mode:      needs N8N_BASE_URL + N8N_API_KEY.
        # We report "configured" whenever either mode can work.
        return bool(get_config().get("n8n_url"))

    def _auth_headers(self) -> dict[str, str]:
        key = get_config().get("n8n_api_key")
        hdrs = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if key:
            hdrs["X-N8N-API-KEY"] = key
        return hdrs

    def _require_api_key(self) -> None:
        if not get_config().get("n8n_api_key"):
            raise AdapterNotConfigured(
                self.name,
                "missing N8N_API_KEY (required for workflow API)",
            )

    # ── Trigger a workflow ─────────────────────────────────────

    def _do_trigger(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        data = params.get("data") or params.get("payload") or {}

        # Mode 1: direct webhook URL given.
        webhook_url = params.get("webhook_url")
        if webhook_url:
            raw = self._http_request(
                "POST", webhook_url, body=data,
                headers={"Content-Type": "application/json"},
            )
            return AdapterResult.success(
                adapter=self.name,
                capability=capability.value,
                data={
                    "mode": "webhook",
                    "webhook_url": webhook_url,
                    "triggered": True,
                    "result": raw,
                },
                raw=raw,
            )

        # Mode 2: webhook path (combined with base url).
        webhook_path = params.get("webhook_path")
        if webhook_path:
            if not self.base_url:
                raise AdapterNotConfigured(
                    self.name, "missing N8N_BASE_URL",
                )
            path = webhook_path.lstrip("/")
            url = f"{self.base_url}/webhook/{path}"
            raw = self._http_request(
                "POST", url, body=data,
                headers={"Content-Type": "application/json"},
            )
            return AdapterResult.success(
                adapter=self.name,
                capability=capability.value,
                data={
                    "mode": "webhook",
                    "webhook_path": webhook_path,
                    "triggered": True,
                    "result": raw,
                },
                raw=raw,
            )

        # Mode 3: workflow id via API.
        workflow_id = params.get("workflow_id") or params.get("action_id")
        if not workflow_id:
            raise AdapterValidationError(
                self.name,
                "one of 'webhook_url', 'webhook_path', or "
                "'workflow_id' is required",
            )
        if not self.base_url:
            raise AdapterNotConfigured(
                self.name, "missing N8N_BASE_URL",
            )
        self._require_api_key()

        url = f"{self.base_url}/api/v1/workflows/{workflow_id}/execute"
        raw = self._http_request("POST", url, body={"data": data})

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "mode": "api",
                "workflow_id": str(workflow_id),
                "execution_id": raw.get("data", {}).get("executionId", "")
                if isinstance(raw.get("data"), dict) else "",
                "triggered": True,
            },
            raw=raw,
        )

    # ── List workflows ─────────────────────────────────────────

    def _do_list_zaps(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        if not self.base_url:
            raise AdapterNotConfigured(
                self.name, "missing N8N_BASE_URL",
            )
        self._require_api_key()

        active_only = bool(params.get("active_only", False))
        url = f"{self.base_url}/api/v1/workflows"
        if active_only:
            url += "?active=true"

        raw = self._http_request("GET", url)

        workflows = []
        for wf in raw.get("data", []):
            workflows.append({
                "id": str(wf.get("id", "")),
                "name": wf.get("name", ""),
                "active": bool(wf.get("active", False)),
                "tags": [t.get("name", "") for t in wf.get("tags", [])],
                "updated_at": wf.get("updatedAt", ""),
            })

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "actions": workflows,
                "count": len(workflows),
            },
            raw=raw,
        )
