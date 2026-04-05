"""Tool Orchestrator — discovers, manages, and routes to external tools.

Like a Shopify App Store but for AI — dynamically uses the best tool
for each task.

Tools: Shopify, Google Ads, Meta Ads, TikTok, Email, SMS, CRM,
       Analytics, Image Gen, Browser, Payment, Workflow, Cloud AI
"""
from __future__ import annotations
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("tools.orchestrator")


TOOL_REGISTRY = {
    "shopify": {
        "module": "tools.adapters.shopify",
        "capabilities": ["product_crud", "order_management", "inventory", "collections", "discounts"],
        "category": "commerce",
        "priority": 1,
    },
    "google_ads": {
        "module": "tools.adapters.google_ads",
        "capabilities": ["search_ads", "shopping_ads", "remarketing", "keyword_research"],
        "category": "advertising",
        "priority": 2,
    },
    "meta_ads": {
        "module": "tools.adapters.meta_ads",
        "capabilities": ["facebook_ads", "instagram_ads", "audience_targeting"],
        "category": "advertising",
        "priority": 2,
    },
    "tiktok_ads": {
        "module": "tools.adapters.tiktok_ads",
        "capabilities": ["video_ads", "hashtag_targeting", "creator_marketplace"],
        "category": "advertising",
        "priority": 3,
    },
    "email_service": {
        "module": "tools.adapters.email_service",
        "capabilities": ["send_email", "email_sequence", "newsletter", "transactional"],
        "category": "communication",
        "priority": 1,
    },
    "sms": {
        "module": "tools.adapters.sms",
        "capabilities": ["send_sms", "sms_campaign", "otp"],
        "category": "communication",
        "priority": 2,
    },
    "analytics": {
        "module": "tools.adapters.analytics",
        "capabilities": ["pageviews", "conversion_tracking", "funnel_analysis", "cohort"],
        "category": "analytics",
        "priority": 1,
    },
    "crm": {
        "module": "tools.adapters.crm",
        "capabilities": ["customer_profiles", "lead_scoring", "pipeline", "segments"],
        "category": "customer",
        "priority": 2,
    },
    "image_generation": {
        "module": "tools.adapters.image_generation",
        "capabilities": ["product_images", "banners", "social_media_images"],
        "category": "content",
        "priority": 2,
    },
    "browser_automation": {
        "module": "tools.adapters.browser_automation",
        "capabilities": ["scrape", "screenshot", "form_fill", "price_check"],
        "category": "research",
        "priority": 3,
    },
    "payment": {
        "module": "tools.adapters.payment",
        "capabilities": ["process_payment", "refund", "subscription"],
        "category": "finance",
        "priority": 2,
    },
    "workflow_automation": {
        "module": "tools.adapters.workflow_automation",
        "capabilities": ["trigger", "schedule", "chain", "parallel"],
        "category": "automation",
        "priority": 1,
    },
    "cloud_ai": {
        "module": "tools.adapters.cloud_ai",
        "capabilities": ["nlp", "vision", "translation", "sentiment"],
        "category": "ai",
        "priority": 2,
    },
}


class ToolOrchestrator:
    """Discovers and routes tasks to the best available tool."""

    def __init__(self) -> None:
        self._available: dict[str, bool] = {}
        self._usage_log: list[dict] = []

    def discover(self) -> dict[str, Any]:
        """Discover which tools are available."""
        for name, info in TOOL_REGISTRY.items():
            try:
                __import__(info["module"])
                self._available[name] = True
            except ImportError:
                self._available[name] = False
        available = sum(1 for v in self._available.values() if v)
        return {
            "total_tools": len(TOOL_REGISTRY),
            "available": available,
            "tools": {k: v for k, v in self._available.items()},
        }

    def find_tool(self, capability: str) -> str | None:
        """Find the best tool for a capability."""
        candidates = []
        for name, info in TOOL_REGISTRY.items():
            if capability in info["capabilities"]:
                candidates.append((name, info["priority"]))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[1])
        # Prefer available tools
        for name, _ in candidates:
            if self._available.get(name, False):
                return name
        return candidates[0][0]  # Return best even if not confirmed available

    def use_tool(self, tool_name: str, action: str,
                 params: dict) -> dict[str, Any]:
        """Use a specific tool for an action."""
        if tool_name not in TOOL_REGISTRY:
            return {"error": "unknown_tool", "tool": tool_name}

        info = TOOL_REGISTRY[tool_name]
        start = time.monotonic()

        try:
            module = __import__(info["module"], fromlist=["*"])
            # Try to find and call the action
            func = getattr(module, action, None)
            if func and callable(func):
                result = func(**params)
            else:
                result = {"status": "action_not_found", "available": dir(module)[:10]}

            elapsed = time.monotonic() - start
            log_entry = {
                "tool": tool_name,
                "action": action,
                "success": True,
                "duration_s": round(elapsed, 3),
                "timestamp": time.time(),
            }
            self._usage_log.append(log_entry)
            self._record_usage(tool_name, action, True)
            return {"result": result, "tool": tool_name, "success": True}

        except Exception as exc:
            self._record_usage(tool_name, action, False)
            return {"error": str(exc)[:100], "tool": tool_name, "success": False}

    def execute_capability(self, capability: str,
                           params: dict) -> dict[str, Any]:
        """Find best tool for a capability and execute."""
        tool = self.find_tool(capability)
        if not tool:
            return {"error": "no_tool_for_capability", "capability": capability}
        return self.use_tool(tool, capability, params)

    def get_capabilities(self) -> dict[str, list[str]]:
        """List all available capabilities grouped by category."""
        caps: dict[str, list] = {}
        for name, info in TOOL_REGISTRY.items():
            cat = info["category"]
            for cap in info["capabilities"]:
                caps.setdefault(cat, []).append("{}.{}".format(name, cap))
        return caps

    @staticmethod
    def _record_usage(tool: str, action: str, success: bool):
        try:
            from core.data.architecture import get_data_architecture
            da = get_data_architecture()
            da.capture("tool_usage", {
                "tool_name": tool,
                "engine_name": action,
                "success": success,
            }, source="tool_orchestrator", score=4.0 if success else 2.0)
        except Exception:
            pass

    def get_stats(self) -> dict[str, Any]:
        return {
            "tools_registered": len(TOOL_REGISTRY),
            "tools_available": sum(1 for v in self._available.values() if v),
            "total_uses": len(self._usage_log),
            "capabilities": sum(len(i["capabilities"]) for i in TOOL_REGISTRY.values()),
        }


_instance = None
def get_tool_orchestrator():
    global _instance
    if _instance is None:
        _instance = ToolOrchestrator()
    return _instance
