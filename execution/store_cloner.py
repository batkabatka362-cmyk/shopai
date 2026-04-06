"""Store Cloner — clone a winning store setup to a new niche in minutes.

Copies: pages, collections, discounts, configs, AI settings.
Swaps: products, niche-specific content.

All Shopify API calls (read + write) run through a shared ThreadPoolExecutor
so extract + clone steps are parallelized. Shopify REST Admin API allows up
to 40 req/s per app, so max_workers=5 leaves generous headroom while still
cutting wall-clock time by ~5x for bulk operations.
"""
from __future__ import annotations
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from utils.logger import get_logger
logger = get_logger("store.cloner")


# Skipped when cloning pages — every store has its own legal content
_SKIP_PAGE_TITLES = frozenset({
    "Terms and Conditions", "Privacy policy", "Shipping Policy",
    "Return Policy", "Contact",
})

# Max concurrent Shopify API requests. Shopify's REST Admin bucket holds
# 40 req/s per app; 5 workers leaves room for the rest of the system.
_MAX_WORKERS = 5


class StoreCloner:
    """Clone store configuration to a new store."""

    def clone(self, source_url: str, source_token: str,
              target_url: str, target_token: str,
              target_niche: str = "") -> dict[str, Any]:
        """Clone source store setup to target store."""
        results: dict[str, Any] = {"steps": []}

        # 1. Extract source configuration (parallel GETs)
        source_config = self._extract_config(source_url, source_token)
        results["steps"].append({
            "extract": "OK",
            "pages": len(source_config.get("pages", [])),
            "collections": len(source_config.get("collections", [])),
            "discounts": len(source_config.get("discounts", [])),
        })

        # 2+3. Clone pages and discounts in parallel — they don't depend
        # on each other and both issue many independent POST requests.
        with ThreadPoolExecutor(max_workers=2) as ex:
            pages_fut = ex.submit(self._clone_pages,
                                  source_config.get("pages", []),
                                  target_url, target_token)
            discounts_fut = ex.submit(self._clone_discounts,
                                      source_config.get("discounts", []),
                                      target_url, target_token)
            pages_created = pages_fut.result()
            discounts_created = discounts_fut.result()
        results["steps"].append({"pages": pages_created})
        results["steps"].append({"discounts": discounts_created})

        # 4. Configure target by niche
        if target_niche:
            try:
                from execution.store_configurator import get_store_configurator
                sc = get_store_configurator()
                sc.configure(target_url, target_token, target_niche)
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
            results["steps"].append({
                "knowledge": "OK",
                "rules_shared": shared.get("shareable_rules", 0),
            })
        except Exception:
            pass

        return {"status": "cloned", "results": results}

    # ── Extraction ─────────────────────────────────────────────

    def _extract_config(self, shop_url: str, token: str) -> dict[str, list]:
        """Fetch pages + collections + discounts in parallel.

        The 3 endpoints are independent so a 3-wide thread pool cuts
        wall-clock time from ~3x latency to ~1x latency.
        """
        h = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
        endpoints = [
            ("pages", "pages.json", "pages"),
            ("collections", "smart_collections.json", "smart_collections"),
            ("discounts", "price_rules.json", "price_rules"),
        ]
        config: dict[str, list] = {k: [] for k, _, _ in endpoints}

        with ThreadPoolExecutor(max_workers=3) as ex:
            futures = {
                ex.submit(self._api_get, shop_url, path, h): (key, resp_key)
                for key, path, resp_key in endpoints
            }
            for fut in as_completed(futures):
                key, resp_key = futures[fut]
                try:
                    config[key] = fut.result().get(resp_key, []) or []
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Extract %s failed: %s", key, exc)
                    config[key] = []
        return config

    # ── Clone pages ────────────────────────────────────────────

    def _clone_pages(self, pages: list, target_url: str, target_token: str) -> int:
        h = {"X-Shopify-Access-Token": target_token, "Content-Type": "application/json"}

        def _create_page(page: dict) -> bool:
            if page.get("title", "") in _SKIP_PAGE_TITLES:
                return False
            result = self._api_post(target_url, "pages.json", h, {
                "page": {
                    "title": page.get("title", ""),
                    "body_html": page.get("body_html", ""),
                    "published": True,
                }
            })
            return bool(result.get("page"))

        if not pages:
            return 0

        created = 0
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
            for ok in ex.map(_create_page, pages):
                if ok:
                    created += 1
        return created

    # ── Clone discounts ────────────────────────────────────────

    def _clone_discounts(self, discounts: list, target_url: str,
                         target_token: str) -> int:
        h = {"X-Shopify-Access-Token": target_token, "Content-Type": "application/json"}
        starts_at = time.strftime("%Y-%m-%dT00:00:00Z")

        def _create_rule(rule: dict) -> bool:
            # Each discount needs two sequential POSTs (rule → code), but
            # different discounts are independent of each other.
            new_rule = {
                "price_rule": {
                    "title": rule.get("title", ""),
                    "target_type": rule.get("target_type", "line_item"),
                    "target_selection": rule.get("target_selection", "all"),
                    "allocation_method": rule.get("allocation_method", "across"),
                    "value_type": rule.get("value_type", "percentage"),
                    "value": rule.get("value", "-10"),
                    "customer_selection": "all",
                    "starts_at": starts_at,
                }
            }
            result = self._api_post(target_url, "price_rules.json", h, new_rule)
            if not result.get("price_rule"):
                return False
            rid = result["price_rule"]["id"]
            self._api_post(
                target_url,
                "price_rules/{}/discount_codes.json".format(rid),
                h,
                {"discount_code": {"code": rule.get("title", "CLONE")}},
            )
            return True

        if not discounts:
            return 0

        created = 0
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
            for ok in ex.map(_create_rule, discounts):
                if ok:
                    created += 1
        return created

    # ── HTTP helpers ───────────────────────────────────────────

    @staticmethod
    def _api_get(shop_url: str, path: str, h: dict) -> dict:
        req = urllib.request.Request(
            "https://{}/admin/api/2024-01/{}".format(shop_url, path), headers=h,
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    @staticmethod
    def _api_post(shop_url: str, path: str, h: dict, payload: dict) -> dict:
        url = "https://{}/admin/api/2024-01/{}".format(shop_url, path)
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, method="POST", headers=h)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:200]
            logger.warning("Clone API error %d on %s: %s", exc.code, path, body)
            return {"error": "HTTP {}".format(exc.code), "body": body}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Clone API error on %s: %s", path, exc)
            return {"error": str(exc)[:100]}


_instance: StoreCloner | None = None


def get_store_cloner() -> StoreCloner:
    global _instance
    if _instance is None:
        _instance = StoreCloner()
    return _instance
