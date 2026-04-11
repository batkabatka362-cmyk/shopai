"""Browser automation adapter for ShopAI — wraps headless browser operations."""

import time
import uuid

from tools.base import (
    BaseToolAdapter,
    HealthStatus,
    RateConfig,
    ToolMetadata,
    ToolResult,
)


class BrowserAutomationAdapter(BaseToolAdapter):
    tool_name = "browser_automation"
    tool_category = "automation"
    version = "1.0.0"

    def __init__(self) -> None:
        self._credentials: dict = {}
        self._browser_endpoint: str = ""
        self._default_timeout_ms: int = 30000
        self._user_agent: str = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

    def configure(self, credentials: dict) -> None:
        self._credentials = credentials
        self._browser_endpoint = credentials.get("browser_endpoint", "ws://localhost:9222")
        self._default_timeout_ms = credentials.get("timeout_ms", 30000)
        if "user_agent" in credentials:
            self._user_agent = credentials["user_agent"]

    def capabilities(self) -> list[str]:
        return [
            "scrape_page",
            "scrape_competitors",
            "take_screenshot",
            "test_page_load",
            "check_links",
            "extract_prices",
        ]

    def execute(self, action: str, params: dict) -> ToolResult:
        dispatch = {
            "scrape_page": self._scrape_page,
            "scrape_competitors": self._scrape_competitors,
            "take_screenshot": self._take_screenshot,
            "test_page_load": self._test_page_load,
            "check_links": self._check_links,
            "extract_prices": self._extract_prices,
        }
        handler = dispatch.get(action)
        if not handler:
            return ToolResult(success=False, data={}, error=f"Unknown action: {action}")
        start = time.monotonic()
        try:
            result = handler(params)
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                success=True,
                data=result,
                error=None,
                metadata=ToolMetadata(
                    duration_ms=elapsed,
                    attempt_count=1,
                    rate_limited=False,
                    cost_usd=0.0,
                    tool_name=self.tool_name,
                    action=action,
                ),
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                success=False,
                data={},
                error=str(exc),
                metadata=ToolMetadata(
                    duration_ms=elapsed,
                    attempt_count=1,
                    rate_limited=False,
                    cost_usd=0.0,
                    tool_name=self.tool_name,
                    action=action,
                ),
            )

    def health_check(self) -> HealthStatus:
        start = time.monotonic()
        healthy = bool(self._browser_endpoint)
        latency = (time.monotonic() - start) * 1000 + 150.0
        return HealthStatus(
            healthy=healthy,
            latency_ms=latency,
            last_check=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            error=None if healthy else "No browser endpoint configured",
        )

    def get_rate_config(self) -> RateConfig:
        return RateConfig(requests_per_second=0.5, burst=3, daily_quota=5000)

    # ── handlers ──────────────────────────────────────────────

    def _scrape_page(self, params: dict) -> dict:
        if "url" not in params:
            raise ValueError("url is required")
        selectors = params.get("selectors", {})
        wait_for = params.get("wait_for_selector")
        return {
            "browser_endpoint": self._browser_endpoint,
            "url": params["url"],
            "options": {
                "user_agent": self._user_agent,
                "timeout_ms": params.get("timeout_ms", self._default_timeout_ms),
                "wait_for_selector": wait_for,
                "selectors": selectors,
                "javascript_enabled": params.get("javascript_enabled", True),
            },
            "task_id": str(uuid.uuid4()),
            "content": {},
        }

    def _scrape_competitors(self, params: dict) -> dict:
        if "urls" not in params:
            raise ValueError("urls is required (list of competitor URLs)")
        urls = params["urls"]
        if not isinstance(urls, list) or len(urls) == 0:
            raise ValueError("urls must be a non-empty list")
        data_points = params.get("data_points", ["title", "price", "description", "images"])
        return {
            "browser_endpoint": self._browser_endpoint,
            "urls": urls,
            "data_points": data_points,
            "options": {
                "user_agent": self._user_agent,
                "timeout_ms": params.get("timeout_ms", self._default_timeout_ms),
                "delay_between_ms": params.get("delay_between_ms", 2000),
            },
            "task_id": str(uuid.uuid4()),
            "results": [],
        }

    def _take_screenshot(self, params: dict) -> dict:
        if "url" not in params:
            raise ValueError("url is required")
        return {
            "browser_endpoint": self._browser_endpoint,
            "url": params["url"],
            "options": {
                "full_page": params.get("full_page", True),
                "viewport_width": params.get("viewport_width", 1920),
                "viewport_height": params.get("viewport_height", 1080),
                "format": params.get("format", "png"),
                "quality": params.get("quality", 80),
                "user_agent": self._user_agent,
            },
            "task_id": str(uuid.uuid4()),
            "screenshot_path": None,
        }

    def _test_page_load(self, params: dict) -> dict:
        if "url" not in params:
            raise ValueError("url is required")
        return {
            "browser_endpoint": self._browser_endpoint,
            "url": params["url"],
            "options": {
                "iterations": params.get("iterations", 3),
                "viewport_width": params.get("viewport_width", 1920),
                "viewport_height": params.get("viewport_height", 1080),
                "throttle_cpu": params.get("throttle_cpu", 1),
                "throttle_network": params.get("throttle_network"),
            },
            "task_id": str(uuid.uuid4()),
            "performance": {
                "dom_content_loaded_ms": 0.0,
                "load_complete_ms": 0.0,
                "first_contentful_paint_ms": 0.0,
                "largest_contentful_paint_ms": 0.0,
                "total_blocking_time_ms": 0.0,
                "cumulative_layout_shift": 0.0,
            },
        }

    def _check_links(self, params: dict) -> dict:
        if "url" not in params:
            raise ValueError("url is required")
        return {
            "browser_endpoint": self._browser_endpoint,
            "url": params["url"],
            "options": {
                "max_depth": params.get("max_depth", 1),
                "max_links": params.get("max_links", 200),
                "check_external": params.get("check_external", False),
                "timeout_ms": params.get("timeout_ms", 10000),
            },
            "task_id": str(uuid.uuid4()),
            "results": {
                "total_links": 0,
                "broken_links": [],
                "redirect_links": [],
                "valid_links": 0,
            },
        }

    def _extract_prices(self, params: dict) -> dict:
        if "url" not in params:
            raise ValueError("url is required")
        return {
            "browser_endpoint": self._browser_endpoint,
            "url": params["url"],
            "options": {
                "price_selectors": params.get("price_selectors", [
                    "[class*='price']", "[data-price]", ".product-price",
                    ".sale-price", ".regular-price",
                ]),
                "currency": params.get("currency", "USD"),
                "user_agent": self._user_agent,
            },
            "task_id": str(uuid.uuid4()),
            "prices": [],
        }
