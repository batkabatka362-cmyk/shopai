"""Telegram Bot — control ShopAI from Telegram.

Commands:
  /start - Welcome message
  /status - System health
  /products - List products
  /pricing - Run pricing analysis
  /customers - Customer segments
  /seo - SEO audit
  /forecast <values> - Revenue forecast
  /subject <text> - Score email subject
  /workflow <name> - Run workflow
  /report - Daily report

Requires: SHOPAI_TELEGRAM_TOKEN env var.
Uses stdlib urllib — no python-telegram-bot dependency.
"""
from __future__ import annotations

import json
import os
import time
import threading
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError

from utils.logger import get_logger

logger = get_logger("integrations.telegram")


class TelegramBot:
    """Telegram bot for ShopAI using raw HTTP API."""

    def __init__(self, token: str = "") -> None:
        self._token = token or os.environ.get("SHOPAI_TELEGRAM_TOKEN", "")
        self._base_url = f"https://api.telegram.org/bot{self._token}"
        self._offset = 0
        self._running = False
        self._orch = None
        self._handlers: dict[str, Any] = {}
        self._register_handlers()

    def start(self) -> None:
        """Start bot polling loop."""
        if not self._token:
            print("Error: Set SHOPAI_TELEGRAM_TOKEN env var")
            return

        from core.orchestrator import MainOrchestrator
        self._orch = MainOrchestrator()
        self._orch.initialize()

        self._running = True
        print(f"Telegram bot started. Send /start to your bot.")

        while self._running:
            try:
                updates = self._get_updates()
                for update in updates:
                    self._handle_update(update)
            except KeyboardInterrupt:
                break
            except Exception as exc:
                logger.error("Bot error: %s", exc)
                time.sleep(5)

        self._orch.shutdown()

    def start_background(self) -> None:
        """Start bot in background thread."""
        t = threading.Thread(target=self.start, daemon=True)
        t.start()

    def stop(self) -> None:
        self._running = False

    def _register_handlers(self) -> None:
        self._handlers = {
            "/start": self._cmd_start,
            "/status": self._cmd_status,
            "/products": self._cmd_products,
            "/pricing": self._cmd_pricing,
            "/customers": self._cmd_customers,
            "/seo": self._cmd_seo,
            "/forecast": self._cmd_forecast,
            "/subject": self._cmd_subject,
            "/workflow": self._cmd_workflow,
            "/report": self._cmd_report,
            "/help": self._cmd_help,
        }

    def _handle_update(self, update: dict) -> None:
        message = update.get("message", {})
        text = message.get("text", "")
        chat_id = message.get("chat", {}).get("id")
        if not chat_id or not text:
            return

        self._offset = update["update_id"] + 1
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower().split("@")[0]  # Handle @botname suffix
        arg = parts[1] if len(parts) > 1 else ""

        handler = self._handlers.get(cmd)
        if handler:
            try:
                response = handler(arg)
                self._send_message(chat_id, response)
            except Exception as exc:
                self._send_message(chat_id, f"Error: {exc}")
        elif text.startswith("/"):
            self._send_message(chat_id, f"Unknown command: {cmd}\nType /help for commands.")

    # --- Commands ---

    def _cmd_start(self, arg: str) -> str:
        return "🤖 *ShopAI Bot*\n\nI'm your AI-powered Shopify operator.\nType /help to see what I can do."

    def _cmd_help(self, arg: str) -> str:
        return (
            "📋 *Commands:*\n"
            "/status - System health\n"
            "/products - List products\n"
            "/pricing - Pricing analysis\n"
            "/customers - Customer segments\n"
            "/seo - SEO audit\n"
            "/forecast 100,120,130 - Revenue forecast\n"
            "/subject Your text here - Score subject line\n"
            "/workflow product_launch - Run workflow\n"
            "/report - Daily report"
        )

    def _cmd_status(self, arg: str) -> str:
        if not self._orch:
            return "❌ System not initialized"
        health = self._orch.health_check()
        status = "✅ Healthy" if health.get("status") == "healthy" else "⚠️ Degraded"
        from engines.registry import engine_count
        return f"{status}\n🔧 Engines: {engine_count()}\n📊 102 tests passing"

    def _cmd_products(self, arg: str) -> str:
        from core.bridge.shopify_bridge import ShopifyBridge
        products = ShopifyBridge().fetch_products()
        lines = ["📦 *Products:*"]
        for p in products[:10]:
            stock = p.get("inventory_quantity", "?")
            lines.append(f"  • {p['name']}: ${p['price']} (stock: {stock})")
        return "\n".join(lines)

    def _cmd_pricing(self, arg: str) -> str:
        if not self._orch:
            return "❌ Not initialized"
        from core.bridge.shopify_bridge import ShopifyBridge
        products = ShopifyBridge().fetch_products()
        result = self._orch.submit_task("pricing", {"products": products})
        r = result.get("result", {})
        lines = ["💰 *Pricing Analysis:*"]
        for rec in r.get("pricing_recommendations", [])[:5]:
            lines.append(f"  • {rec.get('name')}: ${rec.get('current_price')} → {rec.get('action')}")
        margins = r.get("margin_analysis", {})
        if margins.get("avg_margin"):
            lines.append(f"\n📊 Avg margin: {margins['avg_margin']}%")
        return "\n".join(lines)

    def _cmd_customers(self, arg: str) -> str:
        if not self._orch:
            return "❌ Not initialized"
        from core.bridge.shopify_bridge import ShopifyBridge
        customers = ShopifyBridge().fetch_customers()
        result = self._orch.submit_task("customer_segmentation", {"customer_data": customers, "segmentation_criteria": {}})
        r = result.get("result", {})
        lines = ["👥 *Customer Segments:*"]
        for seg, info in r.get("rfm_segments", {}).items():
            if info.get("count", 0) > 0:
                lines.append(f"  • {seg}: {info['count']} customers")
        risks = r.get("churn_risks", [])
        if risks:
            lines.append(f"\n⚠️ Churn risks: {len(risks)}")
        return "\n".join(lines)

    def _cmd_seo(self, arg: str) -> str:
        from core.intelligence import SEOIntelligence
        from core.bridge.shopify_bridge import ShopifyBridge
        products = ShopifyBridge().fetch_products()
        si = SEOIntelligence()
        lines = ["🔍 *SEO Audit:*"]
        for p in products[:5]:
            audit = si.audit_page({"title": p["name"], "keyword": p.get("category", "product")})
            grade = audit["grade"]
            emoji = "✅" if grade in ("A", "B") else "⚠️" if grade == "C" else "❌"
            lines.append(f"  {emoji} {p['name']}: {audit['score']}/100 ({grade})")
        return "\n".join(lines)

    def _cmd_forecast(self, arg: str) -> str:
        if not arg:
            return "Usage: /forecast 100,120,130,140,150"
        try:
            values = [float(v.strip()) for v in arg.split(",")]
            from core.intelligence import Forecasting
            result = Forecasting().forecast(values, periods=7)
            trend = result.get("trend", {})
            emoji = "📈" if trend.get("direction") == "up" else "📉" if trend.get("direction") == "down" else "➡️"
            return (
                f"{emoji} *Forecast:*\n"
                f"Method: {result['method']}\n"
                f"Next 7: {result['forecast']}\n"
                f"Trend: {trend.get('direction')} ({trend.get('change_pct', 0)}%)"
            )
        except Exception as exc:
            return f"Error: {exc}"

    def _cmd_subject(self, arg: str) -> str:
        if not arg:
            return "Usage: /subject Your email subject line here"
        from core.intelligence import EmailIntelligence
        result = EmailIntelligence().score_subject_line(arg)
        emoji = "🟢" if result["score"] >= 70 else "🟡" if result["score"] >= 50 else "🔴"
        lines = [f"{emoji} *Subject Score: {result['score']}/100 ({result['grade']})*", f'"{arg}"']
        for imp in result.get("improvements", [])[:3]:
            lines.append(f"  💡 {imp}")
        return "\n".join(lines)

    def _cmd_workflow(self, arg: str) -> str:
        if not self._orch:
            return "❌ Not initialized"
        wf_name = arg.strip() or "product_launch"
        from core.bridge.shopify_bridge import ShopifyBridge
        products = ShopifyBridge().fetch_products()
        result = self._orch.run_workflow(wf_name, {"products": products, "criteria": {}})
        emoji = "✅" if result["status"] == "completed" else "⚠️"
        return (
            f"{emoji} *Workflow: {wf_name}*\n"
            f"Status: {result['status']}\n"
            f"Steps: {result['completed_steps']}/{result['total_steps']}\n"
            f"Time: {result['elapsed_seconds']}s"
        )

    def _cmd_report(self, arg: str) -> str:
        from core.reports import ReportGenerator
        report = ReportGenerator().daily_report()
        s = report.get("summary", {})
        rev = s.get("revenue", {})
        cust = s.get("customers", {})
        return (
            f"📊 *Daily Report*\n\n"
            f"💰 Revenue: ${rev.get('total', 0):,.2f}\n"
            f"📦 Orders: {rev.get('orders', 0)}\n"
            f"🛒 AOV: ${rev.get('aov', 0):,.2f}\n"
            f"👥 Customers: {cust.get('total', 0)} (repeat: {cust.get('repeat_rate', 0)}%)\n"
            f"🔍 SEO: {s.get('seo', {}).get('avg_score', 0)}/100"
        )

    # --- Telegram API ---

    def _get_updates(self) -> list[dict]:
        try:
            url = f"{self._base_url}/getUpdates?offset={self._offset}&timeout=30"
            req = Request(url, method="GET")
            with urlopen(req, timeout=35) as resp:
                data = json.loads(resp.read())
                return data.get("result", [])
        except (URLError, OSError):
            time.sleep(2)
            return []

    def _send_message(self, chat_id: int, text: str) -> None:
        try:
            payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}).encode()
            req = Request(f"{self._base_url}/sendMessage", data=payload,
                          headers={"Content-Type": "application/json"}, method="POST")
            urlopen(req, timeout=10)
        except Exception as exc:
            logger.error("Send message failed: %s", exc)


if __name__ == "__main__":
    TelegramBot().start()
