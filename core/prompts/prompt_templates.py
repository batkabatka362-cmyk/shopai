"""PromptTemplates — domain-specific prompt templates for each engine category."""
from __future__ import annotations
from typing import Any


class PromptTemplates:
    """Domain-specific prompt templates. Used by PromptBuilder for specialization."""

    TEMPLATES = {
        "product_selection": {
            "analyze": "Evaluate {product_count} products for e-commerce viability. Pre-scored data: avg_score={avg_score}, viable={viable_count}/{total_count}. Criteria: {criteria}. Validate pre-computed scores and identify any the algorithm may have missed.",
            "execute": "Select top products from scored list. Rank by total_score. Apply criteria filters: {criteria}. Generate structured rankings with price_tier, margin_class, and target_audience for each.",
            "enhance": "For each selected product, generate: hook_sentence, unique_selling_proposition, target_audience_description, and suggested_brand_angle.",
            "validate": "Verify: all products have scores 0-10, rankings ordered, no duplicates, margins realistic (5-95%), at least 1 product selected.",
        },
        "pricing": {
            "analyze": "Analyze pricing across {product_count} products. Price range: ${price_min}-${price_max}. Avg margin: {margin_avg}%. Identify pricing opportunities and risks.",
            "execute": "Generate pricing recommendations: target prices for 40% and 50% margin, discount eligibility, bundle opportunities. Include competitive positioning.",
            "enhance": "Add pricing psychology: anchor prices, charm pricing ($X.99), bundle savings messaging, urgency triggers.",
            "validate": "Verify: all prices positive, margins between 5-95%, no price below cost, discount percentages valid.",
        },
        "customer_segmentation": {
            "analyze": "Segment {customer_count} customers by RFM. Churn rate: {churn_rate}%. Repeat rate: {repeat_rate}%. Identify high-value and at-risk segments.",
            "execute": "Generate segment definitions with criteria, personalization rules per segment, and retention strategies. Include: champions, loyal, potential, at_risk, lost.",
            "enhance": "Add segment personas: name, description, preferred channels, messaging tone, offer sensitivity.",
            "validate": "Verify: all customers assigned to exactly one segment, no overlap, segment sizes sum to total.",
        },
        "inventory": {
            "analyze": "Analyze inventory health: {total_skus} SKUs, {zero_stock} OOS, {stockout_risks} at risk. Classify by ABC method.",
            "execute": "Generate reorder recommendations: EOQ, safety stock, reorder points. Prioritize by stockout risk and revenue impact.",
            "validate": "Verify: all quantities non-negative, reorder points above zero for active items, EOQ calculations valid.",
        },
        "seo": {
            "analyze": "Audit SEO: {keyword_count} keywords analyzed, {issue_count} on-page issues found ({high_severity} high). Score each keyword by opportunity.",
            "execute": "Generate SEO strategy: primary/secondary/long-tail keywords, content clusters, meta recommendations, technical fixes.",
            "validate": "Verify: title length 30-60 chars, meta description 120-160 chars, all images have alt text, no duplicate content.",
        },
    }

    @classmethod
    def get(cls, engine_name: str, step_name: str) -> str | None:
        """Get template for engine + step. Returns None if no match."""
        engine_templates = cls.TEMPLATES.get(engine_name)
        if engine_templates is None:
            return None
        return engine_templates.get(step_name)

    @classmethod
    def render(cls, engine_name: str, step_name: str, data: dict[str, Any]) -> str | None:
        """Render template with data. Returns None if no match."""
        template = cls.get(engine_name, step_name)
        if template is None:
            return None
        try:
            return template.format(**data)
        except KeyError:
            return template + "\n\nData: " + str({k: v for k, v in data.items() if not k.startswith("_")})[:500]

    @classmethod
    def list_engines(cls) -> list[str]:
        return sorted(cls.TEMPLATES.keys())
