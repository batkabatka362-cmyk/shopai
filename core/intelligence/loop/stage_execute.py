"""Stage 5: EXECUTE — format actions for target systems."""
from __future__ import annotations

from typing import Any


def stage_execute(plan: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Format planned actions for Shopify, email, ads, etc."""
    ready = []
    products = data.get("products", data.get("product_data", []))
    products_valid = isinstance(products, list) and products and isinstance(products[0], dict)

    for action in plan["actions"]:
        target = action["target"]
        formatted = {
            "action_type": action["type"],
            "priority": action["priority"],
            "target": target,
            "description": action["description"],
            "status": "ready",
        }

        try:
            if target == "pricing_engine" and products_valid:
                formatted["payload"] = {"engine": "pricing", "data": {"products": products[:10]}}

            elif target == "email_engine":
                from core.intelligence.email_intelligence import EmailIntelligence
                flow = EmailIntelligence().build_automation_flow("win_back")
                formatted["payload"] = {"flow": flow["name"], "emails": len(flow["emails"])}

            elif target == "seo_engine" and products_valid:
                from core.intelligence.seo_intelligence import SEOIntelligence
                audit = SEOIntelligence().audit_page({"title": products[0].get("name", ""), "keyword": products[0].get("category", "product")})
                formatted["payload"] = {"audit_score": audit["score"], "issues": audit["issue_count"]}

            elif target == "content_engine" and products_valid:
                from core.intelligence.content_generator import ContentGenerator
                desc = ContentGenerator().product_description(products[0])
                formatted["payload"] = {"headline": desc["headline"][:60], "bullets": len(desc["bullet_points"])}

        except Exception as exc:
            formatted["payload_error"] = str(exc)

        ready.append(formatted)

    return {"ready": ready, "total": len(ready)}
