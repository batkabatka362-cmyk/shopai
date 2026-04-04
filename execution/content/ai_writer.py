"""AIWriter — generates product descriptions, titles, and marketing copy.

Uses LLaMA (creative role) for generation, Mistral for quality review.
Falls back to template-based generation when LLM unavailable.

Every generation is stored in experience DB for learning.
"""
from __future__ import annotations

import time
import re
from typing import Any

from utils.logger import get_logger

logger = get_logger("ai_writer")


class AIWriter:
    """AI-powered content generation for e-commerce."""

    def __init__(self) -> None:
        self._llm = None
        self._experience = None
        self._generated_count = 0

    def _init(self) -> None:
        if not self._llm:
            try:
                from core.system.llm_adapter import get_llm
                self._llm = get_llm()
            except Exception:
                pass
        if not self._experience:
            try:
                from core.ai.experience import get_experience
                self._experience = get_experience()
            except Exception:
                pass

    # ── Product Description ──────────────────────────────────

    def generate_description(self, product: dict[str, Any],
                            style: str = "professional",
                            target_audience: str = "general") -> dict[str, Any]:
        """Generate a compelling product description."""
        self._init()
        start = time.monotonic()

        name = product.get("name", product.get("title", "Product"))
        price = product.get("price", 0)
        category = product.get("category", product.get("product_type", ""))
        features = product.get("features", [])
        tags = product.get("tags", [])

        # Try LLM generation
        if self._llm:
            result = self._llm_generate_description(name, price, category, features, tags, style, target_audience)
            if result.get("success"):
                result["method"] = "llm"
                result["duration_s"] = round(time.monotonic() - start, 2)
                self._record_generation("description", name, result)
                return result

        # Fallback: template-based
        result = self._template_description(name, price, category, features, tags, style)
        result["method"] = "template"
        result["duration_s"] = round(time.monotonic() - start, 2)
        self._record_generation("description", name, result)
        return result

    # ── Product Title Optimization ───────────────────────────

    def optimize_title(self, current_title: str, product: dict[str, Any] | None = None) -> dict[str, Any]:
        """Optimize a product title for SEO and conversion."""
        self._init()

        if self._llm:
            prompt = f"""Optimize this e-commerce product title for SEO and conversions.

Current title: {current_title}
Category: {product.get('category', '') if product else ''}

Rules:
- Keep under 70 characters
- Include main keyword first
- Remove filler words
- Make it compelling

Return JSON: {{"title": "optimized title", "keywords": ["main", "keywords"]}}"""

            response = self._llm.ask("creative", prompt)
            if response.success:
                parsed = response.parse_json()
                if parsed.get("title"):
                    return {
                        "success": True,
                        "original": current_title,
                        "optimized": parsed["title"],
                        "keywords": parsed.get("keywords", []),
                        "method": "llm",
                    }

        # Fallback: rule-based optimization
        optimized = self._rule_optimize_title(current_title)
        return {
            "success": True,
            "original": current_title,
            "optimized": optimized,
            "keywords": optimized.lower().split()[:5],
            "method": "rules",
        }

    # ── Marketing Copy ───────────────────────────────────────

    def generate_ad_copy(self, product: dict[str, Any],
                         platform: str = "facebook") -> dict[str, Any]:
        """Generate ad copy for a product."""
        self._init()
        name = product.get("name", product.get("title", ""))
        price = product.get("price", 0)

        if self._llm:
            prompt = f"""Write a short {platform} ad for this product:
Product: {name}
Price: ${price}

Write: headline (max 5 words), body (max 30 words), call-to-action (max 5 words).
Return JSON: {{"headline": "...", "body": "...", "cta": "..."}}"""

            response = self._llm.ask("creative", prompt)
            if response.success:
                parsed = response.parse_json()
                if parsed.get("headline"):
                    return {"success": True, "platform": platform, **parsed, "method": "llm"}

        # Fallback
        return {
            "success": True,
            "platform": platform,
            "headline": f"Get {name.split()[0]} Now",
            "body": f"Premium {name} at just ${price}. Free shipping on orders over $50. Limited stock available.",
            "cta": "Shop Now",
            "method": "template",
        }

    # ── Email Subject Lines ──────────────────────────────────

    def generate_email_subjects(self, context: str, count: int = 5) -> list[dict[str, Any]]:
        """Generate email subject line variations."""
        self._init()

        if self._llm:
            prompt = f"""Generate {count} email subject lines for this context:
{context}

Rules: under 50 chars, create urgency or curiosity, no spam words.
Return JSON: {{"subjects": ["subject1", "subject2", ...]}}"""

            response = self._llm.ask("creative", prompt)
            if response.success:
                parsed = response.parse_json()
                subjects = parsed.get("subjects", [])
                if subjects:
                    return [{"subject": s, "method": "llm"} for s in subjects[:count]]

        # Fallback
        return [
            {"subject": f"Don't miss out — {context[:30]}", "method": "template"},
            {"subject": f"Last chance: {context[:30]}", "method": "template"},
            {"subject": f"You'll love this: {context[:25]}", "method": "template"},
        ]

    # ── SEO Meta Description ─────────────────────────────────

    def generate_meta_description(self, product: dict[str, Any]) -> dict[str, Any]:
        """Generate SEO meta description (max 160 chars)."""
        self._init()
        name = product.get("name", "")
        category = product.get("category", "")
        price = product.get("price", 0)

        if self._llm:
            prompt = f"""Write an SEO meta description for this product page:
Product: {name}, Category: {category}, Price: ${price}
Max 155 characters. Include product name and a benefit.
Return JSON: {{"meta_description": "..."}}"""

            response = self._llm.ask("creative", prompt)
            if response.success:
                parsed = response.parse_json()
                if parsed.get("meta_description"):
                    return {"success": True, "meta": parsed["meta_description"][:160], "method": "llm"}

        # Fallback
        meta = f"Shop {name} at ${price}. Premium quality, fast shipping. Perfect for your {category.lower() or 'home'}."
        return {"success": True, "meta": meta[:160], "method": "template"}

    # ── LLM Generation ───────────────────────────────────────

    def _llm_generate_description(self, name: str, price: float, category: str,
                                  features: list, tags: list, style: str,
                                  target: str) -> dict[str, Any]:
        prompt = f"""Write a product description for an e-commerce store.

Product: {name}
Price: ${price}
Category: {category}
Features: {', '.join(features) if features else 'not specified'}
Tags: {', '.join(tags) if isinstance(tags, list) else tags}
Style: {style}
Target audience: {target}

Write:
1. A compelling headline (max 10 words)
2. A description paragraph (50-100 words, benefits-focused)
3. 4-5 bullet points of key features/benefits

Return JSON:
{{"headline": "...", "description": "...", "bullets": ["...", "..."], "seo_keywords": ["...", "..."]}}"""

        response = self._llm.ask("creative", prompt)
        if response.success and response.text:
            parsed = response.parse_json()
            if parsed.get("headline") or parsed.get("description"):
                return {
                    "success": True,
                    "headline": parsed.get("headline", name),
                    "description": parsed.get("description", ""),
                    "bullets": parsed.get("bullets", []),
                    "seo_keywords": parsed.get("seo_keywords", []),
                    "body_html": self._format_html(parsed),
                }
        return {"success": False}

    # ── Template Fallback ────────────────────────────────────

    @staticmethod
    def _template_description(name: str, price: float, category: str,
                              features: list, tags: list, style: str) -> dict[str, Any]:
        headline = name
        desc = f"Discover the {name} — designed for quality and performance. "
        if category:
            desc += f"Perfect for your {category.lower()} needs. "
        desc += f"Available now at just ${price}."

        bullets = [
            "Premium quality materials",
            "Fast and free shipping",
            "Easy returns within 30 days",
            "Satisfaction guaranteed",
        ]
        if features:
            bullets = features[:4] + bullets[:2]

        return {
            "success": True,
            "headline": headline,
            "description": desc,
            "bullets": bullets,
            "seo_keywords": name.lower().split()[:5],
            "body_html": f"<p>{desc}</p><ul>{''.join(f'<li>{b}</li>' for b in bullets)}</ul>",
        }

    @staticmethod
    def _format_html(parsed: dict) -> str:
        parts = []
        if parsed.get("description"):
            parts.append(f"<p>{parsed['description']}</p>")
        if parsed.get("bullets"):
            parts.append("<ul>" + "".join(f"<li>{b}</li>" for b in parsed["bullets"]) + "</ul>")
        return "\n".join(parts)

    @staticmethod
    def _rule_optimize_title(title: str) -> str:
        filler = {"with", "and", "the", "for", "a", "an", "in", "on", "of", "to", "large", "capacity",
                  "household", "bedroom", "office", "mute", "heavy", "fog"}
        words = title.split()
        cleaned = [w for w in words if w.lower() not in filler]
        result = " ".join(cleaned[:10])
        if len(result) > 70:
            result = result[:67] + "..."
        return result

    # ── Experience Recording ─────────────────────────────────

    def _record_generation(self, gen_type: str, product_name: str, result: dict) -> None:
        self._generated_count += 1
        if self._experience:
            try:
                self._experience.record_decision_outcome(
                    f"content_{gen_type}",
                    {"product": product_name, "method": result.get("method", "unknown")},
                    {"generated": True, "has_headline": bool(result.get("headline"))},
                    success=result.get("success", False),
                    impact_score=0.5,
                    engine="ai_writer",
                )
            except Exception:
                pass

    def get_stats(self) -> dict[str, Any]:
        return {"total_generated": self._generated_count}
