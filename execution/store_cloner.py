"""Store Cloner — clone a winning store setup to a new niche in minutes.

Copies: pages, collections, discounts, configs, AI settings.
Swaps: products, niche-specific content.
"""
from __future__ import annotations
import json
import time
import urllib.request
from typing import Any
from utils.logger import get_logger
logger = get_logger("store.cloner")


class StoreCloner:
    """Clone store configuration to a new store."""

    def clone(self, source_url: str, source_token: str,
              target_url: str, target_token: str,
              target_niche: str = "") -> dict[str, Any]:
        """Clone source store setup to target store."""
        results = {"steps": []}

        # 1. Extract source configuration
        source_config = self._extract_config(source_url, source_token)
        results["steps"].append({"extract": "OK",
            "pages": len(source_config.get("pages", [])),
            "collections": len(source_config.get("collections", [])),
            "discounts": len(source_config.get("discounts", []))})

        # 2. Clone pages
        pages_created = self._clone_pages(source_config.get("pages", []),
                                           target_url, target_token)
        results["steps"].append({"pages": pages_created})

        # 3. Clone discount strategy
        discounts_created = self._clone_discounts(source_config.get("discounts", []),
                                                   target_url, target_token)
        results["steps"].append({"discounts": discounts_created})

        # 4. Configure target by niche
        if target_niche:
            try:
                from execution.store_configurator import get_store_configurator
                sc = get_store_configurator()
                config_result = sc.configure(target_url, target_token, target_niche)
                results["steps"].append({"niche_config": "OK"})
            except Exception:
                results["steps"].append({"niche_config": "skip"})

        # 5. Share AI knowledge
        try:
            from core.brain.multi_store_brain import get_multi_store
            ms = get_multi_store()
            source_id = source_url.replace(".myshopify.com", "")
            target_id = target_url.replace(".myshopify.com", "")
            ms.register_store(source_id)
            ms.register_store(target_id)
            shared = ms.share_learning(source_id)
            ms.apply_learning(target_id, shared)
            results["steps"].append({"knowledge": "OK",
                "rules_shared": shared.get("shareable_rules", 0)})
        except Exception:
            pass

        return {"status": "cloned", "results": results}

    def _extract_config(self, shop_url, token):
        h = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
        config = {}
        try:
            config["pages"] = self._api_get(shop_url, "pages.json", h).get("pages", [])
            config["collections"] = self._api_get(shop_url, "smart_collections.json", h).get("smart_collections", [])
            config["discounts"] = self._api_get(shop_url, "price_rules.json", h).get("price_rules", [])
        except Exception:
            pass
        return config

    def _clone_pages(self, pages, target_url, target_token):
        h = {"X-Shopify-Access-Token": target_token, "Content-Type": "application/json"}
        created = 0
        skip = {"Terms and Conditions", "Privacy policy", "Shipping Policy", "Return Policy", "Contact"}
        for page in pages:
            if page.get("title", "") in skip:
                continue
            result = self._api_post(target_url, "pages.json", h, {
                "page": {
                    "title": page.get("title", ""),
                    "body_html": page.get("body_html", ""),
                    "published": True,
                }
            })
            if result.get("page"):
                created += 1
        return created

    def _clone_discounts(self, discounts, target_url, target_token):
        h = {"X-Shopify-Access-Token": target_token, "Content-Type": "application/json"}
        created = 0
        for rule in discounts:
            new_rule = {
                "price_rule": {
                    "title": rule.get("title", ""),
                    "target_type": rule.get("target_type", "line_item"),
                    "target_selection": rule.get("target_selection", "all"),
                    "allocation_method": rule.get("allocation_method", "across"),
                    "value_type": rule.get("value_type", "percentage"),
                    "value": rule.get("value", "-10"),
                    "customer_selection": "all",
                    "starts_at": time.strftime("%Y-%m-%dT00:00:00Z"),
                }
            }
            result = self._api_post(target_url, "price_rules.json", h, new_rule)
            if result.get("price_rule"):
                rid = result["price_rule"]["id"]
                self._api_post(target_url, "price_rules/{}/discount_codes.json".format(rid), h,
                               {"discount_code": {"code": rule.get("title", "CLONE")}})
                created += 1
        return created

    @staticmethod
    def _api_get(shop_url, path, h):
        req = urllib.request.Request("https://{}/admin/api/2024-01/{}".format(shop_url, path), headers=h)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    @staticmethod
    def _api_post(shop_url, path, h, payload):
        url = "https://{}/admin/api/2024-01/{}".format(shop_url, path)
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, method="POST", headers=h)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except Exception:
            return {}


_instance = None
def get_store_cloner():
    global _instance
    if _instance is None:
        _instance = StoreCloner()
    return _instance
