"""ingestion — API connectors, web scrapers, and file loaders."""
from .api.shopify_api import ShopifyAPI
from .api.ads_api import AdsAPI
from .api.analytics_api import AnalyticsAPI
from .scraping.scraper import Scraper
from .scraping.crawler import Crawler
from .file_loader.csv_loader import CSVLoader
from .file_loader.json_loader import JSONLoader

__all__ = [
    "ShopifyAPI",
    "AdsAPI",
    "AnalyticsAPI",
    "Scraper",
    "Crawler",
    "CSVLoader",
    "JSONLoader",
]
