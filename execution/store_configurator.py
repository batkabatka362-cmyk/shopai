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
    "gifts",
    "loyalty",
    "referral",
)


# Niche → free-gift threshold (USD). Stores a rule "orders >= N get a
# free gift" as a metafield. Consumed by a Shopify Function or a cart
# page snippet — the configurator just lays down the data.
_GIFT_THRESHOLDS = {
    "beauty": 50.0,
    "fashion": 75.0,
    "tech": 100.0,
    "home": 75.0,
    "general": 60.0,
}

# Niche → loyalty point rules
_LOYALTY_RULES = {
    "beauty":  {"earn_per_dollar": 2, "redeem_value_cents": 1, "welcome_bonus": 100},
    "fashion": {"earn_per_dollar": 1, "redeem_value_cents": 1, "welcome_bonus": 50},
    "tech":    {"earn_per_dollar": 1, "redeem_value_cents": 1, "welcome_bonus": 25},
    "home":    {"earn_per_dollar": 1, "redeem_value_cents": 1, "welcome_bonus": 50},
    "general": {"earn_per_dollar": 1, "redeem_value_cents": 1, "welcome_bonus": 25},
}


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
        if "gifts" in selected:
            results["gifts"] = self._setup_gifts(client, niche, products)
        if "loyalty" in selected:
            results["loyalty"] = self._setup_loyalty(client, niche)
        if "referral" in selected:
            results["referral"] = self._setup_referral(client, niche)

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
        """Create niche-specific + smart data-driven collections.

        Three tiers of collections are created:

        1. Niche category collections (tag-based) — "Home Decor",
           "Lighting", etc. — matches products with a lowercased tag.
        2. Price bands — "Under $20", "Under $50".
        3. Smart data-driven collections derived from the actual
           product data that was fetched:
             * "Bestsellers"     — tag-rule on `bestseller`
             * "New Arrivals"    — products created in the last 30 days
             * "Low Stock"       — total inventory <= 5 (urgency)
             * "Top Rated"       — tag-rule on `top-rated`
             * "Back in Stock"   — tag-rule on `back-in-stock`
             * "Gift Ideas"      — tag-rule on `gift-idea`
           Each smart collection is skipped when the product set has no
           candidates (e.g. no low-stock items) so stores don't end up
           with empty storefront sections.
        """
        existing_resp = client.get("smart_collections.json")
        existing = existing_resp.get("smart_collections", []) if "error" not in existing_resp else []
        existing_titles = set(c["title"].lower() for c in existing)

        created = 0
        skipped_empty = 0

        def _try_create(
            title: str,
            rules: list[dict],
            description: str,
            body_html: str = "",
        ) -> None:
            nonlocal created
            if title.lower() in existing_titles:
                return
            body = {
                "smart_collection": {
                    "title": title,
                    "rules": rules,
                    "published": True,
                }
            }
            if body_html:
                body["smart_collection"]["body_html"] = body_html
            result = self._write(
                client, "POST", "smart_collections.json", body,
                description=description,
            )
            if result.get("smart_collection") or result.get("dry_run"):
                created += 1

        # Tier 1 — niche category collections
        for title in config["collections"]:
            _try_create(
                title,
                [{"column": "tag", "relation": "equals", "condition": title.lower()}],
                f"Create smart collection '{title}'",
                body_html=f"<p>Explore our {title} selection.</p>",
            )

        # Tier 2 — price bands
        for title, cond in [("Under $20", "20"), ("Under $50", "50")]:
            _try_create(
                title,
                [{"column": "variant_price", "relation": "less_than", "condition": cond}],
                f"Create price collection '{title}'",
            )

        # Tier 3 — smart data-driven collections.
        # We inspect the actual products to decide whether each one is
        # worth creating, then point the collection at a tag the system
        # maintains elsewhere (bestseller, top-rated, back-in-stock, etc).
        analysis = self._analyze_products_for_collections(products)

        smart_specs = [
            ("Bestsellers", "bestseller",
             "Our top-selling products based on real order data",
             analysis["has_bestsellers"]),
            ("New Arrivals", None,  # special: date-based rule
             "Recently added — still hot",
             analysis["has_new_arrivals"]),
            ("Low Stock", None,  # special: inventory rule
             "Selling fast — grab them before they're gone",
             analysis["has_low_stock"]),
            ("Top Rated", "top-rated",
             "Customer-favorite products with the best ratings",
             analysis["has_top_rated"]),
            ("Back in Stock", "back-in-stock",
             "Just restocked — don't miss out again",
             analysis["has_back_in_stock"]),
            ("Gift Ideas", "gift-idea",
             "Perfect picks for any occasion",
             analysis["has_gift_ideas"]),
        ]

        for title, tag, blurb, should_create in smart_specs:
            if not should_create:
                skipped_empty += 1
                continue
            if title == "New Arrivals":
                # Products published in the last 30 days
                cutoff = time.strftime(
                    "%Y-%m-%dT00:00:00Z",
                    time.gmtime(time.time() - 30 * 86400),
                )
                rules = [{
                    "column": "created_at",
                    "relation": "greater_than",
                    "condition": cutoff,
                }]
            elif title == "Low Stock":
                rules = [{
                    "column": "inventory_stock",
                    "relation": "less_than",
                    "condition": "6",
                }]
            else:
                rules = [{
                    "column": "tag", "relation": "equals", "condition": tag,
                }]
            _try_create(
                title, rules,
                f"Create smart collection '{title}' (data-driven)",
                body_html=f"<p>{blurb}</p>",
            )

        return {
            "created": created,
            "existing": len(existing),
            "skipped_empty": skipped_empty,
            "analysis": analysis,
        }

    @staticmethod
    def _analyze_products_for_collections(products: list) -> dict[str, Any]:
        """Inspect products and decide which smart collections make sense.

        Returns a dict of boolean flags that _setup_collections uses to
        decide which data-driven collections to create. Flags are based
        on simple signals visible in the Shopify product payload:

        - has_bestsellers: any product tagged ``bestseller``
        - has_new_arrivals: any product with created_at in last 30 days
        - has_low_stock: total inventory across variants <= 5
        - has_top_rated: any product tagged ``top-rated``
        - has_back_in_stock: any product tagged ``back-in-stock``
        - has_gift_ideas: any product tagged ``gift-idea`` or title
                         contains "gift"
        """
        analysis = {
            "has_bestsellers": False,
            "has_new_arrivals": False,
            "has_low_stock": False,
            "has_top_rated": False,
            "has_back_in_stock": False,
            "has_gift_ideas": False,
            "total_products": len(products),
            "new_count": 0,
            "low_stock_count": 0,
        }
        if not products:
            return analysis

        cutoff_ts = time.time() - 30 * 86400
        for p in products:
            tags_raw = p.get("tags", "") or ""
            tags = {t.strip().lower() for t in tags_raw.split(",") if t.strip()}
            title = (p.get("title") or "").lower()

            if "bestseller" in tags:
                analysis["has_bestsellers"] = True
            if "top-rated" in tags:
                analysis["has_top_rated"] = True
            if "back-in-stock" in tags:
                analysis["has_back_in_stock"] = True
            if "gift-idea" in tags or "gift" in title:
                analysis["has_gift_ideas"] = True

            # New arrivals: parse created_at if present
            created_str = p.get("created_at", "") or ""
            if created_str:
                try:
                    # Shopify returns ISO 8601 with TZ, e.g. 2026-01-15T12:00:00-05:00
                    from datetime import datetime
                    try:
                        ts = datetime.fromisoformat(
                            created_str.replace("Z", "+00:00")
                        ).timestamp()
                    except ValueError:
                        ts = 0
                    if ts >= cutoff_ts:
                        analysis["has_new_arrivals"] = True
                        analysis["new_count"] += 1
                except Exception:  # noqa: BLE001
                    pass

            # Low stock: sum inventory across variants
            total_inv = 0
            for v in p.get("variants") or []:
                try:
                    total_inv += int(v.get("inventory_quantity", 0) or 0)
                except (TypeError, ValueError):
                    pass
            if 0 < total_inv <= 5:
                analysis["has_low_stock"] = True
                analysis["low_stock_count"] += 1

        return analysis

    # ── Feature: Discounts ─────────────────────────────────────

    # Month → (code, percent off, description) for the seasonal rule.
    # Shopify stores a single seasonal code at a time; whichever month
    # the configurator runs in drives the choice.
    _SEASONAL_CODES = {
        1:  ("NEWYEAR10",    -10.0, "New Year kickoff"),
        2:  ("VALENTINE15",  -15.0, "Valentine's Day"),
        3:  ("SPRING10",     -10.0, "Spring sale"),
        4:  ("EASTER15",     -15.0, "Easter"),
        5:  ("MAYFLASH10",   -10.0, "May sale"),
        6:  ("SUMMER15",     -15.0, "Summer kickoff"),
        7:  ("JULY4",        -15.0, "Mid-summer sale"),
        8:  ("BACKTOSCHOOL", -15.0, "Back to school"),
        9:  ("AUTUMN10",     -10.0, "Autumn sale"),
        10: ("HALLOWEEN15",  -15.0, "Halloween"),
        11: ("BLACKFRIDAY25",-25.0, "Black Friday"),
        12: ("HOLIDAY20",    -20.0, "Holiday season"),
    }

    def _setup_discounts(
        self, client: ShopifyClient, config: dict, store_name: str,
    ) -> dict[str, Any]:
        """Comprehensive discount strategy.

        Every store gets:
          WELCOME15       — first-time buyer (-15%, once per customer)
          COMEBACK10      — abandoned-cart recovery (-10%, once per customer)
          BUNDLE15        — volume discount when buying 3+ items (-15%)
          FREESHIP50      — free shipping on orders >= $50 (shipping type)
          <SEASONAL>      — one code for the current calendar month
          LOYAL20         — repeat-customer loyalty discount (-20%, once per customer)

        Niche strategy adds on top:
          aggressive → FLASH25, BOGO50
          generous   → BEAUTY20
          moderate   → SAVE10
        """
        existing_resp = client.get("price_rules.json")
        existing = existing_resp.get("price_rules", []) if "error" not in existing_resp else []
        existing_titles = set(r["title"] for r in existing)
        created: list[str] = []

        def _add(code: str, value: float, **kwargs: Any) -> None:
            if code in existing_titles:
                return
            self._create_discount(client, code, value, **kwargs)
            created.append(code)

        # Core discounts every store gets
        _add("WELCOME15", -15.0, once_per_customer=True,
             description="First-time buyer welcome")
        _add("COMEBACK10", -10.0, once_per_customer=True,
             description="Abandoned cart recovery")
        _add("BUNDLE15", -15.0, min_qty=3,
             description="Volume discount (3+ items)")
        _add("FREESHIP50", -100.0, min_subtotal=50.0, target_type="shipping_line",
             description="Free shipping on orders >= $50")
        _add("LOYAL20", -20.0, once_per_customer=True,
             description="Loyalty reward for repeat customers")

        # One seasonal code based on current month
        month = time.gmtime().tm_mon
        seasonal_code, seasonal_value, seasonal_desc = self._SEASONAL_CODES[month]
        _add(seasonal_code, seasonal_value,
             description=f"Seasonal: {seasonal_desc}")

        # Niche-strategy discounts
        strategy = config["discount_strategy"]
        if strategy == "aggressive":
            _add("FLASH25", -25.0, description="Flash sale")
            _add("BOGO50", -50.0, min_qty=2,
                 description="Buy-one-get-one 50%")
        elif strategy == "generous":
            _add("BEAUTY20", -20.0, description="Generous beauty discount")
        else:  # moderate
            _add("SAVE10", -10.0, description="Moderate savings")

        return {
            "created": len(created),
            "codes": created,
            "seasonal": seasonal_code,
            "strategy": strategy,
        }

    def _create_discount(
        self,
        client: ShopifyClient,
        code: str,
        value: float,
        *,
        once_per_customer: bool = False,
        min_qty: int = 0,
        min_subtotal: float = 0.0,
        target_type: str = "line_item",
        description: str = "",
    ) -> None:
        """Create a price rule + attach a discount code.

        Args:
            code: the discount code users enter at checkout
            value: negative percentage (e.g. -15.0 = 15% off)
            once_per_customer: restrict to one use per customer
            min_qty: minimum line-item quantity (volume discount)
            min_subtotal: minimum cart subtotal (free-shipping threshold)
            target_type: "line_item" for product discounts or
                         "shipping_line" for shipping discounts
            description: human-readable summary shown in the dry-run plan
        """
        rule_body: dict[str, Any] = {
            "price_rule": {
                "title": code,
                "target_type": target_type,
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
        if min_subtotal > 0:
            rule_body["price_rule"]["prerequisite_subtotal_range"] = {
                "greater_than_or_equal_to": str(min_subtotal),
            }

        desc = description or f"Create price rule {code} ({value}%)"
        result = self._write(
            client, "POST", "price_rules.json", rule_body, description=desc,
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

    # ── Feature: Free gift with purchase ───────────────────────

    def _setup_gifts(
        self, client: ShopifyClient, niche: str, products: list,
    ) -> dict[str, Any]:
        """Configure a "free gift with purchase" program.

        Shopify REST doesn't natively support "free gift at threshold"
        — that's typically done via a Shopify Function, cart script, or
        a third-party app. The configurator lays down the data as a
        shop metafield (``shopai.gifts``) so downstream code can read
        a single source of truth.

        It also picks an eligible gift product (lowest-priced item in
        the store that isn't tagged ``no-gift``) and retags it with
        ``free-gift-eligible`` so the storefront UI can highlight it.
        """
        threshold = _GIFT_THRESHOLDS.get(niche, _GIFT_THRESHOLDS["general"])

        gift_product = self._pick_gift_product(products)
        eligible_id = gift_product.get("id") if gift_product else None

        program = {
            "enabled": True,
            "threshold_usd": threshold,
            "gift_product_id": eligible_id,
            "gift_product_title": gift_product.get("title") if gift_product else None,
            "message": f"Spend ${threshold:.0f}+ and get a free gift!",
            "configured_at": time.time(),
        }
        result = self._write(
            client, "POST", "metafields.json",
            {
                "metafield": {
                    "namespace": "shopai",
                    "key": "gifts",
                    "value": json.dumps(program),
                    "type": "json",
                }
            },
            description=f"Save gift program (threshold ${threshold:.0f})",
        )
        saved = bool(result.get("metafield") or result.get("dry_run"))

        # Tag the gift product so the storefront can find it
        tagged = False
        if gift_product:
            current_tags = gift_product.get("tags", "") or ""
            tag_set = {t.strip() for t in current_tags.split(",") if t.strip()}
            if "free-gift-eligible" not in tag_set:
                tag_set.add("free-gift-eligible")
                updated = ", ".join(sorted(tag_set))
                self._write(
                    client, "PUT", f"products/{eligible_id}.json",
                    {"product": {"id": eligible_id, "tags": updated}},
                    description=f"Tag gift product {eligible_id}",
                )
                tagged = True

        return {
            "saved": saved,
            "threshold": threshold,
            "gift_product_id": eligible_id,
            "tagged": tagged,
        }

    @staticmethod
    def _pick_gift_product(products: list) -> Optional[dict]:
        """Pick the lowest-priced product that's eligible to be a free gift.

        Eligibility: has a positive price, isn't tagged ``no-gift`` or
        ``premium``, and has at least 1 in stock across variants.
        """
        candidates = []
        for p in products:
            tags_raw = p.get("tags", "") or ""
            tags = {t.strip().lower() for t in tags_raw.split(",") if t.strip()}
            if "no-gift" in tags or "premium" in tags:
                continue
            variants = p.get("variants") or []
            if not variants:
                continue
            try:
                price = float(variants[0].get("price", "0") or "0")
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            # Need at least 1 in stock
            total_inv = 0
            for v in variants:
                try:
                    total_inv += int(v.get("inventory_quantity", 0) or 0)
                except (TypeError, ValueError):
                    pass
            if total_inv < 1:
                continue
            candidates.append((price, p))

        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    # ── Feature: Loyalty points ────────────────────────────────

    def _setup_loyalty(
        self, client: ShopifyClient, niche: str,
    ) -> dict[str, Any]:
        """Configure a loyalty-point program as a shop metafield.

        Like gifts, this is a data-only configuration — the actual
        point accrual/redemption is handled by a Shopify Function or
        an app that reads ``shopai.loyalty``.
        """
        rules = _LOYALTY_RULES.get(niche, _LOYALTY_RULES["general"])
        program = {
            "enabled": True,
            "earn_per_dollar": rules["earn_per_dollar"],
            "redeem_value_cents": rules["redeem_value_cents"],
            "welcome_bonus": rules["welcome_bonus"],
            "tiers": [
                {"name": "Bronze",   "min_points": 0,    "multiplier": 1.0},
                {"name": "Silver",   "min_points": 500,  "multiplier": 1.25},
                {"name": "Gold",     "min_points": 2000, "multiplier": 1.5},
                {"name": "Platinum", "min_points": 5000, "multiplier": 2.0},
            ],
            "configured_at": time.time(),
        }
        result = self._write(
            client, "POST", "metafields.json",
            {
                "metafield": {
                    "namespace": "shopai",
                    "key": "loyalty",
                    "value": json.dumps(program),
                    "type": "json",
                }
            },
            description=(
                f"Save loyalty program ({rules['earn_per_dollar']}x earn, "
                f"{rules['welcome_bonus']} welcome bonus)"
            ),
        )
        return {
            "saved": bool(result.get("metafield") or result.get("dry_run")),
            "earn_per_dollar": rules["earn_per_dollar"],
            "welcome_bonus": rules["welcome_bonus"],
            "tiers": 4,
        }

    # ── Feature: Referral program ──────────────────────────────

    def _setup_referral(
        self, client: ShopifyClient, niche: str,
    ) -> dict[str, Any]:
        """Create a referral program: a FRIEND10 code + metafield config."""
        # The discount itself (created idempotently — it's fine if it
        # already exists because _create_discount checks existing)
        existing_resp = client.get("price_rules.json")
        existing = existing_resp.get("price_rules", []) if "error" not in existing_resp else []
        existing_titles = {r["title"] for r in existing}
        code = "FRIEND10"
        code_created = False
        if code not in existing_titles:
            self._create_discount(
                client, code, -10.0,
                description="Referral reward (given to the friend)",
            )
            code_created = True

        program = {
            "enabled": True,
            "discount_code": code,
            "referrer_reward": {"type": "points", "value": 100},
            "referred_reward": {"type": "discount", "code": code, "percent": 10},
            "max_referrals_per_customer": 10,
            "configured_at": time.time(),
        }
        result = self._write(
            client, "POST", "metafields.json",
            {
                "metafield": {
                    "namespace": "shopai",
                    "key": "referral",
                    "value": json.dumps(program),
                    "type": "json",
                }
            },
            description=f"Save referral program ({code})",
        )
        return {
            "saved": bool(result.get("metafield") or result.get("dry_run")),
            "discount_code": code,
            "code_created": code_created,
        }

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
