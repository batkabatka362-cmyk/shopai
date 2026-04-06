"""Customer Journey AI — track and predict customer behavior."""
from __future__ import annotations
from utils.logger import get_logger
logger = get_logger("customer.journey")


class CustomerJourneyAI:
    """Track customer journey stages and predict next actions."""

    def analyze_customers(self, customers, orders):
        # Build last-order-timestamp index from orders (recency affects churn risk)
        last_order_by_customer: dict = {}
        for o in orders or []:
            cid = str(o.get("customer", {}).get("id", "") if isinstance(o.get("customer"), dict) else o.get("customer_id", ""))
            created = o.get("created_at", o.get("timestamp", 0))
            if cid and created:
                prev = last_order_by_customer.get(cid)
                if not prev or str(created) > str(prev):
                    last_order_by_customer[cid] = created

        journeys = []
        for c in customers:
            cid = str(c.get("id", ""))
            order_count = int(c.get("orders_count", 0))
            spent = float(c.get("total_spent", "0") or 0)
            has_recent_order = cid in last_order_by_customer

            if order_count == 0:
                stage = "visitor"
                next_action = "Send welcome offer"
                churn_risk = 0.8
            elif order_count == 1:
                stage = "first_buyer"
                next_action = "Send post-purchase email + cross-sell"
                churn_risk = 0.6
            elif order_count < 3:
                stage = "returning"
                next_action = "Loyalty program invite"
                churn_risk = 0.3
            else:
                stage = "loyal"
                next_action = "VIP exclusive offer"
                churn_risk = 0.1

            # Boost churn risk if customer has no order in recent batch
            if order_count > 0 and not has_recent_order:
                churn_risk = min(1.0, churn_risk + 0.2)

            journeys.append({
                "customer_id": cid,
                "stage": stage,
                "orders": order_count,
                "spent": spent,
                "next_action": next_action,
                "churn_risk": churn_risk,
                "ltv_estimate": round(spent * (1 + order_count * 0.3), 2),
            })

        stages = {}
        for j in journeys:
            stages[j["stage"]] = stages.get(j["stage"], 0) + 1

        return {"journeys": journeys, "total": len(journeys),
                "by_stage": stages,
                "avg_churn_risk": round(sum(j["churn_risk"] for j in journeys) / max(len(journeys),1), 2)}


_instance = None
def get_customer_journey():
    global _instance
    if _instance is None:
        _instance = CustomerJourneyAI()
    return _instance
