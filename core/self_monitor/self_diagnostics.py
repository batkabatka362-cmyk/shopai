"""SelfDiagnostics — finds problems and fixes them automatically.

"Conversion буурсан" → checkout page шалгана → slow load илэрвэл → image optimize.
"Email ажиллахгүй" → notification template шалгана → template reset.

Known issue → runbook → auto-fix.
"""
from __future__ import annotations

from typing import Any

from utils.helpers import safe_float
from utils.logger import get_logger

logger = get_logger("self_monitor.diagnostics")

# Known issues with diagnostic steps and fixes
RUNBOOK = {
    "conversion_drop": {
        "symptoms": ["conversion_rate < 1%", "checkout_abandonment > 70%"],
        "diagnostic_steps": [
            {"check": "page_load_time", "threshold": 3.0, "unit": "seconds",
             "fix": "Optimize images, enable lazy loading, minimize scripts"},
            {"check": "checkout_steps", "threshold": 4, "unit": "steps",
             "fix": "Reduce checkout to 1-2 steps, enable express checkout"},
            {"check": "payment_methods", "threshold": 2, "unit": "count",
             "fix": "Add Apple Pay, Google Pay, Shop Pay for 1-click checkout"},
            {"check": "mobile_responsive", "threshold": True, "unit": "bool",
             "fix": "Fix mobile layout — 60%+ of traffic is mobile"},
            {"check": "trust_badges", "threshold": True, "unit": "bool",
             "fix": "Add SSL badge, money-back guarantee, secure payment icons"},
        ],
        "priority": "critical",
    },
    "high_cart_abandonment": {
        "symptoms": ["cart_abandonment > 70%"],
        "diagnostic_steps": [
            {"check": "shipping_cost_visible", "threshold": True, "unit": "bool",
             "fix": "Show shipping cost BEFORE checkout — surprise costs = #1 abandonment reason"},
            {"check": "guest_checkout", "threshold": True, "unit": "bool",
             "fix": "Enable guest checkout — forced registration loses 35% of buyers"},
            {"check": "exit_intent_popup", "threshold": True, "unit": "bool",
             "fix": "Add exit-intent popup with discount for abandoners"},
            {"check": "cart_recovery_email", "threshold": True, "unit": "bool",
             "fix": "Set up 3-email cart recovery sequence (1h, 24h, 72h)"},
        ],
        "priority": "high",
    },
    "email_not_working": {
        "symptoms": ["email_open_rate < 10%", "email_deliverability < 90%"],
        "diagnostic_steps": [
            {"check": "spf_record", "threshold": True, "unit": "bool",
             "fix": "Add SPF record to DNS for email domain"},
            {"check": "dkim_record", "threshold": True, "unit": "bool",
             "fix": "Set up DKIM signing for email authentication"},
            {"check": "dmarc_policy", "threshold": True, "unit": "bool",
             "fix": "Add DMARC policy to prevent spoofing"},
            {"check": "list_hygiene", "threshold": 5, "unit": "bounce_pct",
             "fix": "Clean email list — remove bounced/unengaged subscribers"},
            {"check": "subject_line_spam", "threshold": False, "unit": "bool",
             "fix": "Remove spam trigger words (FREE, URGENT, !!!) from subjects"},
        ],
        "priority": "high",
    },
    "slow_site": {
        "symptoms": ["page_load > 3s", "bounce_rate > 50%"],
        "diagnostic_steps": [
            {"check": "image_optimization", "threshold": True, "unit": "bool",
             "fix": "Compress images to WebP, use responsive sizes"},
            {"check": "app_count", "threshold": 15, "unit": "count",
             "fix": "Remove unused apps — each app adds JavaScript that slows site"},
            {"check": "theme_code", "threshold": True, "unit": "bool",
             "fix": "Audit theme for unused code, excessive Liquid loops"},
            {"check": "cdn_enabled", "threshold": True, "unit": "bool",
             "fix": "Ensure Shopify CDN is serving all static assets"},
        ],
        "priority": "medium",
    },
    "revenue_declining": {
        "symptoms": ["revenue_trend negative for 7+ days"],
        "diagnostic_steps": [
            {"check": "traffic_source", "threshold": "check", "unit": "analysis",
             "fix": "Identify which traffic source declined — fix that channel"},
            {"check": "conversion_rate_change", "threshold": "check", "unit": "analysis",
             "fix": "If conversion dropped, check product pages and checkout"},
            {"check": "aov_change", "threshold": "check", "unit": "analysis",
             "fix": "If AOV dropped, review pricing and upsell strategy"},
            {"check": "competitor_activity", "threshold": "check", "unit": "analysis",
             "fix": "Check if competitors launched promotions or new products"},
        ],
        "priority": "critical",
    },
    "high_return_rate": {
        "symptoms": ["return_rate > 10%"],
        "diagnostic_steps": [
            {"check": "product_descriptions", "threshold": True, "unit": "bool",
             "fix": "Improve descriptions — 25% of returns are 'not as described'"},
            {"check": "size_charts", "threshold": True, "unit": "bool",
             "fix": "Add detailed size charts — 20% of returns are wrong size"},
            {"check": "product_photos", "threshold": 5, "unit": "min_count",
             "fix": "Add 5+ photos per product including scale/context shots"},
            {"check": "packaging_quality", "threshold": True, "unit": "bool",
             "fix": "Improve packaging — 15% of returns are shipping damage"},
        ],
        "priority": "high",
    },
    "inventory_mismatch": {
        "symptoms": ["overselling", "negative_inventory"],
        "diagnostic_steps": [
            {"check": "inventory_tracking", "threshold": True, "unit": "bool",
             "fix": "Enable Shopify inventory tracking on all products"},
            {"check": "multi_location_sync", "threshold": True, "unit": "bool",
             "fix": "Sync inventory across all locations and sales channels"},
            {"check": "reserve_buffer", "threshold": 2, "unit": "units",
             "fix": "Set safety buffer of 2 units to prevent overselling"},
        ],
        "priority": "high",
    },
}

