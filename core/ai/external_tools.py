"""ExternalTools — connects ShopAI to free external AI services and data sources.

The AI uses these tools to research, analyze, and make decisions autonomously.
All tools are FREE or use free tiers. No paid API keys required.

Tools:
  - Web search (DuckDuckGo — no API key)
  - Web scraping (urllib — built-in)
  - Google Trends proxy (free)
  - Free AI APIs (Ollama local)
  - Product/market research from public data

Every tool call is logged so the AI learns which tools work best.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from utils.logger import get_logger

logger = get_logger("external_tools")


class ExternalTools:
    """AI's toolkit for interacting with the outside world."""

    def __init__(self) -> None:
        self._call_log: list[dict[str, Any]] = []
        self._tool_stats: dict[str, dict[str, Any]] = {}
        self._user_agent = "ShopAI/1.0 (autonomous e-commerce bot)"

    # ── Web Search (DuckDuckGo — no API key) ─────────────────

    def web_search(self, query: str, max_results: int = 5) -> dict[str, Any]:
        """Search the web using DuckDuckGo instant answer API (free, no key)."""
        start = time.monotonic()
        try:
            encoded = urllib.parse.urlencode({"q": query, "format": "json", "no_html": 1})
            url = f"https://api.duckduckgo.com/?{encoded}"
            data = self._http_get(url)

            results = []
            # Abstract (main answer)
            if data.get("Abstract"):
                results.append({
                    "title": data.get("Heading", ""),
                    "text": data["Abstract"],
                    "url": data.get("AbstractURL", ""),
                    "source": data.get("AbstractSource", ""),
                })

            # Related topics
            for topic in data.get("RelatedTopics", [])[:max_results]:
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append({
                        "title": topic.get("Text", "")[:80],
                        "text": topic.get("Text", ""),
                        "url": topic.get("FirstURL", ""),
                    })

            self._log_call("web_search", True, time.monotonic() - start, {"query": query, "results": len(results)})
            return {"results": results, "total": len(results), "query": query}

        except Exception as exc:
            self._log_call("web_search", False, time.monotonic() - start, {"query": query, "error": str(exc)})
            return {"results": [], "total": 0, "error": str(exc)}

    # ── Web Scraping (extract product/price data) ────────────

    def scrape_page(self, url: str) -> dict[str, Any]:
        """Scrape a web page and extract text content."""
        start = time.monotonic()
        try:
            html = self._http_get_raw(url)
            # Extract text from HTML
            text = self._html_to_text(html)
            title = self._extract_tag(html, "title")
            prices = self._extract_prices(text)
            meta_desc = self._extract_meta(html, "description")

            self._log_call("scrape_page", True, time.monotonic() - start, {"url": url})
            return {
                "url": url,
                "title": title,
                "description": meta_desc,
                "text": text[:2000],
                "prices_found": prices,
                "word_count": len(text.split()),
            }
        except Exception as exc:
            self._log_call("scrape_page", False, time.monotonic() - start, {"url": url, "error": str(exc)})
            return {"url": url, "error": str(exc)}

    # ── Competitor Price Research ─────────────────────────────

    def research_competitor_prices(self, product_name: str) -> dict[str, Any]:
        """Research competitor prices for a product via web search."""
        start = time.monotonic()
        try:
            search_result = self.web_search(f"{product_name} price buy online")
            prices = []

            for result in search_result.get("results", []):
                text = result.get("text", "")
                found_prices = self._extract_prices(text)
                if found_prices:
                    prices.extend([{
                        "price": p,
                        "source": result.get("url", ""),
                        "context": text[:100],
                    } for p in found_prices])

            avg_price = sum(p["price"] for p in prices) / len(prices) if prices else 0

            self._log_call("research_prices", True, time.monotonic() - start, {"product": product_name, "prices_found": len(prices)})
            return {
                "product": product_name,
                "prices": prices[:10],
                "average_price": round(avg_price, 2),
                "price_range": {
                    "min": min(p["price"] for p in prices) if prices else 0,
                    "max": max(p["price"] for p in prices) if prices else 0,
                },
                "data_points": len(prices),
            }
        except Exception as exc:
            self._log_call("research_prices", False, time.monotonic() - start, {"error": str(exc)})
            return {"product": product_name, "prices": [], "error": str(exc)}

    # ── Trend Research ───────────────────────────────────────

    def research_trends(self, keywords: list[str]) -> dict[str, Any]:
        """Research market trends for keywords via web search."""
        start = time.monotonic()
        results = {}

        for keyword in keywords[:5]:
            search = self.web_search(f"{keyword} trend 2026 growing market")
            trend_signals = []
            for r in search.get("results", []):
                text = r.get("text", "").lower()
                if any(w in text for w in ["growing", "trend", "popular", "demand", "rise"]):
                    trend_signals.append("growing")
                elif any(w in text for w in ["declining", "falling", "decrease", "drop"]):
                    trend_signals.append("declining")

            growing = trend_signals.count("growing")
            declining = trend_signals.count("declining")
            results[keyword] = {
                "trend": "growing" if growing > declining else "declining" if declining > growing else "stable",
                "confidence": min(0.9, (growing + declining) * 0.15) if (growing + declining) > 0 else 0.3,
                "signals": len(trend_signals),
            }

        self._log_call("research_trends", True, time.monotonic() - start, {"keywords": len(keywords)})
        return {"trends": results, "keywords_analyzed": len(results)}

    # ── Niche Research ───────────────────────────────────────

    def research_niche(self, niche: str) -> dict[str, Any]:
        """Research a niche for dropshipping potential."""
        start = time.monotonic()

        search = self.web_search(f"best {niche} products to sell online 2026 dropshipping")
        trend = self.research_trends([niche])

        products_mentioned = []
        for r in search.get("results", []):
            text = r.get("text", "")
            # Extract product-like phrases
            words = text.split()
            for i, word in enumerate(words):
                if word.lower() in ("best", "top", "popular", "trending"):
                    context = " ".join(words[max(0, i-2):min(len(words), i+5)])
                    products_mentioned.append(context)

        self._log_call("research_niche", True, time.monotonic() - start, {"niche": niche})
        return {
            "niche": niche,
            "trend": trend.get("trends", {}).get(niche, {"trend": "unknown"}),
            "product_ideas": products_mentioned[:10],
            "search_results": len(search.get("results", [])),
            "recommendation": "promising" if trend.get("trends", {}).get(niche, {}).get("trend") == "growing" else "investigate_more",
        }

    # ── Free AI Analysis (via Ollama) ────────────────────────

    def ai_analyze(self, prompt: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Use local AI (Ollama) for analysis — completely free."""
        try:
            from core.ai.reasoning import ai_reason
            return ai_reason("analysis", prompt=prompt, context_data=data or {})
        except Exception as exc:
            return {"analysis": f"AI analysis unavailable: {exc}", "source": "fallback"}

    # ── HTTP Helpers ─────────────────────────────────────────

    def _http_get(self, url: str, timeout: int = 10) -> dict[str, Any]:
        """GET request returning JSON."""
        req = urllib.request.Request(url, headers={"User-Agent": self._user_agent})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _http_get_raw(self, url: str, timeout: int = 10) -> str:
        """GET request returning raw text."""
        req = urllib.request.Request(url, headers={"User-Agent": self._user_agent})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Strip HTML tags to get plain text."""
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    @staticmethod
    def _extract_tag(html: str, tag: str) -> str:
        """Extract content of first matching HTML tag."""
        match = re.search(f'<{tag}[^>]*>(.*?)</{tag}>', html, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_meta(html: str, name: str) -> str:
        """Extract meta tag content."""
        match = re.search(f'<meta[^>]*name=["\']?{name}["\']?[^>]*content=["\']([^"\']+)', html, re.IGNORECASE)
        return match.group(1) if match else ""

    @staticmethod
    def _extract_prices(text: str) -> list[float]:
        """Extract prices from text."""
        matches = re.findall(r'\$(\d+(?:\.\d{2})?)', text)
        prices = []
        for m in matches:
            try:
                p = float(m)
                if 1 < p < 10000:  # reasonable price range
                    prices.append(p)
            except ValueError:
                pass
        return prices

    # ── Call Logging & Stats ─────────────────────────────────

    def _log_call(self, tool: str, success: bool, duration: float, details: dict) -> None:
        """Log every tool call for learning."""
        entry = {
            "tool": tool,
            "success": success,
            "duration_s": round(duration, 3),
            "timestamp": time.time(),
            "details": details,
        }
        self._call_log.append(entry)
        if len(self._call_log) > 1000:
            self._call_log = self._call_log[-500:]

        # Update stats
        if tool not in self._tool_stats:
            self._tool_stats[tool] = {"calls": 0, "successes": 0, "total_duration": 0}
        stats = self._tool_stats[tool]
        stats["calls"] += 1
        if success:
            stats["successes"] += 1
        stats["total_duration"] += duration
        stats["avg_duration"] = round(stats["total_duration"] / stats["calls"], 3)
        stats["success_rate"] = round(stats["successes"] / stats["calls"], 3)

    def get_tool_stats(self) -> dict[str, Any]:
        """Get performance stats for all tools."""
        return dict(self._tool_stats)

    def get_recent_calls(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._call_log[-limit:]


# Singleton
_tools: ExternalTools | None = None


def get_tools() -> ExternalTools:
    global _tools
    if _tools is None:
        _tools = ExternalTools()
    return _tools
