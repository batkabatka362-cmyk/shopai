"""ShopifyOrderRiskAssessmentAdapter — manual risk assessments.

Companion to ``risk.py`` (read-only — list / get assessments
that other apps already published). This adapter ships the
write side: ShopAI's risk engine submits its OWN assessment to
the order, taking the place of (or augmenting) the assessments
Shopify's built-in fraud check + third-party apps publish.

Concrete flows:

  * **Internal fraud model verdict.** ShopAI's ML scoring
    engine flags an order with a NEGATIVE sentiment fact
    ("velocity check: 11 orders in 60 minutes") + HIGH risk
    level. The downstream cancellation engine watches for
    HIGH assessments and pauses fulfillment.
  * **Manual operator override.** Operator inspects an order,
    decides it's clean, and pushes a LOW assessment with a
    POSITIVE fact ("verified phone number with customer"). The
    fulfillment engine clears the hold.
  * **Provider attribution.** Each assessment is attributed to
    the app that submitted it (via ``provider``), so the
    timeline tells a coherent story when multiple sources
    contribute facts.

Capability:

  * ``SHOPIFY_CREATE_ORDER_RISK_ASSESSMENT`` —
    orderRiskAssessmentCreate.

Pattern A applies on the input dict — the orderId lives inside
``OrderRiskAssessmentCreateInput.orderId`` rather than at the
GraphQL field level (only one mutation arg:
``orderRiskAssessmentInput``).

Risk level enum: HIGH / MEDIUM / LOW / NONE / PENDING.
Fact sentiment enum: POSITIVE / NEUTRAL / NEGATIVE.

The userError envelope is ``OrderRiskAssessmentCreateUserError``
(has ``code``).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_CREATE_RISK_ASSESSMENT_MUTATION = """
mutation orderRiskAssessmentCreate(
  $orderRiskAssessmentInput: OrderRiskAssessmentCreateInput!
) {
  orderRiskAssessmentCreate(
    orderRiskAssessmentInput: $orderRiskAssessmentInput
  ) {
    orderRiskAssessment {
      riskLevel
      facts {
        sentiment
        description
      }
      provider {
        id
        title
      }
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_VALID_RISK_LEVELS = {"HIGH", "MEDIUM", "LOW", "NONE", "PENDING"}
_VALID_SENTIMENTS = {"POSITIVE", "NEUTRAL", "NEGATIVE"}


class ShopifyOrderRiskAssessmentAdapter(ShopifyBaseAdapter):
    name = "shopify_order_risk_assessment"
    capabilities = {Capability.SHOPIFY_CREATE_ORDER_RISK_ASSESSMENT}
    required_scopes = frozenset({"read_orders"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_ORDER_RISK_ASSESSMENT:
            return self._create(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    def _create(self, params: dict[str, Any]) -> Any:
        order_id = (
            params.get("order_id")
            or params.get("orderId")
            or params.get("id")
        )
        if not isinstance(order_id, str) or not order_id.strip():
            raise AdapterValidationError(
                self.name,
                "'order_id' (Shopify GID for the order) is required",
            )

        risk_level_raw = (
            params.get("risk_level") or params.get("riskLevel")
        )
        if not isinstance(risk_level_raw, str) or not risk_level_raw.strip():
            raise AdapterValidationError(
                self.name,
                f"'risk_level' is required — one of {sorted(_VALID_RISK_LEVELS)}",
            )
        risk_level = risk_level_raw.strip().upper()
        if risk_level not in _VALID_RISK_LEVELS:
            raise AdapterValidationError(
                self.name,
                f"'risk_level' must be one of {sorted(_VALID_RISK_LEVELS)}",
            )

        facts = self._build_facts(params.get("facts"))

        input_dict = {
            "orderId": order_id.strip(),
            "riskLevel": risk_level,
            "facts": facts,
        }
        data = self._gql(_CREATE_RISK_ASSESSMENT_MUTATION, {
            "orderRiskAssessmentInput": input_dict,
        })
        self._check_user_errors(data, "orderRiskAssessmentCreate")
        payload = data.get("orderRiskAssessmentCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_ORDER_RISK_ASSESSMENT,
            data={
                "assessment": self._normalise_assessment(
                    payload.get("orderRiskAssessment") or {}
                ),
            },
        )

    def _build_facts(self, raw: Any) -> list[dict[str, str]]:
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                "'facts' must be a non-empty list of "
                "{sentiment, description} dicts",
            )
        out: list[dict[str, str]] = []
        for i, fact in enumerate(raw):
            if not isinstance(fact, dict):
                raise AdapterValidationError(
                    self.name, f"facts[{i}] must be a dict",
                )
            sentiment_raw = fact.get("sentiment")
            description = fact.get("description")
            if not isinstance(sentiment_raw, str) or \
                    not sentiment_raw.strip():
                raise AdapterValidationError(
                    self.name,
                    f"facts[{i}] missing 'sentiment' "
                    f"(one of {sorted(_VALID_SENTIMENTS)})",
                )
            sentiment = sentiment_raw.strip().upper()
            if sentiment not in _VALID_SENTIMENTS:
                raise AdapterValidationError(
                    self.name,
                    f"facts[{i}].sentiment must be one of "
                    f"{sorted(_VALID_SENTIMENTS)}",
                )
            if not isinstance(description, str) or not description.strip():
                raise AdapterValidationError(
                    self.name,
                    f"facts[{i}] missing 'description' (non-empty string)",
                )
            out.append({
                "sentiment": sentiment,
                "description": description.strip(),
            })
        return out

    @staticmethod
    def _normalise_assessment(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        provider = node.get("provider") or {}
        facts_raw = node.get("facts") or []
        facts: list[dict[str, str]] = []
        if isinstance(facts_raw, list):
            for fact in facts_raw:
                if not isinstance(fact, dict):
                    continue
                facts.append({
                    "sentiment": fact.get("sentiment", "") or "",
                    "description": fact.get("description", "") or "",
                })
        return {
            "risk_level": node.get("riskLevel", "") or "",
            "facts": facts,
            "provider_id": (
                provider.get("id", "")
                if isinstance(provider, dict) else ""
            ) or "",
            "provider_title": (
                provider.get("title", "")
                if isinstance(provider, dict) else ""
            ) or "",
        }