# Shopify-specific settings to check
SHOPIFY_HEALTH_CHECKS = {
    "checkout": {
        "express_payment": {"description": "Apple Pay, Google Pay, Shop Pay enabled", "impact": "+15% mobile conversion"},
        "tip_enabled": {"description": "Tipping option available", "impact": "+2-5% revenue for service businesses"},
        "abandoned_checkout_recovery": {"description": "Auto-email for abandoned checkouts", "impact": "+5-15% recovery rate"},
    },
    "shipping": {
        "free_shipping_threshold": {"description": "Free shipping above AOV×1.3", "impact": "+30% AOV"},
        "calculated_shipping": {"description": "Real-time carrier rates", "impact": "Accurate costs, less abandonment"},
        "local_delivery": {"description": "Local delivery option", "impact": "+10-20% local orders"},
    },
    "seo": {
        "meta_descriptions": {"description": "All products have meta descriptions", "impact": "+10-20% organic traffic"},
        "alt_tags": {"description": "All images have alt tags", "impact": "Accessibility + SEO"},
        "url_structure": {"description": "Clean URL slugs", "impact": "Better crawling"},
    },
    "notifications": {
        "order_confirmation": {"description": "Custom order confirmation template", "impact": "Brand consistency"},
        "shipping_confirmation": {"description": "Shipping notification with tracking", "impact": "-20% 'where is my order' queries"},
        "review_request": {"description": "Post-delivery review request", "impact": "+300% review collection"},
    },
}


