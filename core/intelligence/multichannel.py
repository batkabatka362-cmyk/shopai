"""MultiChannel — sync products across Google Merchant, Meta, TikTok.

Formats product data for each platform's feed specification.
"""
from __future__ import annotations

from typing import Any


class MultiChannel:
    """Format and sync products across sales channels."""

    def format_for_google(self, products: list[dict[str, Any]], store_url: str = "") -> dict[str, Any]:
        """Format products for Google Merchant Center feed."""
        items = []
        for p in products:
            item = {
                "id": str(p.get("id", p.get("sku", ""))),
                "title": p.get("name", p.get("title", ""))[:150],
                "description": p.get("description", p.get("body", f"Shop {p.get('name', 'product')}"))[:5000],
                "link": f"{store_url}/products/{self._slugify(p.get('name', ''))}",
                "image_link": p.get("image", p.get("image_url", "")),
                "availability": "in_stock" if int(p.get("inventory_quantity", p.get("stock", 0))) > 0 else "out_of_stock",
                "price": f"{float(p.get('price', 0)):.2f} USD",
                "brand": p.get("vendor", p.get("brand", "")),
                "condition": "new",
                "product_type": p.get("category", p.get("product_type", "")),
                "gtin": p.get("barcode", p.get("gtin", "")),
                "mpn": p.get("sku", ""),
            }
            # Sale price
            compare = float(p.get("compare_at_price", 0))
            if compare > float(p.get("price", 0)):
                item["sale_price"] = f"{float(p.get('price', 0)):.2f} USD"
                item["price"] = f"{compare:.2f} USD"

            # Shipping
            weight = float(p.get("weight", 0))
            if weight > 0:
                item["shipping_weight"] = f"{weight} kg"

            items.append(item)

        errors = self._validate_google(items)
        return {
            "channel": "google_merchant",
            "format": "Content API",
            "total_products": len(items),
            "items": items,
            "errors": errors,
            "valid": len(items) - len(errors),
        }

    def format_for_meta(self, products: list[dict[str, Any]], store_url: str = "") -> dict[str, Any]:
        """Format products for Meta Commerce / Facebook Catalog."""
        items = []
        for p in products:
            price = float(p.get("price", 0))
            item = {
                "id": str(p.get("id", "")),
                "title": p.get("name", "")[:200],
                "description": p.get("description", f"Shop {p.get('name', '')}")[:9999],
                "availability": "in stock" if int(p.get("inventory_quantity", 0)) > 0 else "out of stock",
                "condition": "new",
                "price": f"{price:.2f} USD",
                "link": f"{store_url}/products/{self._slugify(p.get('name', ''))}",
                "image_link": p.get("image", ""),
                "brand": p.get("vendor", ""),
                "product_type": p.get("category", ""),
            }
            compare = float(p.get("compare_at_price", 0))
            if compare > price:
                item["sale_price"] = f"{price:.2f} USD"
                item["sale_price_effective_date"] = ""

            items.append(item)

        return {
            "channel": "meta_catalog",
            "format": "Commerce Manager",
            "total_products": len(items),
            "items": items,
        }

    def format_for_tiktok(self, products: list[dict[str, Any]], store_url: str = "") -> dict[str, Any]:
        """Format products for TikTok Shop catalog."""
        items = []
        for p in products:
            items.append({
                "sku_id": str(p.get("id", p.get("sku", ""))),
                "product_name": p.get("name", "")[:255],
                "description": p.get("description", "")[:2000] or f"Shop {p.get('name', '')}",
                "category_id": p.get("category", ""),
                "brand_name": p.get("vendor", ""),
                "original_price": float(p.get("compare_at_price", p.get("price", 0))),
                "sale_price": float(p.get("price", 0)),
                "stock_quantity": int(p.get("inventory_quantity", 0)),
                "weight": float(p.get("weight", 0)),
                "main_image": p.get("image", ""),
                "product_url": f"{store_url}/products/{self._slugify(p.get('name', ''))}",
            })

        return {
            "channel": "tiktok_shop",
            "format": "TikTok Catalog",
            "total_products": len(items),
            "items": items,
        }

    def sync_all_channels(self, products: list[dict[str, Any]], store_url: str = "") -> dict[str, Any]:
        """Format for all channels at once."""
        return {
            "google": self.format_for_google(products, store_url),
            "meta": self.format_for_meta(products, store_url),
            "tiktok": self.format_for_tiktok(products, store_url),
            "total_products": len(products),
            "channels": 3,
        }

    def channel_health(self, products: list[dict[str, Any]]) -> dict[str, Any]:
        """Check product readiness for each channel."""
        issues = {"google": [], "meta": [], "tiktok": []}

        for p in products:
            name = p.get("name", "?")
            if not p.get("description") and not p.get("body"):
                for ch in issues:
                    issues[ch].append(f"{name}: missing description")
            if not p.get("image") and not p.get("image_url"):
                for ch in issues:
                    issues[ch].append(f"{name}: missing image")
            if float(p.get("price", 0)) <= 0:
                for ch in issues:
                    issues[ch].append(f"{name}: no price")
            if not p.get("category") and not p.get("product_type"):
                issues["google"].append(f"{name}: missing product_type (required for Google)")

        readiness = {}
        for ch, ch_issues in issues.items():
            total = len(products)
            problematic = len(set(i.split(":")[0] for i in ch_issues))
            readiness[ch] = {
                "ready": total - problematic,
                "issues": problematic,
                "ready_pct": round((total - problematic) / max(total, 1) * 100, 1),
                "top_issues": ch_issues[:5],
            }

        return readiness

    @staticmethod
    def _validate_google(items: list[dict]) -> list[dict[str, str]]:
        errors = []
        for item in items:
            if not item.get("title"):
                errors.append({"id": item.get("id", "?"), "error": "missing_title"})
            if not item.get("link"):
                errors.append({"id": item.get("id", "?"), "error": "missing_link"})
            if not item.get("price"):
                errors.append({"id": item.get("id", "?"), "error": "missing_price"})
        return errors

    @staticmethod
    def _slugify(text: str) -> str:
        return text.lower().replace(" ", "-").replace("'", "").replace('"', "")[:100]
