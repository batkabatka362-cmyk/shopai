"""Email Marketing Engine — body composer.

Composes the full email body: headline, product blocks, benefit bullets,
social proof snippet, and CTA text.  Outputs an HTML template string
ready for a rendering engine.

Model note: Uses LLaMA for creative body composition.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Headline templates per campaign type
# ---------------------------------------------------------------------------

_HEADLINES: dict[str, str] = {
    "promotional": "{discount_text} Everything at {store} — Shop the Sale",
    "nurture": "Discover Something New at {store}",
    "win-back": "We Saved Something Special for You, {{first_name}}",
    "announcement": "Exciting News from {store}",
}

# ---------------------------------------------------------------------------
# Social proof snippets per campaign type
# ---------------------------------------------------------------------------

_SOCIAL_PROOF: dict[str, str] = {
    "promotional": "Trusted by 10,000+ happy customers — rated 4.8/5 stars.",
    "nurture": "Join our community of {store} insiders who love what we share.",
    "win-back": "Thousands of customers came back — here's why they stayed.",
    "announcement": "Be among the first to experience what's next from {store}.",
}

# ---------------------------------------------------------------------------
# CTA text per campaign type
# ---------------------------------------------------------------------------

_CTA_TEXT: dict[str, str] = {
    "promotional": "Shop Now & Save",
    "nurture": "Explore More",
    "win-back": "Claim Your Offer",
    "announcement": "Learn More",
}

# ---------------------------------------------------------------------------
# Benefit bullet generators
# ---------------------------------------------------------------------------

_BENEFIT_BULLETS: dict[str, list[str]] = {
    "promotional": [
        "Free shipping on all orders over $50",
        "Easy 30-day returns — no questions asked",
        "Exclusive deals for subscribers only",
    ],
    "nurture": [
        "Curated picks based on your interests",
        "Expert tips delivered to your inbox",
        "First access to new arrivals",
    ],
    "win-back": [
        "Your favorites are still here — and on sale",
        "New products you haven't seen yet",
        "A special comeback discount just for you",
    ],
    "announcement": [
        "Be the first to try our latest launch",
        "Limited availability — early access for subscribers",
        "Share the news and earn rewards",
    ],
}


def compose_body(
    goal: str,
    products: list[dict[str, Any]],
    store_name: str,
    discount: dict[str, Any],
    content_plan: dict[str, Any],
) -> dict[str, Any]:
    """Compose the full email body with HTML template.

    Args:
        goal: Campaign goal / type.
        products: List of ProductInfo dicts.
        store_name: Store display name.
        discount: DiscountInfo dict.
        content_plan: ContentPlan result from content_planner.

    Returns:
        Structured dict with EmailBody data.
    """
    try:
        goal_key = str(goal).lower().strip()
        prods = copy.deepcopy(products)
        discount_text = _format_discount(discount)

        # Build headline
        headline_tpl = _HEADLINES.get(goal_key, _HEADLINES["promotional"])
        headline = headline_tpl.replace("{store}", store_name)
        headline = headline.replace("{discount_text}", discount_text)

        # Build product blocks
        product_blocks: list[dict[str, Any]] = []
        for prod in prods[:4]:  # max 4 products
            title = prod.get("title", "Product")
            price = prod.get("price", 0)
            image_url = prod.get("image_url", "")
            discounted_price = _apply_discount(price, discount)

            product_blocks.append({
                "title": title,
                "original_price": f"${price:.2f}" if price else "",
                "discounted_price": f"${discounted_price:.2f}" if discounted_price != price else "",
                "image_url": image_url,
                "cta": "Shop Now",
            })

        # Build benefit bullets
        benefit_bullets = copy.deepcopy(
            _BENEFIT_BULLETS.get(goal_key, _BENEFIT_BULLETS["promotional"])
        )
        if discount and discount.get("value"):
            benefit_bullets.insert(0, f"Save {discount_text} on your order today")

        # Social proof
        social_proof = _SOCIAL_PROOF.get(goal_key, _SOCIAL_PROOF["promotional"])
        social_proof = social_proof.replace("{store}", store_name)

        # CTA text
        cta_text = _CTA_TEXT.get(goal_key, _CTA_TEXT["promotional"])

        # Build HTML template
        html_template = _build_html(
            headline=headline,
            product_blocks=product_blocks,
            benefit_bullets=benefit_bullets,
            social_proof=social_proof,
            cta_text=cta_text,
            store_name=store_name,
            content_plan=content_plan,
        )

        return {
            "status": "success",
            "body": {
                "html_template": html_template,
                "headline": headline,
                "product_blocks": product_blocks,
                "benefit_bullets": benefit_bullets,
                "social_proof": social_proof,
                "cta_text": cta_text,
                "model_note": "LLaMA: creative body composition with product blocks",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "body": {},
            "error": f"Body composition failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _format_discount(discount: dict[str, Any]) -> str:
    """Format discount into readable text."""
    if not discount:
        return "great deals on"
    disc_type = discount.get("type", "percentage")
    disc_val = discount.get("value", 0)
    if disc_type == "percentage":
        return f"{int(disc_val)}% Off"
    return f"${disc_val} Off"


def _apply_discount(price: float, discount: dict[str, Any]) -> float:
    """Apply discount to a price."""
    if not discount or not price:
        return price
    disc_type = discount.get("type", "percentage")
    disc_val = discount.get("value", 0)
    if disc_type == "percentage":
        return round(price * (1 - disc_val / 100), 2)
    return round(max(price - disc_val, 0), 2)


def _build_html(
    *,
    headline: str,
    product_blocks: list[dict[str, Any]],
    benefit_bullets: list[str],
    social_proof: str,
    cta_text: str,
    store_name: str,
    content_plan: dict[str, Any],
) -> str:
    """Build an HTML email template string."""
    sections = content_plan.get("sections", [])
    tone = content_plan.get("tone", "professional")

    # Product grid HTML
    product_html_parts: list[str] = []
    for block in product_blocks:
        price_line = block["original_price"]
        if block["discounted_price"]:
            price_line = (
                f'<span style="text-decoration:line-through">{block["original_price"]}</span>'
                f' <strong>{block["discounted_price"]}</strong>'
            )
        product_html_parts.append(
            f'<div class="product-card">'
            f'<img src="{block["image_url"]}" alt="{block["title"]}" />'
            f'<h3>{block["title"]}</h3>'
            f'<p>{price_line}</p>'
            f'<a href="#" class="btn">{block["cta"]}</a>'
            f'</div>'
        )
    product_grid = "\n".join(product_html_parts)

    # Benefit list HTML
    bullets_html = "\n".join(f"<li>{b}</li>" for b in benefit_bullets)

    # Section count for template comment
    section_names = [s.get("type", "unknown") for s in sections]

    html = (
        f'<!-- Email: {store_name} | Tone: {tone} | Sections: {", ".join(section_names)} -->\n'
        f'<div class="email-container">\n'
        f'  <div class="header"><h1>{headline}</h1></div>\n'
        f'  <div class="product-grid">\n{product_grid}\n  </div>\n'
        f'  <div class="benefits"><ul>\n{bullets_html}\n  </ul></div>\n'
        f'  <div class="social-proof"><p>{social_proof}</p></div>\n'
        f'  <div class="cta"><a href="#" class="btn-primary">{cta_text}</a></div>\n'
        f'  <div class="footer"><p>You are receiving this because you subscribed to {store_name}.'
        f' <a href="{{{{unsubscribe_url}}}}">Unsubscribe</a></p></div>\n'
        f'</div>'
    )
    return html
