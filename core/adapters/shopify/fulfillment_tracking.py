"""ShopifyFulfillmentTrackingAdapter — tracking update + cancel.

Companion to ``fulfillment.py`` (create + lookup) and
``fulfillment_hold.py``. The post-creation tracking surface is
how ShopAI's fulfillment + customer-service engines keep
shipments visible after they leave the warehouse:

  * **Late tracking attach.** 3PL syncs back tracking numbers
    asynchronously after the fulfillment is created. Engine
    polls the WMS, then calls ``fulfillmentTrackingInfoUpdate``
    with the carrier + number(s) + URL(s) so customer notifications
    fire and the storefront's "track package" button works.
  * **Carrier swap.** First carrier returned the package; ops
    rebooked through a different carrier. Update overrides the
    old tracking record without spawning a new fulfillment.
  * **Cancellation.** Fulfillment was created in error (wrong
    location, wrong line items). ``fulfillmentCancel`` reverses
    it and returns inventory to the original allocation.

Capabilities:

  * ``SHOPIFY_UPDATE_FULFILLMENT_TRACKING`` —
    fulfillmentTrackingInfoUpdate. Pattern A: fulfillmentId +
    notifyCustomer at field level; trackingInfoInput is a
    separate field-level arg, not embedded.
  * ``SHOPIFY_CANCEL_FULFILLMENT`` — fulfillmentCancel. Pattern
    A: id at field level.

Pattern F: both mutations use the typed ``UserError`` variant
(no ``code``). Drop ``code`` from the userErrors selections.

The tracking input accepts both singular (``number`` / ``url``)
and plural (``numbers`` / ``urls``) forms. Adapter prefers
plural when the caller passes a list; engines that send one
number can use either shape.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_FULFILLMENT_FIELDS = """
id
status
displayStatus
trackingInfo {
  number
  url
  company
}
""".strip()


_UPDATE_TRACKING_MUTATION = f"""
mutation fulfillmentTrackingInfoUpdate(
  $fulfillmentId: ID!,
  $trackingInfoInput: FulfillmentTrackingInput!,
  $notifyCustomer: Boolean
) {{
  fulfillmentTrackingInfoUpdate(
    fulfillmentId: $fulfillmentId,
    trackingInfoInput: $trackingInfoInput,
    notifyCustomer: $notifyCustomer
  ) {{
    fulfillment {{
      {_FULFILLMENT_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_CANCEL_FULFILLMENT_MUTATION = f"""
mutation fulfillmentCancel($id: ID!) {{
  fulfillmentCancel(id: $id) {{
    fulfillment {{
      {_FULFILLMENT_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


class ShopifyFulfillmentTrackingAdapter(ShopifyBaseAdapter):
    name = "shopify_fulfillment_tracking"
    capabilities = {
        Capability.SHOPIFY_UPDATE_FULFILLMENT_TRACKING,
        Capability.SHOPIFY_CANCEL_FULFILLMENT,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_UPDATE_FULFILLMENT_TRACKING:
            return self._update_tracking(params)
        if capability == Capability.SHOPIFY_CANCEL_FULFILLMENT:
            return self._cancel(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Update tracking ────────────────────────────────────────────

    def _update_tracking(self, params: dict[str, Any]) -> Any:
        fulfillment_id = (
            params.get("fulfillment_id")
            or params.get("fulfillmentId")
            or params.get("id")
        )
        if not isinstance(fulfillment_id, str) or not fulfillment_id.strip():
            raise AdapterValidationError(
                self.name,
                "'fulfillment_id' (Shopify GID for the fulfillment) "
                "is required",
            )
        tracking_input = self._build_tracking_input(params)

        variables: dict[str, Any] = {
            "fulfillmentId": fulfillment_id.strip(),
            "trackingInfoInput": tracking_input,
        }
        notify = params.get("notify_customer")
        if notify is None:
            notify = params.get("notifyCustomer")
        if notify is not None:
            variables["notifyCustomer"] = bool(notify)

        data = self._gql(_UPDATE_TRACKING_MUTATION, variables)
        self._check_user_errors(data, "fulfillmentTrackingInfoUpdate")
        payload = data.get("fulfillmentTrackingInfoUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_FULFILLMENT_TRACKING,
            data={
                "fulfillment": self._normalise_fulfillment(
                    payload.get("fulfillment") or {}
                ),
            },
        )

    # ── Cancel ─────────────────────────────────────────────────────

    def _cancel(self, params: dict[str, Any]) -> Any:
        fulfillment_id = (
            params.get("id")
            or params.get("fulfillment_id")
            or params.get("fulfillmentId")
        )
        if not isinstance(fulfillment_id, str) or not fulfillment_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the fulfillment) is required",
            )
        data = self._gql(_CANCEL_FULFILLMENT_MUTATION, {
            "id": fulfillment_id.strip(),
        })
        self._check_user_errors(data, "fulfillmentCancel")
        payload = data.get("fulfillmentCancel") or {}
        return self._success(
            Capability.SHOPIFY_CANCEL_FULFILLMENT,
            data={
                "fulfillment": self._normalise_fulfillment(
                    payload.get("fulfillment") or {}
                ),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _build_tracking_input(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        company = params.get("company") or params.get("carrier")
        if company is not None:
            if not isinstance(company, str):
                raise AdapterValidationError(
                    self.name, "'company' must be a string",
                )
            company = company.strip()
            if company:
                out["company"] = company

        # Plural numbers/urls take priority; singular form falls back.
        numbers = (
            params.get("numbers")
            or params.get("tracking_numbers")
            or params.get("trackingNumbers")
        )
        if numbers is not None:
            if not isinstance(numbers, list) or not all(
                isinstance(n, str) for n in numbers
            ):
                raise AdapterValidationError(
                    self.name,
                    "'numbers' must be a list of strings",
                )
            cleaned = [n.strip() for n in numbers if n.strip()]
            if cleaned:
                out["numbers"] = cleaned
        elif "number" in params and params["number"] is not None:
            number = params["number"]
            if not isinstance(number, str):
                raise AdapterValidationError(
                    self.name, "'number' must be a string",
                )
            number = number.strip()
            if number:
                out["number"] = number

        urls = params.get("urls") or params.get("tracking_urls")
        if urls is not None:
            if not isinstance(urls, list) or not all(
                isinstance(u, str) for u in urls
            ):
                raise AdapterValidationError(
                    self.name, "'urls' must be a list of strings",
                )
            cleaned = [u.strip() for u in urls if u.strip()]
            if cleaned:
                out["urls"] = cleaned
        elif "url" in params and params["url"] is not None:
            url = params["url"]
            if not isinstance(url, str):
                raise AdapterValidationError(
                    self.name, "'url' must be a string",
                )
            url = url.strip()
            if url:
                out["url"] = url

        if not out:
            raise AdapterValidationError(
                self.name,
                "'trackingInfoInput' had no fields — pass at least one "
                "of company / number / numbers / url / urls",
            )
        return out

    @staticmethod
    def _normalise_fulfillment(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        tracking_raw = node.get("trackingInfo") or []
        tracking: list[dict[str, str]] = []
        if isinstance(tracking_raw, list):
            for t in tracking_raw:
                if not isinstance(t, dict):
                    continue
                tracking.append({
                    "number": t.get("number", "") or "",
                    "url": t.get("url", "") or "",
                    "company": t.get("company", "") or "",
                })
        return {
            "id": node.get("id", "") or "",
            "status": node.get("status", "") or "",
            "display_status": node.get("displayStatus", "") or "",
            "tracking": tracking,
        }
