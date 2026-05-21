"""Telegram Bot — monitor and control ShopAI via Telegram.

Commands: /status /cycle /report /memory /alerts /profit /help
Requires: TELEGRAM_BOT_TOKEN in .env
"""
from __future__ import annotations
import json
import os
import threading
import time
import urllib.request
from typing import Any
from utils.logger import get_logger
logger = get_logger("telegram.bot")


class TelegramBot:
    """ShopAI Telegram bot."""

    def __init__(self, token=""):
        self._token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._offset = 0
        self._running = False
        self._chat_ids = set()
        self._commands = {
            "/status": self._cmd_status,
            "/cycle": self._cmd_cycle,
            "/report": self._cmd_report,
            "/memory": self._cmd_memory,
            "/alerts": self._cmd_alerts,
            "/profit": self._cmd_profit,
            "/stores": self._cmd_stores,
            "/help": self._cmd_help,
            "/start": self._cmd_help,
        }

    def start(self):
        if not self._token:
            return {"error": "No TELEGRAM_BOT_TOKEN"}
        self._running = True
        threading.Thread(target=self._poll, daemon=True).start()
        return {"status": "started"}

    def stop(self):
        self._running = False

    def send(self, chat_id, text):
        if not self._token:
            return False
        try:
            url = "https://api.telegram.org/bot{}/sendMessage".format(self._token)
            payload = json.dumps({"chat_id": chat_id, "text": text[:4096],
                                  "parse_mode": "HTML"}).encode()
            req = urllib.request.Request(url, data=payload, method="POST",
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
            return True
        except Exception as exc:  # noqa: BLE001
            # Log so "messages not arriving" is debuggable. The
            # token is omitted from the log -- exc usually carries
            # status code + reason which is the diagnostic signal.
            logger.warning(
                "telegram send failed (chat=%s, text_len=%d): %s",
                chat_id, len(text or ""), exc,
            )
            return False

    def broadcast(self, text):
        return sum(1 for cid in self._chat_ids if self.send(cid, text))

    def _poll(self):
        while self._running:
            try:
                url = "https://api.telegram.org/bot{}/getUpdates?offset={}&timeout=5".format(
                    self._token, self._offset)
                with urllib.request.urlopen(urllib.request.Request(url), timeout=10) as resp:
                    updates = json.loads(resp.read()).get("result", [])
                    if updates:
                        self._offset = updates[-1]["update_id"] + 1
                    for u in updates:
                        self._handle(u)
            except Exception as exc:  # noqa: BLE001
                # Silent-fail would let the bot "look running" while
                # auth/network errors mean it never receives an
                # update. Log per-iteration so operators see the
                # signal.
                logger.warning(
                    "telegram poll iteration failed (offset=%s): %s",
                    self._offset, exc,
                )
            time.sleep(2)

    def _handle(self, update):
        msg = update.get("message", {})
        text = msg.get("text", "").strip()
        cid = msg.get("chat", {}).get("id", 0)
        if not text or not cid:
            return
        self._chat_ids.add(cid)
        parts = text.split()
        cmd = parts[0].lower()

        # Record every command in data architecture. The bot's
        # main work continues regardless; telemetry being down
        # shouldn't block command handling. Debug-level so noisy
        # ImportError-on-startup paths don't spam.
        try:
            from core.data.architecture import get_data_architecture
            da = get_data_architecture()
            da.capture("feedback", {
                "source": "telegram",
                "topic": cmd,
                "sentiment": "neutral",
                "urgency": "low",
            }, source="telegram_bot", score=3.5)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "telegram command telemetry failed (cmd=%s): %s",
                cmd, exc,
            )

        # Special: /addstore url token name niche
        if cmd == "/addstore" and len(parts) >= 3:
            self.send(cid, self._cmd_addstore(parts[1], parts[2],
                      parts[3] if len(parts) > 3 else "",
                      parts[4] if len(parts) > 4 else "", cid))
            return

        handler = self._commands.get(cmd)
        if handler:
            self.send(cid, handler())
        else:
            self.send(cid, "Unknown command. /help")

    @staticmethod
    def _cmd_status():
        try:
            from core.memory.intelligence import get_memory_intelligence
            from core.data.architecture import get_data_architecture
            mi = get_memory_intelligence()
            da = get_data_architecture()
            s = mi.get_stats()
            ds = da.get_stats()
            return "ShopAI Status\nMemories: {}\nRules: {} Strategies: {}\nData: {} records ({}%)\nScore: {}".format(
                s["total_memories"], s["by_level"].get("rule", 0),
                s["by_level"].get("strategy", 0), ds["total_records"],
                ds["result_rate"], s["avg_score"])
        except Exception as e:
            return "Error: {}".format(e)

    @staticmethod
    def _cmd_cycle():
        try:
            from core.autonomous.controller import AutonomousController
            ac = AutonomousController(auto_approve=False)
            ac.initialize()
            r = ac.run_cycle("deguar")
            return "Cycle done: {}s | {} phases | {} insights".format(
                r.get("duration_s", 0), len(r.get("phases", {})),
                r.get("phases", {}).get("layers", {}).get("total_insights", 0))
        except Exception as e:
            return "Error: {}".format(e)

    @staticmethod
    def _cmd_report():
        try:
            from core.system.auto_scheduler import get_scheduler
            sc = get_scheduler()
            if sc._last_result:
                from core.system.cycle_reporter import get_cycle_reporter
                return get_cycle_reporter().report(sc._last_result)
            return "No cycle yet. /cycle first."
        except Exception as exc:  # noqa: BLE001
            logger.debug("telegram /report failed: %s", exc)
            return "Unavailable"

    @staticmethod
    def _cmd_memory():
        try:
            from core.memory.intelligence import get_memory_intelligence
            mi = get_memory_intelligence()
            s = mi.get_stats()
            lines = ["AI Memory", "Total: {}".format(s["total_memories"])]
            for k, v in s.get("by_level", {}).items():
                lines.append("{}: {}".format(k, v))
            lines.append("Score: {}".format(s["avg_score"]))
            return "\n".join(lines)
        except Exception as exc:  # noqa: BLE001
            logger.debug("telegram /memory failed: %s", exc)
            return "Unavailable"

    @staticmethod
    def _cmd_alerts():
        try:
            from core.system.alerts import get_alert_system
            alerts = get_alert_system().get_recent(5)
            if not alerts:
                return "No alerts"
            return "\n".join("[{}] {}".format(a.get("severity"), a.get("message")) for a in alerts)
        except Exception as exc:  # noqa: BLE001
            logger.debug("telegram /alerts failed: %s", exc)
            return "Unavailable"

    @staticmethod
    def _cmd_profit():
        try:
            from core.system.profit_calculator import get_profit_calculator
            from data_pipeline.store.store_manager import StoreManager
            pc = get_profit_calculator()
            p = pc.calculate_store(StoreManager().get_products("deguar"))
            return "Profit: {}/{} profitable, {}% margin".format(
                p["profitable"], p["products"], p["avg_margin"])
        except Exception as exc:  # noqa: BLE001
            logger.debug("telegram /profit failed: %s", exc)
            return "Unavailable"

    @staticmethod
    def _cmd_stores():
        try:
            from core.system.store_registry import get_store_registry
            reg = get_store_registry()
            stores = reg.list_stores()
            if not stores:
                return "No stores registered. Use /addstore"
            lines = ["Stores ({}):\n".format(len(stores))]
            for s in stores:
                lines.append("{} [{}] {} products, health {}".format(
                    s.get("store_id", "?"), s.get("status", "?"),
                    s.get("products_count", 0), s.get("health_score", 0)))
            return "\n".join(lines)
        except Exception as exc:  # noqa: BLE001
            logger.debug("telegram /stores failed: %s", exc)
            return "Unavailable"

    @staticmethod
    def _cmd_addstore(url, token, name="", niche="", chat_id=0):
        try:
            from core.system.store_registry import get_store_registry
            reg = get_store_registry()
            result = reg.register(url, token, name, niche,
                                  telegram_chat_id=chat_id)
            if result.get("status") == "success":
                steps = result.get("setup", {}).get("steps", [])
                summary = "\n".join(str(s) for s in steps[:5])
                return "Store {} registered!\n\n{}".format(
                    result.get("store_id", ""), summary)
            return "Error: {}".format(result.get("error", "unknown"))
        except Exception as e:
            return "Error: {}".format(e)

    @staticmethod
    def _cmd_help():
        return "/status /cycle /report /memory /alerts /profit /stores /help\n/addstore url token [name] [niche]"

    def get_stats(self):
        return {"running": self._running, "chats": len(self._chat_ids),
                "configured": bool(self._token)}


_instance = None
def get_telegram_bot():
    global _instance
    if _instance is None:
        _instance = TelegramBot()
    return _instance
