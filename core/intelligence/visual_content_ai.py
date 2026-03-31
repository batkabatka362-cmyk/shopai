"""Visual Content AI — generates image/design specifications.

Outputs design briefs that can be used with Canva API, Figma, or AI image tools.
Not actual images — structured specs that any design tool can consume.
"""
from __future__ import annotations

from typing import Any


# Brand color palettes by industry
PALETTES = {
    "electronics": {"primary": "#1a1a2e", "secondary": "#0f3460", "accent": "#e94560", "bg": "#f5f5f5"},
    "fitness": {"primary": "#2d6a4f", "secondary": "#40916c", "accent": "#ff6b35", "bg": "#fafafa"},
    "beauty": {"primary": "#d4a373", "secondary": "#ccd5ae", "accent": "#e63946", "bg": "#fefae0"},
    "home": {"primary": "#463f3a", "secondary": "#8a817c", "accent": "#e0afa0", "bg": "#f4f3ee"},
    "fashion": {"primary": "#000000", "secondary": "#333333", "accent": "#d4af37", "bg": "#ffffff"},
    "default": {"primary": "#2563eb", "secondary": "#1e40af", "accent": "#f59e0b", "bg": "#f8fafc"},
}


class VisualContentAI:
    """Generates visual content specifications for e-commerce."""

    def product_image_brief(self, product: dict[str, Any]) -> dict[str, Any]:
        """Generate photography/render brief for a product."""
        name = product.get("name", "Product")
        category = product.get("category", "default").lower()
        price = float(product.get("price", 0))
        tier = "luxury" if price > 100 else "premium" if price > 50 else "standard"

        return {
            "product": name,
            "shots": [
                {"type": "hero", "angle": "45-degree front", "background": "clean white" if tier != "luxury" else "dark gradient",
                 "lighting": "soft studio", "aspect_ratio": "1:1", "use": "main listing image"},
                {"type": "lifestyle", "setting": self._lifestyle_setting(category), "mood": "aspirational",
                 "aspect_ratio": "4:5", "use": "social media, collection page"},
                {"type": "detail", "focus": "texture and build quality", "macro": True,
                 "aspect_ratio": "1:1", "use": "product page gallery"},
                {"type": "scale", "show_with": "hand or everyday object for size reference",
                 "aspect_ratio": "1:1", "use": "product page"},
                {"type": "packaging", "show": "unboxing experience", "angle": "overhead flat lay",
                 "aspect_ratio": "16:9", "use": "social media, email"},
            ],
            "style_guide": {
                "palette": PALETTES.get(category, PALETTES["default"]),
                "tier": tier,
                "mood": "clean and professional" if tier == "standard" else "premium and aspirational",
                "font_suggestion": "Inter or Montserrat" if tier != "luxury" else "Playfair Display",
            },
            "formats": {
                "shopify_main": {"width": 2048, "height": 2048, "format": "webp"},
                "instagram_post": {"width": 1080, "height": 1080, "format": "jpg"},
                "instagram_story": {"width": 1080, "height": 1920, "format": "jpg"},
                "facebook_ad": {"width": 1200, "height": 628, "format": "jpg"},
                "email_hero": {"width": 600, "height": 400, "format": "jpg"},
            },
        }

    def social_post_spec(self, product: dict[str, Any], platform: str = "instagram") -> dict[str, Any]:
        """Generate social media post visual specification."""
        name = product.get("name", "Product")
        price = float(product.get("price", 0))
        category = product.get("category", "default").lower()
        palette = PALETTES.get(category, PALETTES["default"])

        specs = {
            "instagram": {
                "formats": [
                    {"type": "feed_post", "size": "1080x1080", "content": f"Product hero with price overlay ${price:.2f}"},
                    {"type": "carousel", "slides": 3, "size": "1080x1080",
                     "slide_content": ["Hero shot + headline", "3 key benefits", "CTA + price"]},
                    {"type": "reel_cover", "size": "1080x1920", "content": "Eye-catching product in action"},
                    {"type": "story", "size": "1080x1920", "content": "Swipe up to shop + countdown sticker"},
                ],
            },
            "facebook": {
                "formats": [
                    {"type": "ad_image", "size": "1200x628", "content": "Product + benefit headline + CTA"},
                    {"type": "carousel_ad", "cards": 3, "size": "1080x1080",
                     "card_content": ["Product hero", "Key benefit", "Offer + CTA"]},
                ],
            },
            "tiktok": {
                "formats": [
                    {"type": "video_thumbnail", "size": "1080x1920", "content": "Hook text + product preview"},
                    {"type": "spark_ad", "size": "1080x1920", "content": "Native-looking product showcase"},
                ],
            },
        }

        return {
            "product": name,
            "platform": platform,
            "palette": palette,
            "specs": specs.get(platform, specs["instagram"]),
            "copy_overlay": {
                "headline": f"{name}" if len(name) < 20 else name.split()[0],
                "subtext": f"Starting at ${price:.2f}" if price else "Shop Now",
                "cta": "Shop Now →",
            },
            "hashtags": self._generate_hashtags(name, category),
        }

    def banner_spec(self, campaign: dict[str, Any]) -> dict[str, Any]:
        """Generate banner ad specifications for a campaign."""
        name = campaign.get("name", "Campaign")
        discount = campaign.get("discount", "")
        category = campaign.get("category", "default").lower()
        palette = PALETTES.get(category, PALETTES["default"])

        return {
            "campaign": name,
            "sizes": [
                {"name": "leaderboard", "width": 728, "height": 90, "use": "website header"},
                {"name": "medium_rectangle", "width": 300, "height": 250, "use": "sidebar"},
                {"name": "skyscraper", "width": 160, "height": 600, "use": "sidebar"},
                {"name": "mobile_banner", "width": 320, "height": 50, "use": "mobile"},
                {"name": "hero", "width": 1920, "height": 600, "use": "homepage"},
            ],
            "design": {
                "palette": palette,
                "headline": f"{discount} OFF" if discount else name,
                "subtext": campaign.get("description", "Limited time offer"),
                "cta_text": "Shop Now",
                "cta_color": palette["accent"],
                "layout": "left-aligned text + right product image",
            },
        }

    @staticmethod
    def _lifestyle_setting(category: str) -> str:
        settings = {
            "electronics": "modern desk setup with laptop and coffee",
            "fitness": "bright home gym or outdoor morning scene",
            "beauty": "marble vanity with soft natural light",
            "home": "cozy living room with warm lighting",
            "fashion": "urban street or minimalist studio",
            "food": "rustic wooden table with fresh ingredients",
        }
        return settings.get(category, "clean lifestyle setting")

    @staticmethod
    def _generate_hashtags(name: str, category: str) -> list[str]:
        base = ["#shopify", "#ecommerce", "#shoponline"]
        cat_tags = {
            "electronics": ["#tech", "#gadgets", "#newtech"],
            "fitness": ["#fitness", "#workout", "#fitlife"],
            "beauty": ["#beauty", "#skincare", "#selfcare"],
            "home": ["#homedecor", "#homedesign", "#interiors"],
            "fashion": ["#fashion", "#style", "#ootd"],
        }
        return base + cat_tags.get(category, ["#trending", "#musthave"]) + [f"#{name.lower().replace(' ', '')}"]
