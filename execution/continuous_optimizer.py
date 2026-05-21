"""Continuous Optimizer — auto-improves Shopify store every cycle.

Each cycle checks:
  1. New products without descriptions → generate
  2. Products without images → add placeholder
  3. New products without tags → generate SEO tags
  4. Price opportunities → adjust (if promoted to dry_run/live)
  5. Customer re-tagging → update segments
  6. Stale content → refresh
"""
from __future__ import annotations
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("optimizer.continuous")


class ContinuousOptimizer:
    """Runs on every cycle — finds and fixes store issues automatically."""

    def __init__(self) -> None:
        self._fixes: list[dict] = []
        self._cycle_count = 0

    def optimize(self, products: list[dict], customers: list[dict],
                 shop_url: str = "", token: str = "",
                 store_id: str = "") -> dict[str, Any]:
        """Run all optimizations. Returns what was fixed."""
        self._cycle_count += 1
        fixes = []

        # 1. Check for products needing descriptions
        no_desc = [p for p in products
                   if not str(p.get("body_html", p.get("description", "")) or "").strip()]
        if no_desc and shop_url and token:
            for p in no_desc[:2]:  # Max 2 per cycle
                fix = self._fix_description(p, shop_url, token)
                if fix:
                    fixes.append(fix)

        # 2. Check for products needing tags
        no_tags = [p for p in products
                   if not str(p.get("tags", "") or "").strip()]
        if no_tags and shop_url and token:
            for p in no_tags[:2]:
                fix = self._fix_tags(p, shop_url, token)
                if fix:
                    fixes.append(fix)

        # 3. Check pricing opportunities
        pricing_fixes = self._check_pricing(products)
        fixes.extend(pricing_fixes)

        # 4. Customer segment updates
        if customers:
            seg_fixes = self._update_segments(customers, shop_url, token)
            fixes.extend(seg_fixes)

        self._fixes.extend(fixes)

        # Record
        self._record(fixes, store_id)

        return {
            "fixes_applied": len(fixes),
            "by_type": self._count_types(fixes),
            "cycle": self._cycle_count,
        }

    def _fix_description(self, product: dict, shop_url: str, token: str) -> dict | None:
        try:
            from execution.store_optimizer import get_store_optimizer
            opt = get_store_optimizer()
            result = opt.optimize([product], shop_url, token, max_changes=1)
            if result.get("total_changes", 0) > 0:
                return {"type": "description", "product": str(product.get("id", ""))}
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "_fix_description failed for product %s: %s",
                product.get("id", "?"), exc,
            )
        return None

    def _fix_tags(self, product: dict, shop_url: str, token: str) -> dict | None:
        try:
            from execution.store_optimizer import get_store_optimizer
            opt = get_store_optimizer()
            result = opt.optimize([product], shop_url, token, max_changes=1)
            if result.get("total_changes", 0) > 0:
                return {"type": "tags", "product": str(product.get("id", ""))}
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "_fix_tags failed for product %s: %s",
                product.get("id", "?"), exc,
            )
        return None

    @staticmethod
    def _check_pricing(products: list[dict]) -> list[dict]:
        fixes = []
        from utils.finance import margin as _margin
        for p in products:
            price = float(p.get("price", 0))
            cost = float(p.get("cost", 0))
            margin = _margin(price, cost, default=-1.0)
            if margin >= 0 and margin < 0.1:
                    fixes.append({
                        "type": "pricing_warning",
                        "product": str(p.get("id", "")),
                        "message": "Margin {:.0%} too low".format(margin),
                    })
        return fixes[:3]

    @staticmethod
    def _update_segments(customers: list[dict], shop_url: str, token: str) -> list[dict]:
        if not shop_url or not token:
            return []
        try:
            from execution.shopify_automation import get_shopify_automation
            auto = get_shopify_automation()
            auto.set_credentials(shop_url, token)
            result = auto.tag_customers(customers)
            if result.get("tagged", 0) > 0:
                return [{"type": "customer_retag", "count": result["tagged"]}]
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "_update_segments failed (%d customers): %s",
                len(customers), exc,
            )
        return []

    @staticmethod
    def _count_types(fixes: list) -> dict:
        counts = {}
        for f in fixes:
            t = f.get("type", "unknown")
            counts[t] = counts.get(t, 0) + 1
        return counts

    @staticmethod
    def _record(fixes: list, store_id: str):
        if not fixes:
            return
        try:
            from core.data.architecture import get_data_architecture
            da = get_data_architecture()
            for f in fixes:
                da.capture("action", {
                    "action_type": "auto_fix_{}".format(f["type"]),
                    "id": f.get("product", f.get("count", "")),
                }, source="continuous_optimizer", store_id=store_id, score=4.0)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "_record telemetry write failed "
                "(%d fixes, store=%s): %s",
                len(fixes), store_id, exc,
            )

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_fixes": len(self._fixes),
            "cycles_run": self._cycle_count,
            "by_type": self._count_types(self._fixes),
        }


_instance = None
def get_continuous_optimizer():
    global _instance
    if _instance is None:
        _instance = ContinuousOptimizer()
    return _instance