class SelfDiagnostics:
    """Diagnoses store problems and suggests/applies fixes.

    Usage:
        diag = SelfDiagnostics()
        result = diag.diagnose("conversion_drop", store_data)
        health = diag.shopify_health_check(store_config)
        full = diag.full_scan(store_data, store_config)
    """

    def diagnose(self, issue: str, store_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Diagnose a specific issue using the runbook."""
        if issue not in RUNBOOK:
            return {
                "issue": issue,
                "known": False,
                "suggestion": "Issue not in runbook — check system health report for clues",
                "available_issues": list(RUNBOOK.keys()),
            }

        runbook = RUNBOOK[issue]
        results = []
        fixes_needed = 0

        for step in runbook["diagnostic_steps"]:
            check_name = step["check"]
            # In production, these would query actual Shopify data
            # For now, return the diagnostic as a checklist
            results.append({
                "check": check_name,
                "expected": step["threshold"],
                "fix_if_failed": step["fix"],
                "status": "needs_check",
            })
            fixes_needed += 1

        return {
            "issue": issue,
            "known": True,
            "priority": runbook["priority"],
            "symptoms": runbook["symptoms"],
            "diagnostic_steps": results,
            "total_checks": len(results),
            "fixes_needed": fixes_needed,
        }

    def shopify_health_check(self, store_config: dict[str, Any] | None = None) -> dict[str, Any]:
        """Check Shopify store configuration for optimization opportunities."""
        if not isinstance(store_config, dict):
            store_config = None

        sections = {}
        total_checks = 0
        total_issues = 0

        for section, checks in SHOPIFY_HEALTH_CHECKS.items():
            section_results = []
            for check_name, info in checks.items():
                enabled = False
                if store_config:
                    # Pre-audit ``store_config.get(section, {}).get(...)``
                    # crashed when ``section`` was present-but-None.
                    # Audit pass 51.
                    section_cfg = store_config.get(section) or {}
                    if isinstance(section_cfg, dict):
                        enabled = bool(section_cfg.get(check_name, False))

                section_results.append({
                    "check": check_name,
                    "description": info["description"],
                    "impact": info["impact"],
                    "enabled": enabled,
                    "action": "OK" if enabled else f"ENABLE: {info['description']}",
                })
                total_checks += 1
                if not enabled:
                    total_issues += 1

            sections[section] = section_results

        score = round((total_checks - total_issues) / max(total_checks, 1) * 100)
        grade = "A" if score >= 80 else "B" if score >= 60 else "C" if score >= 40 else "D" if score >= 20 else "F"

        return {
            "sections": sections,
            "total_checks": total_checks,
            "issues_found": total_issues,
            "score": score,
            "grade": grade,
            "top_fix": next(
                (r["action"] for s in sections.values() for r in s if not r["enabled"]),
                "All checks passing",
            ),
        }

    def full_scan(
        self,
        store_data: dict[str, Any] | None = None,
        store_config: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run full diagnostic scan and return prioritized fix list."""
        issues_found = []

        # Auto-detect issues from metrics. Pre-audit
        # ``metrics.get("conversion_rate", 100) < 1`` crashed
        # on present-but-None / non-numeric values. safe_float
        # handles both. Audit pass 51.
        if isinstance(metrics, dict):
            if safe_float(metrics.get("conversion_rate"), default=100) < 1:
                issues_found.append(self.diagnose("conversion_drop", store_data))
            if safe_float(metrics.get("cart_abandonment")) > 70:
                issues_found.append(self.diagnose("high_cart_abandonment", store_data))
            if safe_float(metrics.get("email_open_rate"), default=100) < 10:
                issues_found.append(self.diagnose("email_not_working", store_data))
            if safe_float(metrics.get("return_rate")) > 10:
                issues_found.append(self.diagnose("high_return_rate", store_data))
            if safe_float(metrics.get("page_load")) > 3:
                issues_found.append(self.diagnose("slow_site", store_data))

        # Shopify config check
        shopify_health = self.shopify_health_check(store_config)

        # Prioritize. Skip non-dict entries defensively.
        issues_found = [i for i in issues_found if isinstance(i, dict)]
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        issues_found.sort(key=lambda i: priority_order.get(i.get("priority", "low"), 3))

        return {
            "issues_detected": len(issues_found),
            "issues": issues_found,
            "shopify_health": shopify_health,
            "recommendation": (
                f"Fix {len(issues_found)} detected issues. "
                f"Shopify config score: {shopify_health['score']}/100 ({shopify_health['grade']})."
                if issues_found
                else f"No issues detected. Shopify config score: {shopify_health['score']}/100."
            ),
        }
