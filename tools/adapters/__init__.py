"""Tool adapters — one per external service."""

from tools.adapters.analytics import AnalyticsAdapter
from tools.adapters.browser_automation import BrowserAutomationAdapter
from tools.adapters.cloud_ai import CloudAIAdapter
from tools.adapters.crm import CRMAdapter
from tools.adapters.email_service import EmailServiceAdapter
from tools.adapters.google_ads import GoogleAdsAdapter
from tools.adapters.image_generation import ImageGenerationAdapter
from tools.adapters.meta_ads import MetaAdsAdapter
from tools.adapters.payment import PaymentAdapter
from tools.adapters.shopify import ShopifyAdapter
from tools.adapters.sms import SMSAdapter
from tools.adapters.tiktok_ads import TikTokAdsAdapter
from tools.adapters.workflow_automation import WorkflowAutomationAdapter

__all__ = [
    "AnalyticsAdapter",
    "BrowserAutomationAdapter",
    "CloudAIAdapter",
    "CRMAdapter",
    "EmailServiceAdapter",
    "GoogleAdsAdapter",
    "ImageGenerationAdapter",
    "MetaAdsAdapter",
    "PaymentAdapter",
    "ShopifyAdapter",
    "SMSAdapter",
    "TikTokAdsAdapter",
    "WorkflowAutomationAdapter",
]
