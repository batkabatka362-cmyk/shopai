"""W963-144: order tracking adapter category.

Aggregators like AfterShip unify carrier tracking
across 1000+ carriers worldwide. ShopAI consumes
tracking events to:

  - Auto-answer 'where is my order?' tickets
  - Drive customer notifications (delivery on the way,
    delivered)
  - Feed the delivery_feedback engine for satisfaction
    measurement
  - Trigger replacement workflows on stuck shipments

Per-store routing via W963-116 helper (active_store ->
SHOPAI_STORE_<SID>_AFTERSHIP_API_KEY chain).
"""
from ._base import TrackingBaseAdapter

__all__ = ["TrackingBaseAdapter"]
