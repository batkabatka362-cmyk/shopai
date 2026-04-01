"""Customer Journey — full lifecycle orchestration intelligence.

What veterans know:
  - 7+ stages: Awareness -> Interest -> Consideration -> Purchase -> Delivery -> Use -> Advocacy
  - Traffic-source specific landing pages increase conversion 20-30%
  - Post-purchase experience determines LTV more than acquisition
  - Surprise & delight automation increases retention 30%+
  - Winback sequences: soft (30d) -> value (60d) -> last chance (90d)
  - Purchase pattern recognition enables predictive marketing
"""
from __future__ import annotations

from typing import Any

from .lifecycle import segment_by_lifecycle
from .funnel import map_customer_journeys
from .winback import identify_winback_candidates
from .surprise_delight import plan_surprise_delight
from .landing_pages import recommend_landing_pages
from .post_purchase import get_post_purchase_plan


class CustomerJourney:
    """Full customer lifecycle orchestration engine."""

    def full_analysis(
        self,
        customers: list[dict[str, Any]],
        orders: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run full customer journey analysis."""
        return {
            "lifecycle_segments": segment_by_lifecycle(customers, orders),
            "journey_map": map_customer_journeys(customers, orders),
            "winback_candidates": identify_winback_candidates(customers, orders),
            "surprise_delight_plan": plan_surprise_delight(customers, orders),
            "landing_page_strategy": recommend_landing_pages(),
            "post_purchase_plan": get_post_purchase_plan(),
        }

    # Delegate methods to standalone functions for backward compatibility
    def segment_by_lifecycle(self, customers, orders=None):
        return segment_by_lifecycle(customers, orders)

    def map_customer_journeys(self, customers, orders=None):
        return map_customer_journeys(customers, orders)

    def identify_winback_candidates(self, customers, orders=None):
        return identify_winback_candidates(customers, orders)

    def plan_surprise_delight(self, customers, orders=None):
        return plan_surprise_delight(customers, orders)

    def recommend_landing_pages(self):
        return recommend_landing_pages()

    def get_post_purchase_plan(self):
        return get_post_purchase_plan()
