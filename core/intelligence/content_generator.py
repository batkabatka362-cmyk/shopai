"""ContentGenerator — generates real, usable e-commerce copy.

Not templates with {placeholders} — actual formatted copy ready to use.
Works WITHOUT LLM by using rule-based generation with product attributes.
When LLM is available, uses it for enhanced creative output via the
`*_with_llm()` variants that wrap the deterministic generators with
an LLM rewrite layer.
"""
from __future__ import annotations

import random
from typing import Any, Optional


# Copywriting formulas
HEADLINE_FORMULAS = [
    "{benefit} {product} — {differentiator}",
    "The {adjective} {product} That {benefit_verb}",
    "{number} Reasons {audience} Love Our {product}",
    "Finally, a {product} That Actually {benefit_verb}",
    "Meet Your New Favorite {product}",
    "Say Goodbye to {pain_point} with {product}",
    "{product}: {benefit} Without {objection}",
]

BENEFIT_VERBS = ["Delivers Results", "Saves You Time", "Works Every Time", "Lasts Forever",
                  "Fits Perfectly", "Feels Amazing", "Changes Everything"]

ADJECTIVES = ["Premium", "Ultimate", "Essential", "Smart", "Revolutionary", "Professional", "Everyday"]

PAIN_POINTS = {
    "electronics": ["tangled wires", "dead batteries", "poor sound quality", "bulky designs"],
    "fitness": ["boring workouts", "uncomfortable gear", "wasted gym time", "weak results"],
    "home": ["cluttered spaces", "dim lighting", "cheap furniture", "wasted energy"],
    "accessories": ["cracked screens", "lost items", "boring style", "poor protection"],
    "beauty": ["dry skin", "dull hair", "breakouts", "aging signs"],
}

CTA_OPTIONS = ["Shop Now", "Add to Cart", "Get Yours", "Buy Now", "Order Today",
               "Claim Your Discount", "Start Shopping", "See Details"]


