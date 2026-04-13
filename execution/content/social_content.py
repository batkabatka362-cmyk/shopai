"""Social Content Generator — creates posts for social media platforms."""
from __future__ import annotations
import hashlib
from typing import Any
from utils.logger import get_logger
logger = get_logger("content.social")


class SocialContentGenerator:
    """Generates platform-specific social media content."""

    def generate_for_product(self, product: dict,
                             platforms: list[str] | None = None) -> dict[str, Any]:
        platforms = platforms or ["instagram", "facebook", "tiktok", "pinterest"]
        name = product.get("title", product.get("name", "Product"))
        price = product.get("price", product.get("variants", [{}])[0].get("price", "0") if product.get("variants") else "0")
        handle = product.get("handle", "")
        category = product.get("product_type", "")

        posts = {}
        for platform in platforms:
            posts[platform] = self._generate(platform, name, price, handle, category)
        return {"product": name[:30], "posts": posts, "platforms": len(posts)}

    def generate_batch(self, products: list[dict],
                       max_products: int = 5) -> dict[str, Any]:
        all_posts = []
        for p in products[:max_products]:
            result = self.generate_for_product(p)
            all_posts.append(result)
        return {"total_products": len(all_posts), "posts": all_posts}

    @staticmethod
    def _generate(platform: str, name: str, price: str,
                  handle: str, category: str) -> dict:
        url = "/products/{}".format(handle) if handle else ""

        if platform == "instagram":
            caption = (
                "NEW IN! {name} \n\n"
                "Perfect for your {cat} needs. Premium quality at just ${price}.\n\n"
                "Shop now - link in bio!\n\n"
                "#shopify #ecommerce #{tag1} #{tag2} #newproduct #musthave"
            ).format(name=name, cat=category.lower() or "everyday",
                     price=price, tag1=name.split()[0].lower(),
                     tag2=category.split()[0].lower() if category else "lifestyle")
            return {"caption": caption, "type": "image_post", "url": url}

        elif platform == "facebook":
            text = (
                "Check out the {name}! \n\n"
                "Now available for just ${price}. "
                "High quality {cat} product that you will love.\n\n"
                "Shop: {{store_url}}{url}"
            ).format(name=name, price=price,
                     cat=category.lower() or "", url=url)
            return {"text": text, "type": "link_post", "url": url}

        elif platform == "tiktok":
            script = (
                "POV: You just found the perfect {name} for only ${price}. "
                "This {cat} product is a game changer! "
                "Link in bio to shop."
            ).format(name=name, price=price,
                     cat=category.lower() or "")
            return {"script": script, "type": "video_script",
                    "hashtags": "#tiktokmademebuyit #shopify #{}".format(
                        name.split()[0].lower())}

        elif platform == "pinterest":
            return {
                "title": "{} - ${} | Shop Now".format(name, price),
                "description": "Discover the {} — premium {} for your everyday life.".format(
                    name, category.lower() or "product"),
                "type": "pin", "url": url,
            }

        return {"text": "Check out {}!".format(name), "type": "generic"}


_instance = None
def get_social_content():
    global _instance
    if _instance is None:
        _instance = SocialContentGenerator()
    return _instance
