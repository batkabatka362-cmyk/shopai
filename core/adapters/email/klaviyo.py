"""KlaviyoAdapter -- Klaviyo e-commerce email ESP.

Klaviyo (https://www.klaviyo.com) is the dominant Shopify-
oriented email platform. Built specifically for e-commerce
flows (cart-abandon / welcome / browse-abandon / post-purchase),
making it the canonical fit when ShopAI's cart_recovery /
welcome_series / browse_recovery / loyalty engines need
delivery substrate.

Why Klaviyo over Brevo/Resend for an e-commerce empire:

  * Native Shopify integration -- pulls orders, products,
    customer profiles automatically. Brevo + Resend are
    transactional-first, e-commerce-second.
  * Built-in flows (cart-abandon, post-purchase) that the
    ShopAI loyalty / cart_recovery engines tap directly --
    less template wiring on the operator's side.
  * Profile-aware send -- Klaviyo tracks per-customer
    engagement + suppresses low-engagement recipients
    automatically. Improves deliverability vs flat sends.

Why it's secondary to Brevo on free tier:
  * Klaviyo's free tier is 500 email-sends/month vs Brevo's
    9,000/day -- Brevo wins on raw volume for cold-start.
  * Once empire is earning, Klaviyo's paid tier ($45/mo
    starter) is the upgrade path for e-commerce empires.

Auth: single private API key (Bearer-style with custom
header ``Authorization: Klaviyo-API-Key <KEY>``). Operator
generates from Klaviyo Account -> Settings -> API Keys ->
Private API Keys -> Create Key (full access).

Endpoints documented at:
https://developers.klaviyo.com/en/reference/api_overview

W963-103 ships a SKELETON:
  * Auth + config wiring complete
  * Capability dispatch in place
  * Concrete send endpoint marked TODO until operator
    confirms Klaviyo's chosen send-flow vs send-event vs
    create-event endpoint (Klaviyo has 3 distinct ways to
    trigger an email, depending on whether it's a one-off
    transactional, a triggered flow event, or a campaign
    blast).
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from ..errors import AdapterError
from ._base import EmailBaseAdapter

logger = get_logger("adapters.email.klaviyo")


class KlaviyoAdapter(EmailBaseAdapter):
    """Klaviyo e-commerce email adapter (skeleton).

    Wired into the bootstrap registry so api-status surfaces
    Klaviyo as a configurable email option. Concrete send-
    endpoint logic lands when operator confirms target
    Klaviyo flow type (event-trigger vs campaign vs
    transactional).
    """

    name = "klaviyo"
    base_url = "https://a.klaviyo.com/api"
    config_alias = "klaviyo"

    # Below Brevo (90) -- Brevo wins router default because
    # of higher free-tier volume. Above Resend (75) because
    # Klaviyo's e-commerce-specific flows are a better fit
    # for cart_recovery / loyalty / browse_recovery once
    # the operator opts in explicitly.
    priority = 80
    cost_per_call = 0.0
    # Free tier: 500 emails/month total (no daily breakdown
    # published; conservative 30 per day as guidance).
    free_tier_daily_limit = 30
    free_tier_monthly_limit = 500

    # Klaviyo uses a custom Authorization scheme:
    #   Authorization: Klaviyo-API-Key <KEY>
    # Override the base's Bearer-default to match.
    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": (
                f"Klaviyo-API-Key {self._api_key()}"
            ),
            "Accept": "application/json",
            "revision": "2024-10-15",
            "Content-Type": "application/json",
        }

    def _send_url(self) -> str:
        # Klaviyo has 3 distinct send paths:
        #   POST /api/events                     (event trigger)
        #   POST /api/campaign-send-jobs         (campaign blast)
        #   POST /api/template-render            (transactional)
        # The right choice depends on the message kind --
        # ShopAI's cart_recovery / browse_recovery / loyalty
        # emails are flow-triggered events, so events is the
        # baseline endpoint. Operator can opt into the
        # campaign or template paths once confirmed.
        return f"{self.base_url}/events"

    def _build_payload(
        self, message: dict[str, Any],
    ) -> dict[str, Any]:
        """Skeleton -- builds a minimal Klaviyo "events" body.

        Klaviyo's events endpoint expects a JSON:API-style
        wrapper. The actual transactional render is handled
        Klaviyo-side by mapping the event name to a pre-
        configured flow on the operator's account. ShopAI
        sends the metric + customer profile + custom
        properties; Klaviyo renders + delivers.

        For the skeleton we build the SHAPE correctly but
        the operator needs to confirm:
          * which metric name to use (configured per flow)
          * which custom properties to pass through

        Raises AdapterError at send-time to keep the skeleton
        honest -- caller knows the endpoint isn't yet fully
        wired.
        """
        # Klaviyo events shape (JSON:API):
        # {
        #   "data": {
        #     "type": "event",
        #     "attributes": {
        #       "properties": {...},
        #       "metric": {
        #         "data": {
        #           "type": "metric",
        #           "attributes": {"name": "<metric name>"}
        #         }
        #       },
        #       "profile": {
        #         "data": {
        #           "type": "profile",
        #           "attributes": {"email": "..."}
        #         }
        #       }
        #     }
        #   }
        # }
        metric = (
            (message.get("tags") or ["transactional"])[0]
            if message.get("tags") else "transactional"
        )
        return {
            "data": {
                "type": "event",
                "attributes": {
                    "properties": {
                        "subject": message.get("subject", ""),
                        "html_body": message.get("html", ""),
                        "text_body": message.get("text", ""),
                        "reply_to": message.get(
                            "reply_to", "",
                        ),
                    },
                    "metric": {
                        "data": {
                            "type": "metric",
                            "attributes": {"name": metric},
                        },
                    },
                    "profile": {
                        "data": {
                            "type": "profile",
                            "attributes": {
                                "email": message["to"],
                            },
                        },
                    },
                },
            },
        }

    def _parse_response(self, raw: Any) -> str:
        """Klaviyo events endpoint returns 202 Accepted +
        empty body on success. Generated event id is NOT
        returned (intentional design -- Klaviyo is the
        source-of-truth, not the caller).

        Skeleton returns the empty string -- caller can
        treat this as "submitted but no echo id". Honest:
        Klaviyo's send-flow is fire-and-track-via-webhook,
        not request/response.
        """
        if not isinstance(raw, dict) and raw != "":
            # Real Klaviyo response should be empty / None;
            # if we got something else, flag it.
            logger.debug(
                "klaviyo events: unexpected response shape: "
                "%s", type(raw).__name__,
            )
        return ""
