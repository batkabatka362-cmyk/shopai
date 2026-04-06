"""Store Configurator — auto-configure all Shopify store settings.

Configures collections, discounts, shipping, content, tags, payments,
gifts/loyalty, and email templates to turn a fresh Shopify store into
an AI-managed storefront with zero manual clicking.

Every write goes through ShopifyClient (retry, rate limit, consistent
error shape) and can be previewed via ``dry_run=True``. Features can
be run selectively via the ``features`` parameter:

    configurator = StoreConfigurator(dry_run=True)
    result = configurator.configure(
        "mystore.myshopify.com", "shpat_x",
        niche="beauty",
        features=["collections", "discounts"],  # only these
    )
    print(result["plan"])  # what would have been written

The historical methods (_setup_collections, _setup_discounts, etc.)
are still called from configure() so the public interface consumed by
store_registry.py stays stable.
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from utils.logger import get_logger
from utils.shopify_client import ShopifyClient

logger = get_logger("store.configurator")


# ── Niche-specific configurations ──────────────────────────────────

NICHE_CONFIGS: dict[str, dict[str, Any]] = {
    "home": {
        "collections": ["Home Decor", "Lighting", "Kitchen", "Bedroom", "Living Room"],
        "discount_strategy": "moderate",
        "shipping_message": "Free shipping on orders over $50",
        "target_audience": "homeowners, renters, gift buyers",
    },
    "fashion": {
        "collections": ["New Arrivals", "Tops", "Bottoms", "Accessories", "Sale"],
        "discount_strategy": "aggressive",
        "shipping_message": "Free shipping on all orders",
        "target_audience": "young adults, fashion-conscious",
    },
    "tech": {
        "collections": ["Gadgets", "Accessories", "Smart Home", "Audio", "Charging"],
        "discount_strategy": "moderate",
        "shipping_message": "Fast tech delivery — 2-5 days",
        "target_audience": "tech enthusiasts, gadget lovers",
    },
    "beauty": {
        "collections": ["Skincare", "Makeup", "Hair Care", "Tools", "Gift Sets"],
        "discount_strategy": "generous",
        "shipping_message": "Free shipping + free samples",
        "target_audience": "beauty enthusiasts",
    },
    "general": {
        "collections": ["Best Sellers", "New In", "Under $25", "Premium", "Gift Ideas"],
        "discount_strategy": "moderate",
        "shipping_message": "Free shipping on orders over $50",
        "target_audience": "general consumers",
    },
}


ALL_FEATURES = (
    "collections",
    "discounts",
    "shipping",
    "content",
    "product_tags",
    "ai_config",
)


class StoreConfigurator:
    """Auto-configure Shopify store based on niche and products."""

    def __init__(self, dry_run: bool = False) -> None:
        self._dry_run = dry_run
        self._plan: list[dict] = []

    # ── Public API ─────────────────────────────────────────────

    def configure(
        self,
        shop_url: str,
        token: str,
        niche: str = "general",
        store_name: str = "",
        *,
        features: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Full store configuration.

        Args:
            shop_url: e.g. ``mystore.myshopify.com``
            token: Shopify Admin API access token
            niche: one of NICHE_CONFIGS keys (default: "general")
            store_name: optional display name used in generated content
            features: list of feature names to run (None = all). Valid
                values: {collections, discounts, shipping, content,
                product_tags, ai_config}. Unknown names are ignored
                with a warning.

        Returns:
            ``{"status": "configured"|"planned", "niche": ..., "results": {...}, "plan": [...] }``
        """
        client = ShopifyClient(shop_url, token)
        config = NICHE_CONFIGS.get(niche, NICHE_CONFIGS["general"])
        selected = self._resolve_features(features)
        self._plan = []
        results: dict[str, Any] = {}

        # Fetch products once — multiple features use it
        products_resp = client.get("products.json", params={"limit": 50})
        products = products_resp.get("products", []) if "error" not in products_resp else []
        if "error" in products_resp:
            logger.warning("Configurator: products fetch failed: %s", products_resp["error"])

        if "collections" in selected:
            results["collections"] = self._setup_collections(client, config, products)
        if "discounts" in selected:
            results["discounts"] = self._setup_discounts(client, config, store_name)
        if "shipping" in selected:
            results["shipping"] = self._check_shipping(client)
        if "content" in selected:
            results["content"] = self._create_niche_content(client, niche, config, products)
        if "product_tags" in selected:
            results["product_tags"] = self._organize_products(client, niche, products)
        if "ai_config" in selected:
            results["ai_config"] = self._save_ai_config(client, niche, config)

        self._record(results)

        return {
            "status": "planned" if self._dry_run else "configured",
            "niche": niche,
            "features": sorted(selected),
            "results": results,
            "plan": self._plan if self._dry_run else None,
        }

    # ── Helpers ────────────────────────────────────────────────

    def _resolve_features(self, features: Optional[list[str]]) -> set[str]:
        if features is None:
            return set(ALL_FEATURES)
        valid = set(ALL_FEATURES)
        selected = set()
        for f in features:
            if f in valid:
                selected.add(f)
            else:
                logger.warning("Unknown feature %r (valid: %s)", f, sorted(valid))
        return selected or set(ALL_FEATURES)

    def _write(
        self,
        client: ShopifyClient,
        method: str,
        path: str,
        json_body: Optional[dict] = None,
        *,
        description: str = "",
    ) -> dict[str, Any]:
        """POST/PUT/DELETE wrapper that honors dry_run mode."""
        entry = {
            "method": method,
            "path": path,
            "description": description,
            "body_preview": self._summarize_body(json_body),
        }
        if self._dry_run:
            self._plan.append(entry)
            return {"dry_run": True}
        if method == "POST":
            return client.post(path, json=json_body)
        if method == "PUT":
            return client.put(path, json=json_body)
        if method == "DELETE":
            return client.delete(path)
        raise ValueError(f"Unsupported write method: {method}")

    @staticmethod
    def _summarize_body(body: Optional[dict]) -> str:
        if not body:
            return ""
        try:
            s = json.dumps(body, default=str)
        except Exception:  # noqa: BLE001
            s = str(body)
        return s[:120] + ("…" if len(s) > 120 else "")

    # ── Feature: Collections ───────────────────────────────────

    def _setup_collections(
        self, client: ShopifyClient, config: dict, products: list,
    ) -> dict[str, Any]:
        existing_resp = client.get("smart_collections.json")
        existing = existing_resp.get("smart_collections", []) if "error" not in existing_resp else []
        existing_titles = set(c["title"].lower() for c in existing)

        created = 0
        for title in config["collections"]:
            if title.lower() in existing_titles:
                continue
            result = self._write(
                client, "POST", "smart_collections.json",
                {
                    "smart_collection": {
                        "title": title,
                        "body_html": f"<p>Explore our {title} selection.</p>",
                        "rules": [{
                            "column": "tag", "relation": "equals",
                            "condition": title.lower(),
                        }],
                        "published": True,
                    }
                },
                description=f"Create smart collection '{title}'",
            )
            if result.get("smart_collection") or result.get("dry_run"):
                created += 1

        # Price-based collections
        for title, rule in [("Under $20", "20"), ("Under $50", "50")]:
            if title.lower() in existing_titles:
                continue
            result = self._write(
                client, "POST", "smart_collections.json",
                {
                    "smart_collection": {
                        "title": title,
                        "rules": [{
                            "column": "variant_price", "relation": "less_than",
                            "condition": rule,
                        }],
                        "published": True,
                    }
                },
                description=f"Create price collection '{title}'",
            )
            if result.get("smart_collection") or result.get("dry_run"):
                created += 1

        return {"created": created, "existing": len(existing)}

    # ── Feature: Discounts ─────────────────────────────────────

    def _setup_discounts(
        self, client: ShopifyClient, config: dict, store_name: str,
    ) -> dict[str, Any]:
        existing_resp = client.get("price_rules.json")
        existing = existing_resp.get("price_rules", []) if "error" not in existing_resp else []
        existing_titles = set(r["title"] for r in existing)
        created: list[str] = []

        strategy = config["discount_strategy"]

        # Welcome discount (always)
        if "WELCOME15" not in existing_titles:
            self._create_discount(client, "WELCOME15", -15.0, once_per_customer=True)
            created.append("WELCOME15")

        if strategy == "aggressive":
            for code, value, kwargs in [
                ("FLASH25", -25.0, {}),
                ("BOGO50", -50.0, {"min_qty": 2}),
            ]:
                if code not in existing_titles:
                    self._create_discount(client, code, value, **kwargs)
                    created.append(code)
        elif strategy == "generous":
            if "BEAUTY20" not in existing_titles:
                self._create_discount(client, "BEAUTY20", -20.0)
                created.append("BEAUTY20")
        else:
            if "SAVE10" not in existing_titles:
                self._create_discount(client, "SAVE10", -10.0)
                created.append("SAVE10")

        return {"created": len(created), "codes": created}

    def _create_discount(
        self, client: ShopifyClient, code: str, value: float,
        once_per_customer: bool = False, min_qty: int = 0,
    ) -> None:
        rule_body: dict[str, Any] = {
            "price_rule": {
                "title": code,
                "target_type": "line_item",
                "target_selection": "all",
                "allocation_method": "across",
                "value_type": "percentage",
                "value": str(value),
                "customer_selection": "all",
                "starts_at": time.strftime("%Y-%m-%dT00:00:00Z"),
                "once_per_customer": once_per_customer,
            }
        }
        if min_qty:
            rule_body["price_rule"]["prerequisite_quantity_range"] = {
                "greater_than_or_equal_to": min_qty,
            }

        result = self._write(
            client, "POST", "price_rules.json", rule_body,
            description=f"Create price rule {code} ({value}%)",
        )
        rule_id = result.get("price_rule", {}).get("id") if result else None
        if rule_id:
            self._write(
                client, "POST",
                f"price_rules/{rule_id}/discount_codes.json",
                {"discount_code": {"code": code}},
                description=f"Attach discount code {code}",
            )
        elif result.get("dry_run"):
            # In dry-run we still want the code to be visible in the plan
            self._write(
                client, "POST",
                "price_rules/<id>/discount_codes.json",
                {"discount_code": {"code": code}},
                description=f"Attach discount code {code}",
            )

    # ── Feature: Shipping (read-only for now) ──────────────────

    def _check_shipping(self, client: ShopifyClient) -> dict[str, Any]:
        resp = client.get("shipping_zones.json")
        zones = resp.get("shipping_zones", []) if "error" not in resp else []
        return {
            "zones": len(zones),
            "details": [
                {"name": z.get("name", ""), "countries": len(z.get("countries", []))}
                for z in zones
            ],
        }

    # ── Feature: Content ───────────────────────────────────────

    def _create_niche_content(
        self, client: ShopifyClient, niche: str, config: dict, products: list,
    ) -> dict[str, Any]:
        existing_resp = client.get("pages.json")
        existing_pages = existing_resp.get("pages", []) if "error" not in existing_resp else []
        existing_titles = set(p["title"].lower() for p in existing_pages)

        created = 0
        guide_title = f"Buying Guide: Best {niche.title()} Products"
        if guide_title.lower() not in existing_titles:
            body = f"<h2>How to Choose the Best {niche.title()} Products</h2>"
            body += "<p>Our AI-curated selection helps you find the perfect products.</p>"
            body += "<h3>What to Look For</h3><ul>"
            body += "<li>Quality materials and construction</li>"
            body += "<li>Good reviews and ratings</li>"
            body += "<li>Fair pricing with good margin</li>"
            body += "<li>Fast shipping availability</li></ul>"
            if products:
                body += "<h3>Our Top Picks</h3><ul>"
                for p in products[:5]:
                    body += (
                        f'<li><a href="/products/{p.get("handle", "")}">'
                        f'{p.get("title", "")}</a></li>'
                    )
                body += "</ul>"
            body += "<p>Use code <strong>WELCOME15</strong> for 15% off!</p>"

            result = self._write(
                client, "POST", "pages.json",
                {"page": {"title": guide_title, "body_html": body, "published": True}},
                description=f"Create page '{guide_title}'",
            )
            if result.get("page") or result.get("dry_run"):
                created += 1

        return {"pages_created": created}

    # ── Feature: Product tags ──────────────────────────────────

    def _organize_products(
        self, client: ShopifyClient, niche: str, products: list,
    ) -> dict[str, Any]:
        tagged = 0
        for p in products[:20]:
            pid = p["id"]
            current_tags = p.get("tags", "") or ""
            new_tags = set(t.strip() for t in current_tags.split(",") if t.strip())
            new_tags.add(niche)

            variants = p.get("variants", [{}])
            price = float(variants[0].get("price", "0") or "0") if variants else 0.0
            if price < 20:
                new_tags.add("budget-friendly")
            elif price > 40:
                new_tags.add("premium")
            if 15 < price < 60:
                new_tags.add("gift-idea")

            updated_tags = ", ".join(sorted(new_tags))
            if updated_tags != current_tags:
                self._write(
                    client, "PUT", f"products/{pid}.json",
                    {"product": {"id": pid, "tags": updated_tags}},
                    description=f"Retag product {pid}",
                )
                tagged += 1

        return {"tagged": tagged}

    # ── Feature: AI config metafield ───────────────────────────

    def _save_ai_config(
        self, client: ShopifyClient, niche: str, config: dict,
    ) -> dict[str, Any]:
        ai_config = {
            "niche": niche,
            "target_audience": config["target_audience"],
            "discount_strategy": config["discount_strategy"],
            "configured_at": time.time(),
            "version": "2.0",
        }
        result = self._write(
            client, "POST", "metafields.json",
            {
                "metafield": {
                    "namespace": "shopai",
                    "key": "config",
                    "value": json.dumps(ai_config),
                    "type": "json",
                }
            },
            description="Save ShopAI config metafield",
        )
        return {"saved": bool(result.get("metafield") or result.get("dry_run"))}

    # ── Recording ──────────────────────────────────────────────

    def _record(self, results: dict) -> None:
        if self._dry_run:
            return
        try:
            from core.data.architecture import get_data_architecture
            da = get_data_architecture()
            da.capture(
                "action",
                {"action_type": "store_configuration", "success": True},
                source="configurator",
                score=4.5,
            )
        except Exception:  # noqa: BLE001
            pass


_instance: Optional[StoreConfigurator] = None


def get_store_configurator() -> StoreConfigurator:
    global _instance
    if _instance is None:
        _instance = StoreConfigurator()
    return _instance
