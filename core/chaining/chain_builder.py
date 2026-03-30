"""ChainBuilder — fluent API for building engine chains.

Makes it easy to compose multi-engine workflows without modifying engine code.
"""
from __future__ import annotations

from typing import Any, Callable

from .engine_chain import EngineChain, OutputTransform


class ChainBuilder:
    """Fluent builder for EngineChain."""

    def __init__(self, name: str) -> None:
        self._chain = EngineChain(name)

    def then(
        self,
        engine_name: str,
        transform: OutputTransform | None = None,
        required: bool = True,
        description: str = "",
    ) -> "ChainBuilder":
        """Add next engine in the chain."""
        self._chain.add_step(engine_name, transform, required, description)
        return self

    def optional(
        self,
        engine_name: str,
        transform: OutputTransform | None = None,
        description: str = "",
    ) -> "ChainBuilder":
        """Add an optional engine step (failure won't stop chain)."""
        self._chain.add_step(engine_name, transform, required=False, description=description)
        return self

    def build(self) -> EngineChain:
        """Return the built chain."""
        return self._chain

    # Pre-built chains for common workflows
    @classmethod
    def product_launch(cls) -> EngineChain:
        """Product launch chain: research → pricing → content → SEO → campaign."""
        return (
            cls("product_launch")
            .then("market_research", description="Analyze market opportunity")
            .then("competitor_analysis", description="Study competitors")
            .then("pricing", description="Set optimal price")
            .then("product_description", description="Generate product copy")
            .then("seo", description="Optimize for search")
            .then("content_generation", description="Create marketing content")
            .then("email_marketing", description="Prepare launch emails")
            .then("social_media", description="Plan social posts")
            .optional("influencer", description="Find influencer matches")
            .build()
        )

    @classmethod
    def customer_acquisition(cls) -> EngineChain:
        """Customer acquisition chain: targeting → ads → landing → conversion."""
        return (
            cls("customer_acquisition")
            .then("audience_targeting", description="Define target audience")
            .then("ad_copy", description="Generate ad creative")
            .then("landing_page", description="Build landing page")
            .then("ab_testing", description="Set up A/B tests")
            .then("conversion_tracking", description="Track conversions")
            .build()
        )

    @classmethod
    def inventory_restock(cls) -> EngineChain:
        """Inventory restock chain: forecast → supplier → order → track."""
        return (
            cls("inventory_restock")
            .then("demand_forecasting", description="Forecast demand")
            .then("stock_prediction", description="Predict stock needs")
            .then("supplier", description="Select supplier")
            .then("procurement", description="Create purchase order")
            .then("inventory", description="Update inventory records")
            .build()
        )

    @classmethod
    def customer_retention(cls) -> EngineChain:
        """Customer retention chain: analyze → segment → personalize → engage."""
        return (
            cls("customer_retention")
            .then("churn_prediction", description="Predict churn risk")
            .then("customer_segmentation", description="Segment by risk")
            .then("personalization", description="Personalize offers")
            .then("email_marketing", description="Send retention campaign")
            .then("loyalty_program", description="Offer loyalty rewards")
            .build()
        )
