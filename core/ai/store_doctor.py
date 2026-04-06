"""AI Store Doctor — weekly health diagnosis with auto-fix."""
from __future__ import annotations
import time
from utils.logger import get_logger
logger = get_logger("store.doctor")


class AIStoreDoctor:
    """Diagnoses store problems and prescribes fixes."""

    def diagnose(self, products, orders, customers, cycle_result=None):
        issues = []
        fixes = []
        score = 100

        # Product issues
        no_img = sum(1 for p in products if not (p.get("images") or p.get("image_url")))
        if no_img:
            issues.append("CRITICAL: {} products without images".format(no_img))
            fixes.append("Add images to all products")
            score -= no_img * 3

        no_desc = sum(1 for p in products if not (p.get("body_html","") or "").strip())
        if no_desc:
            issues.append("WARNING: {} products without descriptions".format(no_desc))
            fixes.append("Generate AI descriptions")
            score -= no_desc * 2

        if len(products) < 20:
            issues.append("INFO: Only {} products — expand to 25+".format(len(products)))
            fixes.append("Use AI Product Finder to add trending products")
            score -= 5

        # Order issues
        if not orders:
            issues.append("CRITICAL: No orders — store needs traffic")
            fixes.append("Launch social media + use discount codes")
            score -= 20

        # Customer issues
        if not customers:
            issues.append("WARNING: No customers — need acquisition strategy")
            fixes.append("Run welcome email campaign")
            score -= 10

        # Margin check
        low_margin = sum(1 for p in products
                          if float(p.get("price",0)) > 0 and float(p.get("cost",0)) > 0
                          and (float(p["price"]) - float(p["cost"])) / float(p["price"]) < 0.2)
        if low_margin:
            issues.append("WARNING: {} products with <20% margin".format(low_margin))
            fixes.append("Raise prices or find cheaper suppliers")
            score -= low_margin * 2

        # Cycle-level signals
        if cycle_result:
            phases = cycle_result.get("phases", {}) or {}
            layers_run = phases.get("layers", {}).get("layers_run", 12)
            if layers_run < 12:
                issues.append("WARNING: Only {}/12 layers ran last cycle".format(layers_run))
                fixes.append("Check layer_dispatcher logs")
                score -= (12 - layers_run) * 2
            rule_health = phases.get("rule_health", {}).get("health_score", 100)
            if rule_health < 50:
                issues.append("WARNING: Rule health at {}%".format(rule_health))
                fixes.append("Deprioritize zero-success rules")
                score -= 5

        score = max(0, min(100, score))
        health = "HEALTHY" if score >= 80 else "NEEDS ATTENTION" if score >= 50 else "CRITICAL"

        return {
            "health_score": score,
            "health_status": health,
            "issues": issues,
            "fixes": fixes,
            "products": len(products),
            "orders": len(orders),
            "customers": len(customers),
            "diagnosed_at": time.time(),
        }


_instance = None
def get_store_doctor():
    global _instance
    if _instance is None:
        _instance = AIStoreDoctor()
    return _instance
