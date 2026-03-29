"""ContentLogic — deep logic for content/creative engines."""
from __future__ import annotations
from typing import Any


class ContentLogic:
    CONTENT_ENGINES = {
        "content_generation", "creative_generation", "blog_generation",
        "product_description", "copywriting", "headline_generator",
        "video_marketing", "faq_generation", "translation", "storytelling",
        "brand_voice", "press_release", "case_study",
    }

    def applies_to(self, engine_name: str) -> bool:
        return engine_name in self.CONTENT_ENGINES

    def analyze(self, data: dict[str, Any]) -> dict[str, Any]:
        result = {}
        content = self._get_content(data)
        product = self._get_product(data)

        if content:
            result["content_analysis"] = self._analyze_content(content)
        if product:
            result["product_context"] = self._extract_product_context(product)

        result["tone_config"] = data.get("brand_voice", data.get("tone_config", data.get("tone", "professional")))
        result["target_audience"] = data.get("audience", data.get("target_audience", "general"))
        result["score"] = 7.0
        result["decision"] = "approve"
        result["reason"] = "Content generation ready"
        return result

    def execute(self, data: dict[str, Any]) -> dict[str, Any]:
        result = {}
        product = self._get_product(data)
        brief = data.get("content_brief", data.get("brief", data.get("topic_data", {})))

        if product:
            result["content_elements"] = self._generate_content_elements(product)
        if brief:
            result["content_plan"] = self._plan_content(brief)

        result["seo_elements"] = self._generate_seo_elements(data)
        result["content_checklist"] = [
            "Headline captures attention",
            "Clear value proposition",
            "Social proof included",
            "Call-to-action present",
            "Mobile-friendly formatting",
        ]
        result["generated"] = True
        return result

    def _analyze_content(self, content: str) -> dict:
        words = content.split()
        sentences = content.split(".")
        return {
            "word_count": len(words),
            "sentence_count": len(sentences),
            "avg_sentence_length": round(len(words) / max(len(sentences), 1), 1),
            "readability": "easy" if len(words)/max(len(sentences),1) < 15 else "moderate" if len(words)/max(len(sentences),1) < 25 else "complex",
        }

    def _extract_product_context(self, product: dict) -> dict:
        return {
            "name": product.get("name", product.get("title", "")),
            "price": product.get("price", 0),
            "category": product.get("category", product.get("type", "")),
            "key_features": product.get("features", [])[:5],
            "benefits": product.get("benefits", [])[:5],
        }

    def _generate_content_elements(self, product: dict) -> dict:
        name = product.get("name", product.get("title", "Product"))
        price = product.get("price", 0)
        return {
            "headlines": [
                f"Discover the {name}",
                f"Why Everyone Loves {name}",
                f"Transform Your Day with {name}",
            ],
            "value_props": [
                f"Premium quality at ${price}" if price else "Premium quality",
                "Free shipping on all orders",
                "30-day money-back guarantee",
            ],
            "cta_options": [
                "Shop Now", "Add to Cart", "Get Yours Today", "Learn More",
            ],
        }

    def _plan_content(self, brief: dict) -> dict:
        return {
            "structure": ["Hook", "Problem", "Solution", "Benefits", "Social Proof", "CTA"],
            "word_count_target": 500,
            "tone": brief.get("tone", "professional"),
            "format": brief.get("format", "article"),
        }

    def _generate_seo_elements(self, data: dict) -> dict:
        keywords = data.get("seo_keywords", data.get("keywords", []))
        primary = keywords[0] if isinstance(keywords, list) and keywords else data.get("topic", "product")
        if isinstance(primary, dict):
            primary = primary.get("keyword", "product")
        return {
            "primary_keyword": primary,
            "meta_title_template": f"{primary.title()} | Best {{benefit}} | {{brand}}",
            "meta_description_template": f"Discover {primary} that {{benefit}}. {{social_proof}}. Shop now.",
        }

    @staticmethod
    def _get_content(data: dict) -> str:
        for key in ("content", "text", "body", "description"):
            val = data.get(key, "")
            if isinstance(val, str) and val: return val
        return ""

    @staticmethod
    def _get_product(data: dict) -> dict:
        for key in ("product_data", "product", "products"):
            val = data.get(key)
            if isinstance(val, dict) and val: return val
            if isinstance(val, list) and val and isinstance(val[0], dict): return val[0]
        return {}
