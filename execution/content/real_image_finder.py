"""Real Image Finder — searches web for actual product images.

Replaces placeholder images with real product photos found via search.
Uses web_search to find images, then uploads to Shopify via product image API.
"""
from __future__ import annotations
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("images.finder")


class RealImageFinder:
    """Find and replace placeholder images with real product photos."""

    def __init__(self) -> None:
        self._found: list[dict] = []

    def find_real_images(self, products: list[dict],
                         max_products: int = 5) -> dict[str, Any]:
        """Search for real product images."""
        results = []
        for p in products[:max_products]:
            name = p.get("title", p.get("name", ""))
            images = p.get("images", [])

            # Check if current image is placeholder
            is_placeholder = False
            if images:
                for img in images:
                    src = img.get("src", "") if isinstance(img, dict) else str(img)
                    if "placehold" in src.lower():
                        is_placeholder = True
                        break

            if not is_placeholder and images:
                continue  # Already has real image

            # Search for real image
            image_url = self._search_product_image(name)
            if image_url:
                results.append({
                    "product_id": str(p.get("id", "")),
                    "name": name[:40],
                    "image_url": image_url,
                    "is_replacement": is_placeholder,
                })
                self._found.append(results[-1])

        return {
            "found": len(results),
            "products_checked": min(len(products), max_products),
            "results": results,
        }

    @staticmethod
    def _search_product_image(product_name: str) -> str:
        """Search web for product image."""
        try:
            from core.ai.external_tools import web_search
            query = "{} product photo transparent background".format(product_name)
            results = web_search(query, max_results=5)
            if results:
                for r in results:
                    if isinstance(r, dict):
                        # Check for image URLs
                        for key in ("thumbnail", "image", "url"):
                            url = r.get(key, "")
                            if url and any(ext in url.lower() for ext in (".jpg", ".png", ".webp")):
                                return url
        except Exception:
            pass
        return ""

    def get_stats(self) -> dict[str, Any]:
        return {"images_found": len(self._found)}


_instance = None
def get_real_image_finder():
    global _instance
    if _instance is None:
        _instance = RealImageFinder()
    return _instance
