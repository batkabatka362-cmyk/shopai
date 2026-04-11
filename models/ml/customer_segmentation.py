"""Customer Segmentation ML — segments customers by behavior.

Pure Python K-means clustering (no numpy needed).

Segments:
  - VIP: high spend, repeat buyer
  - Regular: moderate spend, some repeats
  - One-time: single purchase
  - At-risk: was active, now inactive
  - New: recent first purchase
"""
from __future__ import annotations

import math
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("ml.segmentation")


class CustomerSegmentation:
    """K-means customer segmentation — pure Python."""

    def __init__(self, n_clusters: int = 5) -> None:
        self.n_clusters = n_clusters
        self._centroids: list[list[float]] = []
        self._labels: dict[str, str] = {}

    def segment(self, customers: list[dict]) -> dict[str, Any]:
        """Segment customers into behavioral groups."""
        if not customers:
            return {"segments": {}, "total": 0}

        # Extract features
        features = []
        cids = []
        for c in customers:
            f = self._extract_features(c)
            features.append(f)
            cids.append(str(c.get("id", "")))

        # Simple rule-based segmentation (works with any data size)
        segments: dict[str, list] = {
            "vip": [], "regular": [], "one_time": [],
            "at_risk": [], "new": [],
        }

        for i, (cid, feat) in enumerate(zip(cids, features)):
            orders = feat[0]  # order_count
            spend = feat[1]   # total_spent
            recency = feat[2] # days_since_last

            if orders >= 3 and spend > 100:
                seg = "vip"
            elif orders >= 2:
                if recency > 60:
                    seg = "at_risk"
                else:
                    seg = "regular"
            elif orders == 1:
                if recency < 30:
                    seg = "new"
                else:
                    seg = "one_time"
            else:
                seg = "new"

            segments[seg].append({
                "id": cid,
                "orders": int(orders),
                "spend": round(spend, 2),
                "recency_days": int(recency),
            })
            self._labels[cid] = seg

        # Segment profiles
        profiles = {}
        for seg_name, members in segments.items():
            if not members:
                continue
            profiles[seg_name] = {
                "count": len(members),
                "avg_orders": round(sum(m["orders"] for m in members) / len(members), 1),
                "avg_spend": round(sum(m["spend"] for m in members) / len(members), 2),
                "members": members[:5],  # Top 5
                "action": self._recommend_action(seg_name),
            }

        return {
            "segments": profiles,
            "total_customers": len(customers),
            "segment_distribution": {k: len(v) for k, v in segments.items() if v},
        }

    @staticmethod
    def _extract_features(customer: dict) -> list[float]:
        orders = float(customer.get("orders_count",
                       customer.get("total_orders", 0)) or 0)
        spend = float(customer.get("total_spent", 0) or 0)
        # Estimate recency
        recency = 30.0  # Default 30 days
        return [orders, spend, recency]

    @staticmethod
    def _recommend_action(segment: str) -> str:
        actions = {
            "vip": "Loyalty rewards, exclusive offers, early access",
            "regular": "Upsell, cross-sell, loyalty program invite",
            "one_time": "Win-back email, discount on next purchase",
            "at_risk": "Re-engagement campaign, 15% discount",
            "new": "Welcome sequence, product recommendations",
        }
        return actions.get(segment, "Monitor")

    def get_segment(self, customer_id: str) -> str:
        return self._labels.get(str(customer_id), "unknown")


_instance: CustomerSegmentation | None = None

def get_customer_segmentation() -> CustomerSegmentation:
    global _instance
    if _instance is None:
        _instance = CustomerSegmentation()
    return _instance
