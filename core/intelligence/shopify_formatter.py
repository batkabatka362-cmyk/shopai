"""ShopifyFormatter — formats engine output for direct Shopify API use.

Converts engine results into Shopify-compatible formats:
  - Product JSON (Shopify Admin API format)
  - Metafield JSON
  - Liquid template snippets
  - Collection rules
  - Email HTML (Shopify email compatible)
"""
from __future__ import annotations

import json
from typing import Any


class ShopifyFormatter:
    """Formats engine output for Shopify API consumption."""

    def format_product(self, engine_output: dict[str, Any]) -> dict[str, Any]:
        """Format for Shopify POST /admin/api/products.json"""
        content = engine_output.get("content_elements", {})
        product = engine_output.get("product", engine_output)

        headlines = content.get("headlines", [])
        bullets = content.get("value_props", [])

        title = headlines[0] if headlines else product.get("name", "")
        body_html = self._build_product_html(product, content)

        return {
            "product": {
                "title": title,
                "body_html": body_html,
                "vendor": product.get("vendor", ""),
                "product_type": product.get("category", product.get("product_type", "")),
                "tags": ", ".join(product.get("tags", [])) if isinstance(product.get("tags"), list) else product.get("tags", ""),
                "variants": [{
                    "price": str(product.get("price", "0.00")),
                    "compare_at_price": str(product.get("compare_at_price", "")) if product.get("compare_at_price") else None,
                    "sku": product.get("sku", ""),
                    "inventory_quantity": int(product.get("inventory_quantity", product.get("stock", 0))),
                    "weight": float(product.get("weight", 0)),
                    "weight_unit": "kg",
                }],
                "metafields": self._build_metafields(engine_output),
            },
            "_shopify_api": "POST /admin/api/2024-01/products.json",
        }

    def format_price_update(self, recommendation: dict[str, Any]) -> dict[str, Any]:
        """Format for Shopify PUT /admin/api/variants/{id}.json"""
        return {
            "variant": {
                "id": recommendation.get("variant_id", ""),
                "price": str(recommendation.get("charm_price", recommendation.get("current_price", "0.00"))),
                "compare_at_price": str(recommendation.get("anchor_price", "")) if recommendation.get("anchor_price") else None,
            },
            "_shopify_api": f"PUT /admin/api/2024-01/variants/{recommendation.get('variant_id', 'ID')}.json",
            "_action": recommendation.get("action", "maintain"),
        }

    def format_collection(self, engine_output: dict[str, Any]) -> dict[str, Any]:
        """Format for Shopify POST /admin/api/smart_collections.json"""
        return {
            "smart_collection": {
                "title": engine_output.get("collection_name", "Auto Collection"),
                "rules": [
                    {"column": "tag", "relation": "equals", "condition": tag}
                    for tag in engine_output.get("tags", [])[:5]
                ],
                "sort_order": engine_output.get("sort_order", "best-selling"),
                "body_html": engine_output.get("description", ""),
            },
            "_shopify_api": "POST /admin/api/2024-01/smart_collections.json",
        }

    def format_metafields(self, product_id: str, seo_data: dict[str, Any]) -> list[dict[str, Any]]:
        """Format SEO data as Shopify metafields."""
        metafields = []

        if seo_data.get("meta_title"):
            metafields.append({
                "metafield": {
                    "namespace": "shopai",
                    "key": "seo_title",
                    "value": seo_data["meta_title"],
                    "type": "single_line_text_field",
                },
                "_shopify_api": f"POST /admin/api/2024-01/products/{product_id}/metafields.json",
            })

        if seo_data.get("meta_description"):
            metafields.append({
                "metafield": {
                    "namespace": "shopai",
                    "key": "seo_description",
                    "value": seo_data["meta_description"],
                    "type": "single_line_text_field",
                },
            })

        score = seo_data.get("on_page_audit", {}).get("score")
        if score is not None:
            metafields.append({
                "metafield": {
                    "namespace": "shopai",
                    "key": "seo_score",
                    "value": str(score),
                    "type": "number_integer",
                },
            })

        return metafields

    def format_email_html(self, email_content: dict[str, Any]) -> str:
        """Format email content as Shopify-compatible HTML."""
        sections = email_content.get("body_sections", [])
        html_parts = ['<div style="max-width:600px;margin:0 auto;font-family:Arial,sans-serif;">']

        for section in sections:
            stype = section.get("type", "")
            if stype == "hero":
                html_parts.append(f'''
<div style="text-align:center;padding:40px 20px;background:#f8f8f8;">
  <h1 style="margin:0;font-size:28px;">{section.get("headline", "")}</h1>
  <p style="color:#666;font-size:16px;">{section.get("subtext", "")}</p>
</div>''')
            elif stype == "benefits":
                items = section.get("items", [])
                items_html = "".join(f'<li style="padding:8px 0;">{item}</li>' for item in items)
                html_parts.append(f'<ul style="padding:20px 40px;list-style:none;">{items_html}</ul>')
            elif stype == "price":
                html_parts.append(f'''
<div style="text-align:center;padding:20px;">
  <span style="font-size:32px;font-weight:bold;color:#333;">{section.get("amount", "")}</span>
  <br>
  <a href="#" style="display:inline-block;margin-top:15px;padding:12px 30px;background:#000;color:#fff;text-decoration:none;border-radius:4px;">{section.get("cta", "Shop Now")}</a>
</div>''')
            elif stype == "social_proof":
                html_parts.append(f'<div style="text-align:center;padding:15px;color:#666;font-style:italic;">{section.get("text", "")}</div>')
            elif stype == "cta":
                html_parts.append(f'''
<div style="text-align:center;padding:30px;">
  <a href="#" style="display:inline-block;padding:15px 40px;background:#000;color:#fff;text-decoration:none;border-radius:4px;font-size:16px;">{section.get("primary", "Shop Now")}</a>
</div>''')

        footer = email_content.get("footer", "")
        if footer:
            html_parts.append(f'<div style="text-align:center;padding:20px;color:#999;font-size:12px;border-top:1px solid #eee;">{footer}</div>')

        html_parts.append("</div>")
        return "\n".join(html_parts)

    def format_liquid_snippet(self, content: dict[str, Any]) -> str:
        """Generate Shopify Liquid template snippet for product page."""
        bullets = content.get("bullet_points", [])
        social = content.get("social_proof", {})
        urgency = content.get("urgency_element", {})

        liquid = """{% comment %} ShopAI Generated Content {% endcomment %}
<div class="shopai-product-content">
  <h1 class="product-title">{{ product.title }}</h1>
"""
        if content.get("subheadline"):
            liquid += f'  <p class="product-subheadline">{content["subheadline"]}</p>\n'

        if bullets:
            liquid += '  <ul class="product-benefits">\n'
            for bullet in bullets:
                liquid += f'    <li>{bullet}</li>\n'
            liquid += '  </ul>\n'

        if social.get("text"):
            liquid += f'  <div class="social-proof">{social["text"]}</div>\n'

        if urgency.get("text"):
            liquid += f'  <div class="urgency-badge">{urgency["text"]}</div>\n'

        liquid += """  <div class="product-price">
    <span class="price">{{ product.price | money }}</span>
    {% if product.compare_at_price > product.price %}
      <span class="compare-price">{{ product.compare_at_price | money }}</span>
    {% endif %}
  </div>
  <button type="submit" class="btn-add-to-cart">{{ content.cta_primary | default: 'Add to Cart' }}</button>
</div>"""
        return liquid

    # --- Helpers ---

    def _build_product_html(self, product: dict, content: dict) -> str:
        name = product.get("name", "")
        body = content.get("body", product.get("description", ""))
        bullets = content.get("bullet_points", content.get("value_props", []))

        html = f"<p>{body}</p>\n" if body else ""
        if bullets:
            html += "<ul>\n"
            for b in bullets:
                html += f"  <li>{b}</li>\n"
            html += "</ul>\n"
        return html

    @staticmethod
    def _build_metafields(output: dict) -> list[dict]:
        metafields = []
        for key in ("seo_score", "quality_score", "demand_score"):
            val = output.get(key)
            if isinstance(val, (int, float)):
                metafields.append({"namespace": "shopai", "key": key, "value": str(int(val)), "type": "number_integer"})
        return metafields