class ContentGenerator:
    """Generates real, formatted e-commerce copy from product data."""

    def __init__(self, *, llm: Any = None) -> None:
        self._llm = llm

    def product_description(
        self,
        product: dict[str, Any],
        tone: str = "professional",
        *,
        use_geo_sandwich: bool = False,
    ) -> dict[str, Any]:
        """Generate a complete product description with headline, body, bullets, SEO.

        Setting ``use_geo_sandwich=True`` enables Wave E-2 GEO
        quote-sandwich augmentation: when ``product["citations"]``
        is a non-empty list of ``{claim, quote, source_name, …}``
        dicts, each entry is wrapped via
        :func:`execution.seo.quote_sandwich.wrap_claim` and the
        resulting HTML is appended to ``body_html`` and returned
        on a new ``geo_sandwiches`` key. Missing / malformed
        citations are skipped — no fake content is generated.
        """
        name = product.get("name", product.get("title", "Product"))
        price = float(product.get("price", 0))
        category = product.get("category", product.get("type", "")).lower()
        features = product.get("features", [])
        benefits = product.get("benefits", [])

        if not features:
            features = self._infer_features(product)
        if not benefits:
            benefits = self._features_to_benefits(features)

        headline = self._generate_headline(name, category, benefits)
        body = self._generate_body(name, category, features, benefits, tone)
        bullets = self._generate_bullets(features, benefits)
        seo_desc = self._generate_meta_description(name, benefits, price)

        # GEO quote-sandwich augmentation (opt-in).
        # Lazy import to avoid paying the cost for every
        # description generation when the flag is off.
        geo_sandwiches: list[dict[str, Any]] = []
        body_html = ""
        if use_geo_sandwich:
            raw_citations = product.get("citations") or []
            if (
                isinstance(raw_citations, list)
                and raw_citations
            ):
                try:
                    from execution.seo.quote_sandwich import (
                        wrap_many,
                    )
                    sandwiches = wrap_many(raw_citations)
                except Exception:  # noqa: BLE001
                    sandwiches = []
                if sandwiches:
                    geo_sandwiches = [
                        s.as_dict() for s in sandwiches
                    ]
                    body_html = "\n".join(
                        s.get("html", "")
                        for s in geo_sandwiches
                        if s.get("html")
                    )

        out: dict[str, Any] = {
            "headline": headline,
            "subheadline": self._generate_subheadline(name, benefits),
            "body": body,
            "bullet_points": bullets,
            "meta_description": seo_desc,
            "meta_title": f"{name} — {benefits[0] if benefits else 'Shop Now'} | Free Shipping",
            "cta_primary": random.choice(CTA_OPTIONS[:3]),
            "cta_secondary": "Learn More",
            "social_proof": self._generate_social_proof(product),
            "urgency_element": self._generate_urgency(product),
            "word_count": len(body.split()),
            "tone": tone,
        }
        if geo_sandwiches:
            out["geo_sandwiches"] = geo_sandwiches
            out["body_html"] = body_html
        return out

    def ad_copy(self, product: dict[str, Any], platform: str = "facebook") -> dict[str, Any]:
        """Generate ad copy for specific platform."""
        name = product.get("name", "Product")
        price = float(product.get("price", 0))
        category = product.get("category", "").lower()
        benefits = product.get("benefits", self._features_to_benefits(self._infer_features(product)))
        discount = product.get("discount", "")

        configs = {
            "facebook": {"headline_max": 40, "body_max": 125, "description_max": 30},
            "google": {"headline_max": 30, "body_max": 90, "description_max": 90},
            "instagram": {"headline_max": 40, "body_max": 2200, "description_max": 0},
            "tiktok": {"headline_max": 34, "body_max": 100, "description_max": 0},
        }
        config = configs.get(platform, configs["facebook"])

        headline = f"{benefits[0][:config['headline_max'] - 5]} ✨" if benefits else name[:config["headline_max"]]

        if discount:
            body = f"🔥 {discount} off {name}! {benefits[0] if benefits else 'Shop now'}. Limited time."
        elif price > 0:
            body = f"Discover {name} — {benefits[0] if benefits else 'premium quality'}. Starting at ${price:.2f}."
        else:
            body = f"Meet {name}. {benefits[0] if benefits else 'Everything you need'}. Shop now →"

        body = body[:config["body_max"]]

        return {
            "platform": platform,
            "headline": headline,
            "body": body,
            "cta": "Shop Now",
            "variants": [
                {"headline": f"New: {name}", "body": f"{benefits[0] if benefits else 'Premium quality'}. Free shipping."},
                {"headline": f"⭐ {name}", "body": f"Join {random.randint(500, 5000)}+ happy customers. {benefits[0] if benefits else ''}"},
                {"headline": f"Last chance: {name}", "body": f"Limited stock. {benefits[0] if benefits else 'Get yours before they sell out'}."},
            ],
        }

    def email_content(self, product: dict[str, Any], email_type: str = "promotional") -> dict[str, Any]:
        """Generate email copy."""
        name = product.get("name", "Product")
        price = float(product.get("price", 0))
        benefits = product.get("benefits", self._features_to_benefits(self._infer_features(product)))

        subjects = {
            "promotional": [
                f"🎉 New: {name} just dropped",
                f"You're going to love this — {name}",
                f"Introducing {name} — {benefits[0] if benefits else 'finally here'}",
            ],
            "abandoned_cart": [
                f"You left {name} behind...",
                f"Still thinking about {name}?",
                f"Your {name} is waiting for you ✨",
            ],
            "post_purchase": [
                f"Tips to get the most from your {name}",
                f"How's your {name}? We'd love to know",
                f"You + {name} = perfect match 💛",
            ],
        }

        subject_options = subjects.get(email_type, subjects["promotional"])

        preview_text = f"{benefits[0] if benefits else 'Premium quality'} — Free shipping on all orders."

        body_sections = [
            {"type": "hero", "headline": f"Meet {name}", "subtext": benefits[0] if benefits else ""},
            {"type": "benefits", "items": benefits[:3]},
        ]
        if price > 0:
            body_sections.append({"type": "price", "amount": f"${price:.2f}", "cta": "Shop Now"})
        body_sections.append({"type": "social_proof", "text": self._generate_social_proof(product).get("text", "")})
        body_sections.append({"type": "cta", "primary": "Shop Now", "secondary": "Learn More"})

        return {
            "email_type": email_type,
            "subject_options": subject_options,
            "preview_text": preview_text,
            "body_sections": body_sections,
            "footer": "Free shipping on orders over $50 | 30-day returns | Secure checkout",
        }

    def blog_outline(self, topic: str, keywords: list[str] | None = None, word_target: int = 1500) -> dict[str, Any]:
        """Generate SEO-optimized blog post outline."""
        kws = keywords or [topic]
        primary_kw = kws[0]

        return {
            "title": f"The Complete Guide to {topic.title()}: Everything You Need to Know in 2024",
            "meta_description": f"Learn everything about {topic}. Expert tips, comparisons, and recommendations. Updated for 2024.",
            "target_keyword": primary_kw,
            "word_target": word_target,
            "outline": [
                {"h2": f"What Is {topic.title()}?", "word_count": 200, "notes": "Define the topic, why it matters"},
                {"h2": f"Why {topic.title()} Matters", "word_count": 250, "notes": "Benefits, statistics, expert quotes"},
                {"h2": f"How to Choose the Best {topic.title()}", "word_count": 300, "notes": "Buying guide, key factors"},
                {"h2": f"Top 5 {topic.title()} Compared", "word_count": 400, "notes": "Comparison table, pros/cons"},
                {"h2": "Expert Tips & Best Practices", "word_count": 200, "notes": "Actionable advice"},
                {"h2": "Frequently Asked Questions", "word_count": 150, "notes": "4-6 FAQs with schema markup"},
            ],
            "internal_links": [f"/collections/{topic.lower().replace(' ', '-')}", f"/blog/{topic.lower().replace(' ', '-')}-guide"],
            "cta": f"Shop our {topic} collection →",
        }

    # --- Private generators ---

    def _generate_headline(self, name: str, category: str, benefits: list[str]) -> str:
        benefit = benefits[0] if benefits else "Premium Quality"
        formula = random.choice(HEADLINE_FORMULAS[:4])
        return formula.format(
            benefit=benefit, product=name, differentiator="Free Shipping",
            adjective=random.choice(ADJECTIVES), benefit_verb=random.choice(BENEFIT_VERBS),
            number=random.choice(["3", "5", "7"]), audience="Customers",
            pain_point=random.choice(PAIN_POINTS.get(category, ["problems"])),
            objection="the high price tag",
        )

    @staticmethod
    def _generate_subheadline(name: str, benefits: list[str]) -> str:
        if len(benefits) >= 2:
            return f"{benefits[0]}. {benefits[1]}. Guaranteed."
        return f"The {name} you've been waiting for."

    def _generate_body(self, name: str, category: str, features: list[str], benefits: list[str], tone: str) -> str:
        opener = f"Introducing the {name} — designed for people who demand the best."
        if tone == "casual":
            opener = f"Meet the {name}. Trust us, you're going to love this."
        elif tone == "luxury":
            opener = f"Crafted with precision and purpose, the {name} represents the pinnacle of {category or 'design'}."

        mid = ""
        if benefits:
            mid = f" With {benefits[0].lower()}, you'll experience the difference from day one."
            if len(benefits) > 1:
                mid += f" Plus, {benefits[1].lower()} means you can focus on what matters."

        closer = " Join thousands of happy customers who've already made the switch."
        cta = f" Order your {name} today and see why everyone's talking about it."

        return opener + mid + closer + cta

    @staticmethod
    def _generate_bullets(features: list[str], benefits: list[str]) -> list[str]:
        bullets = []
        for i, feature in enumerate(features[:5]):
            benefit = benefits[i] if i < len(benefits) else ""
            if benefit:
                bullets.append(f"✓ {feature} — {benefit.lower()}")
            else:
                bullets.append(f"✓ {feature}")
        if not bullets:
            bullets = ["✓ Premium quality materials", "✓ Fast, free shipping", "✓ 30-day money-back guarantee"]
        return bullets

    @staticmethod
    def _generate_meta_description(name: str, benefits: list[str], price: float) -> str:
        benefit_text = benefits[0].lower() if benefits else "premium quality"
        price_text = f" Starting at ${price:.2f}." if price > 0 else ""
        return f"Shop {name} — {benefit_text}.{price_text} Free shipping. 30-day returns. ⭐ 4.8/5 stars."

    @staticmethod
    def _generate_social_proof(product: dict) -> dict[str, Any]:
        rating = float(product.get("rating", 4.7))
        reviews = int(product.get("review_count", random.randint(50, 500)))
        return {
            "text": f"⭐ {rating}/5 based on {reviews} reviews",
            "rating": rating,
            "review_count": reviews,
            "badge": "Bestseller" if reviews > 200 else "Popular Choice" if reviews > 50 else "New Arrival",
        }

    @staticmethod
    def _generate_urgency(product: dict) -> dict[str, str]:
        stock = int(product.get("inventory_quantity", product.get("stock", 50)))
        if stock < 10:
            return {"type": "low_stock", "text": f"Only {stock} left in stock — order soon!"}
        if stock < 30:
            return {"type": "selling_fast", "text": "Selling fast — don't miss out!"}
        return {"type": "free_shipping", "text": "Free shipping on all orders today"}

    @staticmethod
    def _infer_features(product: dict) -> list[str]:
        features = []
        category = product.get("category", "").lower()
        if "weight" in product and float(product.get("weight", 0)) < 0.5:
            features.append("Lightweight design")
        if float(product.get("price", 0)) < 30:
            features.append("Affordable price point")
        if float(product.get("price", 0)) > 100:
            features.append("Premium build quality")
        feat_map = {
            "electronics": ["Advanced technology", "Long battery life", "Compact design"],
            "fitness": ["Durable materials", "Non-slip surface", "Easy to clean"],
            "home": ["Modern design", "Energy efficient", "Easy assembly"],
            "accessories": ["Protective design", "Perfect fit", "Stylish look"],
        }
        features.extend(feat_map.get(category, ["High quality", "Versatile design"]))
        return features[:5]

    @staticmethod
    def _features_to_benefits(features: list[str]) -> list[str]:
        benefit_map = {
            "lightweight": "Easy to carry anywhere",
            "affordable": "Save money without sacrificing quality",
            "premium": "Built to last for years",
            "advanced": "Stay ahead with the latest innovation",
            "battery": "Never worry about running out of power",
            "durable": "Withstands daily wear and tear",
            "modern": "Elevate your space instantly",
            "protective": "Keep your device safe from drops",
            "compact": "Fits perfectly in your bag or pocket",
        }
        benefits = []
        for feature in features:
            fl = feature.lower()
            matched = False
            for keyword, benefit in benefit_map.items():
                if keyword in fl:
                    benefits.append(benefit)
                    matched = True
                    break
            if not matched:
                benefits.append(f"Enjoy {feature.lower()}")
        return benefits[:5]

    # ── LLM-backed wrappers ───────────────────────────────────

    def product_description_with_llm(
        self,
        product: dict[str, Any],
        tone: str = "professional",
    ) -> dict[str, Any]:
        """Generate a product description with an LLM rewrite layer.

        Always runs the deterministic generator first so callers
        get a result. When an LLM is wired, the deterministic
        output is fed to the LLM as a starting point and rewritten
        for richer copy. The final dict carries both versions:

            {
                "heuristic": <rule-based output>,
                "llm": {headline, subheadline, body, bullets,
                        meta_description} or {"error": "..."},
                "source": "llm" | "heuristic_only",
            }
        """
        heuristic = self.product_description(product, tone=tone)
        result: dict[str, Any] = {
            "heuristic": heuristic,
            "llm": None,
            "source": "heuristic_only",
        }

        llm = self._get_llm()
        if llm is None:
            return result
        try:
            if not llm.is_available():
                return result
        except Exception:  # noqa: BLE001
            return result

        try:
            from core.system.prompt_library import get_prompt
        except Exception:  # noqa: BLE001
            return result
        template = get_prompt("content.product_description")
        if template is None:
            return result

        rendered = template.render(
            product_name=product.get("name", product.get("title", "Product")),
            category=product.get("category", product.get("type", "")),
            features=", ".join(product.get("features", []) or self._infer_features(product)),
            tone=tone,
            heuristic_headline=heuristic.get("headline", ""),
            heuristic_body=heuristic.get("body", "")[:400],
        )

        try:
            structured = llm.ask_structured(
                role=template.role,
                prompt=rendered.user,
                system_prompt=rendered.system,
                schema_hint=template.schema_hint,
            )
        except Exception as exc:  # noqa: BLE001
            result["llm"] = {"error": str(exc)[:200]}
            return result

        if not getattr(structured, "ok", False):
            result["llm"] = {"error": structured.error or "unparseable"}
            return result

        data = structured.data or {}
        try:
            result["llm"] = {
                "headline": str(data.get("headline", heuristic.get("headline", ""))),
                "subheadline": str(data.get("subheadline", "")),
                "body": str(data.get("body", "")),
                "bullets": [str(b) for b in (data.get("bullets") or [])][:6],
                "meta_description": str(data.get("meta_description", ""))[:160],
            }
            result["source"] = "llm"
        except (TypeError, ValueError) as exc:
            result["llm"] = {"error": f"normalization failed: {exc}"}
        return result

    def ad_copy_with_llm(
        self,
        product: dict[str, Any],
        platform: str = "facebook",
    ) -> dict[str, Any]:
        """Generate ad copy with an LLM rewrite layer."""
        heuristic = self.ad_copy(product, platform=platform)
        result: dict[str, Any] = {
            "heuristic": heuristic,
            "llm": None,
            "source": "heuristic_only",
        }

        llm = self._get_llm()
        if llm is None:
            return result
        try:
            if not llm.is_available():
                return result
        except Exception:  # noqa: BLE001
            return result

        try:
            from core.system.prompt_library import get_prompt
        except Exception:  # noqa: BLE001
            return result
        template = get_prompt("content.ad_copy")
        if template is None:
            return result

        rendered = template.render(
            product_name=product.get("name", product.get("title", "Product")),
            price=product.get("price", 0),
            platform=platform,
            heuristic_headline=heuristic.get("headline", ""),
            heuristic_body=heuristic.get("body", "")[:300],
        )

        try:
            structured = llm.ask_structured(
                role=template.role,
                prompt=rendered.user,
                system_prompt=rendered.system,
                schema_hint=template.schema_hint,
            )
        except Exception as exc:  # noqa: BLE001
            result["llm"] = {"error": str(exc)[:200]}
            return result

        if not getattr(structured, "ok", False):
            result["llm"] = {"error": structured.error or "unparseable"}
            return result

        data = structured.data or {}
        try:
            result["llm"] = {
                "headline": str(data.get("headline", "")),
                "body": str(data.get("body", "")),
                "cta": str(data.get("cta", "Shop Now")),
                "tags": [str(t) for t in (data.get("tags") or [])][:8],
            }
            result["source"] = "llm"
        except (TypeError, ValueError) as exc:
            result["llm"] = {"error": f"normalization failed: {exc}"}
        return result

    def _get_llm(self) -> Any:
        """Lazily resolve the LLM adapter."""
        if self._llm is not None:
            return self._llm
        try:
            from core.system.llm_adapter import get_llm
            return get_llm()
        except Exception:  # noqa: BLE001
            return None
