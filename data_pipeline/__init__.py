"""data_pipeline — unified ingestion, processing, and feature engineering for ShopAI."""
from .pipelines.product_pipeline import ProductPipeline
from .pipelines.marketing_pipeline import MarketingPipeline
from .pipelines.analytics_pipeline import AnalyticsPipeline

__all__ = ["ProductPipeline", "MarketingPipeline", "AnalyticsPipeline"]
