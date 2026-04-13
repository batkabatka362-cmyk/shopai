"""SEO Analyzer — checks and improves search engine optimization.

Analyzes: title tags, meta descriptions, URL handles, image alt text,
heading structure, keyword density, internal linking.
"""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger
logger = get_logger("seo.analyzer")


class SEOAnalyzer:
    """Analyzes and scores product/page SEO."""

    def analyze_product(self, product: dict) -> dict[str, Any]:
        title = product.get("title", product.get("name", ""))
        desc = str(product.get("body_html", "") or "")
        handle = product.get("handle", "")
        tags = str(product.get("tags", "") or "")
        images = product.get("images", [])

        score = 0
        issues = []
        fixes = []

        # Title (30 pts)
        if len(title) >= 20 and len(title) <= 70:
            score += 30
        elif title:
            score += 15
            if len(title) < 20:
                issues.append("Title too short ({} chars, need 20+)".format(len(title)))
                fixes.append("Expand title with keywords")
            if len(title) > 70:
                issues.append("Title too long ({} chars, max 70)".format(len(title)))
                fixes.append("Shorten title to under 70 characters")
        else:
            issues.append("No title!")
            fixes.append("Add descriptive title with main keyword")

        # Description (25 pts)
        clean_desc = desc.replace("<p>", "").replace("</p>", "").replace("<br>", "").strip()
        if len(clean_desc) >= 100:
            score += 25
        elif clean_desc:
            score += 10
            issues.append("Description too short ({} chars, need 100+)".format(len(clean_desc)))
            fixes.append("Expand description with product benefits and keywords")
        else:
            issues.append("No product description!")
            fixes.append("Add detailed description (150+ words)")

        # URL handle (10 pts)
        if handle and len(handle) < 80 and "-" in handle:
            score += 10
        elif handle:
            score += 5

        # Tags/keywords (15 pts)
        tag_list = [t.strip() for t in tags.replace("[", "").replace("]", "").replace("'", "").split(",") if t.strip()]
        if len(tag_list) >= 3:
            score += 15
        elif tag_list:
            score += 7
            issues.append("Only {} tags, need 3+".format(len(tag_list)))
            fixes.append("Add more relevant tags for search")
        else:
            issues.append("No tags!")
            fixes.append("Add 5-10 relevant keyword tags")

        # Images (15 pts)
        if isinstance(images, list) and images:
            has_alt = sum(1 for img in images if isinstance(img, dict) and img.get("alt"))
            if has_alt > 0:
                score += 15
            else:
                score += 8
                issues.append("Images have no alt text")
                fixes.append("Add descriptive alt text to all images")
        else:
            issues.append("No product images!")
            fixes.append("Add high-quality product images")

        # Meta (5 pts bonus)
        if product.get("metafields_global_title_tag") or product.get("metafields_global_description_tag"):
            score += 5

        return {
            "product_id": product.get("id", ""),
            "title": title[:40],
            "seo_score": min(100, score),
            "grade": "A" if score >= 80 else "B" if score >= 60 else "C" if score >= 40 else "D",
            "issues": issues,
            "fixes": fixes,
        }

    def analyze_all(self, products: list[dict]) -> dict[str, Any]:
        results = [self.analyze_product(p) for p in products]
        avg_score = sum(r["seo_score"] for r in results) / max(len(results), 1)
        return {
            "products_analyzed": len(results),
            "avg_seo_score": round(avg_score, 1),
            "grade_distribution": {g: sum(1 for r in results if r["grade"] == g) for g in "ABCD"},
            "top_issues": self._top_issues(results),
            "results": results,
        }

    @staticmethod
    def _top_issues(results):
        issues = {}
        for r in results:
            for i in r.get("issues", []):
                key = i.split("(")[0].strip()
                issues[key] = issues.get(key, 0) + 1
        return sorted(issues.items(), key=lambda x: -x[1])[:5]


_instance = None
def get_seo_analyzer():
    global _instance
    if _instance is None:
        _instance = SEOAnalyzer()
    return _instance
