"""ShopifyRiskAdapter — fraud risk assessment.

Wraps Shopify's ``orderRiskAssessment`` GraphQL object (and the
related ``shopifyProtect`` eligibility query) so the brain can
ask for ``Capability.SHOPIFY_ASSESS_RISK`` instead of poking
the deprecated REST ``order.risks`` endpoint.

REST history (why this adapter exists):
  * Pre-2024-04: ``GET /admin/api/.../orders/{id}/risks.json``
  * 2024-04+ : Object renamed to ``orderRiskAssessment`` and
                moved to GraphQL only. REST endpoint kept for
                a deprecation window then removed.
  * 2024-10+ : ``ShopifyProtectOrderEligibility`` added —
                tells you whether the order is eligible for
                Shopify's chargeback guarantee program.

The adapter exposes ONE capability today
(``SHOPIFY_ASSESS_RISK``) which returns a normalised dict:

    {
        "order_id": "gid://shopify/Order/12345",
        "risk_level": "HIGH" | "MEDIUM" | "LOW",
        "score": 0.0–1.0,
        "recommendation": "cancel" | "investigate" | "accept",
        "facts": [{"description": ..., "sentiment": ...}, ...],
        "protect_eligible": True | False,
    }

Callers (notably ``engines/order_management/fraud_screener.py``)
should use these fields instead of inventing their own
heuristics.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


_RISK_QUERY = """
query OrderRisk($id: ID!) {
  order(id: $id) {
    id
    name
    risk {
      assessments {
        riskLevel
        provider {
          features
          handle
        }
        facts {
          description
          sentiment
        }
      }
      recommendation
    }
    shopifyProtect {
      eligibility {
        status
      }
      status
    }
  }
}
""".strip()


# Map Shopify's enum risk levels to a normalised float score
# in the [0, 1] range. The exact numbers don't have to match
# any vendor — they just have to be monotonic and sensible
# so the brain can compare orders apples-to-apples.
_RISK_SCORE_MAP = {
    "LOW": 0.15,
    "MEDIUM": 0.55,
    "HIGH": 0.90,
    "PENDING": 0.50,    # Shopify hasn't finished scoring yet
    "NONE": 0.05,
    "": 0.50,
}

_RECOMMENDATION_MAP = {
    "ACCEPT": "accept",
    "INVESTIGATE": "investigate",
    "CANCEL": "cancel",
}


class ShopifyRiskAdapter(ShopifyBaseAdapter):
    name = "shopify_risk"
    capabilities = {Capability.SHOPIFY_ASSESS_RISK}
    required_scopes = frozenset({"read_orders"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability != Capability.SHOPIFY_ASSESS_RISK:
            raise AdapterValidationError(
                self.name,
                f"unsupported capability: {capability.value}",
            )

        order_id = params.get("order_id") or params.get("id")
        if not order_id:
            raise AdapterValidationError(
                self.name, "'order_id' is required",
            )

        # Accept either a numeric Shopify ID or the GraphQL GID.
        # Pre-cleanup callers passed both shapes; normalise here
        # so the engine layer above doesn't have to think about it.
        gid = self._to_gid(order_id)

        data = self._gql(_RISK_QUERY, {"id": gid})
        order = data.get("order")
        if not order:
            return self._success(
                capability,
                data={
                    "order_id": gid,
                    "found": False,
                    "risk_level": "UNKNOWN",
                    "score": 0.5,
                    "recommendation": "investigate",
                    "facts": [],
                    "protect_eligible": False,
                },
            )

        normalised = self._normalise_risk(order)
        return self._success(capability, data=normalised)

    # ── Helpers ────────────────────────────────────────────────

    @staticmethod
    def _to_gid(order_id: Any) -> str:
        """Accept ``"12345"`` / ``12345`` / ``"gid://shopify/Order/12345"``
        and return the canonical GID."""
        s = str(order_id)
        if s.startswith("gid://"):
            return s
        return f"gid://shopify/Order/{s}"

    @staticmethod
    def _normalise_risk(order: dict[str, Any]) -> dict[str, Any]:
        """Pull the highest-severity risk level from the
        ``assessments`` array, map to a [0,1] score, and flatten
        the ``facts`` so callers can iterate without nested
        knowledge of the GraphQL schema."""
        risk = order.get("risk") or {}
        assessments = risk.get("assessments") or []

        # Highest risk wins (an order with one HIGH and three LOW
        # assessments is HIGH overall — this matches the Shopify
        # admin behaviour).
        risk_level = ""
        score = 0.0
        facts: list[dict[str, Any]] = []
        for a in assessments:
            if not isinstance(a, dict):
                continue
            level = str(a.get("riskLevel", "") or "")
            level_score = _RISK_SCORE_MAP.get(level.upper(), 0.5)
            if level_score > score:
                score = level_score
                risk_level = level.upper()
            for fact in a.get("facts") or []:
                if isinstance(fact, dict):
                    facts.append({
                        "description": fact.get("description", ""),
                        "sentiment": fact.get("sentiment", ""),
                        "provider": (a.get("provider") or {}).get("handle", ""),
                    })

        if not risk_level:
            risk_level = "UNKNOWN"

        recommendation = _RECOMMENDATION_MAP.get(
            str(risk.get("recommendation", "") or "").upper(),
            "investigate" if score > 0.5 else "accept",
        )

        protect = order.get("shopifyProtect") or {}
        protect_eligible = (
            str(protect.get("status", "") or "").upper() == "ACTIVE"
            or str(
                (protect.get("eligibility") or {}).get("status", "") or "",
            ).upper() == "ELIGIBLE"
        )

        return {
            "order_id": order.get("id", ""),
            "order_name": order.get("name", ""),
            "found": True,
            "risk_level": risk_level,
            "score": round(score, 3),
            "recommendation": recommendation,
            "facts": facts,
            "protect_eligible": protect_eligible,
            "raw_assessments": assessments,
        }
