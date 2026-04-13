"""ZapierAdapter — Zapier Natural Language Actions (NLA) API.

Zapier connects 6,000+ apps. The NLA API lets AI assistants
trigger Zaps using natural language instructions. Use cases
for Shopify stores:

  * **Order notifications** — send Slack messages, create Trello
    cards when orders come in
  * **Data sync** — push customer data to Google Sheets, Airtable
  * **Marketing** — add subscribers to Mailchimp, trigger drip
    campaigns
  * **Support** — create Zendesk tickets, update CRM records

Capabilities:
  * AUTOMATION_TRIGGER   — execute an exposed action by name
  * AUTOMATION_LIST_ZAPS — list available exposed actions

Authentication: Bearer token (NLA API key).
Free tier: 100 tasks/month.
Pricing: from $19.99/month for 750 tasks.

Reference: https://nla.zapier.com/docs
"""
from __future__ import annotations

from typing import Any

from ..base import AdapterResult, Capability
from ..errors import AdapterValidationError
from ._base import AutomationBaseAdapter


class ZapierAdapter(AutomationBaseAdapter):
    name = "zapier"
    base_url = "https://nla.zapier.com/api/v1"
    config_alias = "zapier_nla"

    priority = 85
    cost_per_call = 0.0

    # ── Trigger an action ──────────────────────────────────────

    def _do_trigger(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        action_id = params.get("action_id")
        if not action_id:
            raise AdapterValidationError(
                self.name, "'action_id' is required",
            )

        instructions = params.get("instructions", "")
        if not instructions:
            raise AdapterValidationError(
                self.name, "'instructions' (natural language) is required",
            )

        url = f"{self.base_url}/exposed/{action_id}/execute/"
        body = {
            "instructions": instructions,
        }
        # Optional params override
        if params.get("params"):
            body["params"] = params["params"]

        raw = self._http_request("POST", url, body=body)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "action_id": action_id,
                "status": raw.get("status", ""),
                "result": raw.get("result", raw.get("output", "")),
            },
            raw=raw,
        )

    # ── List available actions ─────────────────────────────────

    def _do_list_zaps(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        url = f"{self.base_url}/exposed/"
        raw = self._http_request("GET", url)

        actions = []
        for action in raw.get("results", []):
            actions.append({
                "id": action.get("id", ""),
                "description": action.get("description", ""),
                "params": action.get("params", {}),
            })

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"actions": actions, "count": len(actions)},
            raw=raw,
        )
