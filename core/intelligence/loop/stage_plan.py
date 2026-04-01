"""Stage 4: PLAN — create specific executable actions."""
from __future__ import annotations

from typing import Any


def stage_plan(decision: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    actions = []
    confidence = decision.get("confidence", "medium")
    decision_type = decision.get("decision_type", "")

    products = data.get("products", data.get("product_data", []))
    customers = data.get("customer_data", data.get("customers", []))

    if isinstance(products, list) and products:
        actions.append({"type": "pricing_analysis", "priority": 1, "description": "Run pricing intelligence", "target": "pricing_engine", "data_needed": "products"})
        actions.append({"type": "seo_audit", "priority": 2, "description": "Audit product pages for SEO", "target": "seo_engine", "data_needed": "products"})
        actions.append({"type": "content_check", "priority": 2, "description": "Improve product descriptions", "target": "content_engine", "data_needed": "products"})

    if isinstance(customers, list) and customers:
        actions.append({"type": "segment_customers", "priority": 1, "description": "Segment by RFM and detect churn", "target": "customer_engine", "data_needed": "customers"})

    # Decision-type-specific actions
    if decision_type == "product_launch":
        actions.append({"type": "product_launch", "priority": 1, "description": "Execute product launch workflow", "target": "workflow_engine", "data_needed": "products"})
    elif decision_type == "customer_retention":
        actions.append({"type": "win_back_email", "priority": 1, "description": "Create win-back email campaign", "target": "email_engine", "data_needed": "customers"})
    elif decision_type == "aov_increase":
        actions.append({"type": "bundle_strategy", "priority": 1, "description": "Create bundle/upsell offers", "target": "pricing_engine", "data_needed": "products"})

    # Deprioritize if low confidence
    if confidence == "low":
        for a in actions:
            a["priority"] = max(a["priority"], 2)
        actions.append({"type": "gather_more_data", "priority": 1, "description": "Low confidence — collect more data", "target": "data_engine", "data_needed": "all"})

    actions.sort(key=lambda a: a["priority"])
    return {"actions": actions, "total": len(actions)}
