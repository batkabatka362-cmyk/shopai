"""Store Registry — register new stores with ZERO code. Just credentials.

Usage:
  CLI:      python scripts/add_store.py --url mystore.myshopify.com --token shpat_xxx --name "My Store" --niche home
  API:      POST /api/stores {url, token, name, niche}
  Telegram: /addstore mystore.myshopify.com shpat_xxx MyStore home

When a store is registered:
  1. Validate credentials (test API call)
  2. Save to unified DB (store_id from URL)
  3. Initial sync (products, orders, customers)
  4. Auto-optimize all products (desc, tags, SEO, images)
  5. Share existing rules/strategies from other stores
  6. Add to daemon rotation
  7. First AI cycle runs immediately
"""
from __future__ import annotations
import json
import os
import sqlite3
import time
import urllib.request
from pathlib import Path
from typing import Any
from utils.logger import get_logger
logger = get_logger("store.registry")

_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "store_registry.db"


class StoreRegistry:
    """Central registry for all stores. Zero-code store onboarding."""

    def __init__(self) -> None:
        self._db_path = str(_DB_PATH)
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._db_path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def _init_schema(self) -> None:
        self._conn().executescript("""
            CREATE TABLE IF NOT EXISTS stores (
                store_id    TEXT PRIMARY KEY,
                shop_url    TEXT NOT NULL,
                token       TEXT NOT NULL,
                name        TEXT DEFAULT '',
                niche       TEXT DEFAULT '',
                store_type  TEXT DEFAULT 'dropshipping',
                status      TEXT DEFAULT 'pending',
                owner       TEXT DEFAULT '',
                telegram_chat_id INTEGER DEFAULT 0,
                products_count INTEGER DEFAULT 0,
                orders_count INTEGER DEFAULT 0,
                customers_count INTEGER DEFAULT 0,
                last_sync   REAL DEFAULT 0,
                last_cycle  REAL DEFAULT 0,
                health_score INTEGER DEFAULT 0,
                created_at  REAL NOT NULL,
                config      TEXT DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS store_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id    TEXT NOT NULL,
                event       TEXT NOT NULL,
                details     TEXT DEFAULT '',
                timestamp   REAL NOT NULL
            );
        """)

    # ── REGISTER ─────────────────────────────────

    def register(self, shop_url: str, token: str, name: str = "",
                 niche: str = "", store_type: str = "dropshipping",
                 owner: str = "", telegram_chat_id: int = 0) -> dict[str, Any]:
        """Register a new store. Returns setup result."""

        # 1. Derive store_id from URL
        store_id = shop_url.replace(".myshopify.com", "").replace("https://", "").replace("http://", "").strip("/")
        shop_url = shop_url if ".myshopify.com" in shop_url else store_id + ".myshopify.com"

        # 2. Validate credentials
        valid = self._validate_credentials(shop_url, token)
        if not valid.get("success"):
            return {"status": "error", "error": valid.get("error", "Invalid credentials"),
                    "store_id": store_id}

        # 3. Save to registry DB
        conn = self._conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO stores
                   (store_id, shop_url, token, name, niche, store_type, owner,
                    telegram_chat_id, status, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (store_id, shop_url, token, name or valid.get("shop_name", store_id),
                 niche, store_type, owner, telegram_chat_id, "active", time.time()),
            )
            conn.commit()
        finally:
            conn.close()

        self._log_event(store_id, "registered", "Store registered successfully")

        # 4. Save to main StoreManager DB too
        self._save_to_store_manager(store_id, shop_url, token)

        # 5. Run auto-setup pipeline
        setup_result = self._auto_setup(store_id, shop_url, token, niche)

        return {
            "status": "success",
            "store_id": store_id,
            "shop_url": shop_url,
            "name": name or valid.get("shop_name", ""),
            "setup": setup_result,
        }

    # ── VALIDATE ─────────────────────────────────

    @staticmethod
    def _validate_credentials(shop_url: str, token: str) -> dict:
        """Test Shopify API connection."""
        try:
            req = urllib.request.Request(
                "https://{}/admin/api/2024-01/shop.json".format(shop_url),
                headers={"X-Shopify-Access-Token": token},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                shop = data.get("shop", {})
                return {
                    "success": True,
                    "shop_name": shop.get("name", ""),
                    "domain": shop.get("domain", ""),
                    "currency": shop.get("currency", ""),
                    "plan": shop.get("plan_name", ""),
                }
        except urllib.error.HTTPError as exc:
            return {"success": False, "error": "HTTP {} — check token".format(exc.code)}
        except Exception as exc:
            return {"success": False, "error": str(exc)[:100]}

    # ── AUTO-SETUP ───────────────────────────────

    def _auto_setup(self, store_id: str, shop_url: str, token: str,
                    niche: str) -> dict[str, Any]:
        """Full automatic store setup — no human needed."""
        result = {"steps": []}
        h = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

        # Step 1: Sync products
        try:
            from data_pipeline.store.store_manager import StoreManager
            sm = StoreManager()
            sm.set_credentials(store_id, shop_url, token)

            from data_pipeline.store.sync_service import SyncService
            sync = SyncService(sm)
            sync_result = sync.sync_store(store_id)
            products_count = sync_result.get("synced", {}).get("products", {}).get("count", 0)
            result["steps"].append({"sync": "OK", "products": products_count})
            self._update_counts(store_id, products_count, 0, 0)
        except Exception as exc:
            result["steps"].append({"sync": "error", "error": str(exc)[:50]})
            products_count = 0

        # Step 2: Auto-optimize products (descriptions, tags, SEO)
        try:
            from execution.store_optimizer import get_store_optimizer
            opt = get_store_optimizer()
            # Get products from API
            req = urllib.request.Request(
                "https://{}/admin/api/2024-01/products.json?limit=50".format(shop_url),
                headers=h)
            with urllib.request.urlopen(req, timeout=15) as resp:
                products = json.loads(resp.read()).get("products", [])

            opt_result = opt.optimize(products, shop_url, token, max_changes=50)
            result["steps"].append({"optimize": "OK", "changes": opt_result.get("total_changes", 0)})
        except Exception as exc:
            result["steps"].append({"optimize": "error", "error": str(exc)[:50]})

        # Step 3: Full store configuration (collections, discounts, content, tags)
        try:
            from execution.store_configurator import get_store_configurator
            sc = get_store_configurator()
            config_result = sc.configure(shop_url, token, niche)
            result["steps"].append({
                "configure": "OK",
                "collections": config_result.get("results", {}).get("collections", {}).get("created", 0),
                "discounts": config_result.get("results", {}).get("discounts", {}).get("created", 0),
                "tagged": config_result.get("results", {}).get("product_tags", {}).get("tagged", 0),
            })
        except Exception as exc:
            result["steps"].append({"configure": "error", "error": str(exc)[:50]})

        # Step 4: Add placeholder images where missing
        try:
            from execution.shopify_automation import get_shopify_automation
            auto = get_shopify_automation()
            auto.set_credentials(shop_url, token)
            img_result = auto.add_placeholder_images(products, max_products=50)
            result["steps"].append({"images": "OK", "added": img_result.get("added", 0)})
        except Exception as exc:
            result["steps"].append({"images": "error", "error": str(exc)[:50]})

        # Step 4: Create discount codes
        try:
            auto = get_shopify_automation()
            auto.set_credentials(shop_url, token)
            disc_result = auto.create_discount_strategy(products)
            result["steps"].append({"discounts": "OK", "created": disc_result.get("created", 0)})
        except Exception as exc:
            result["steps"].append({"discounts": "error", "error": str(exc)[:50]})

        # Step 5: Share knowledge from existing stores
        try:
            from core.brain.multi_store_brain import get_multi_store
            ms = get_multi_store()
            ms.register_store(store_id, {"niche": niche})

            # Get knowledge from all other stores
            other_stores = self.list_stores()
            for other in other_stores:
                if other["store_id"] != store_id and other["status"] == "active":
                    shared = ms.share_learning(other["store_id"])
                    if shared.get("shareable_rules", 0) > 0:
                        ms.apply_learning(store_id, shared)
                        result["steps"].append({
                            "knowledge_shared": "OK",
                            "from": other["store_id"],
                            "rules": shared.get("shareable_rules", 0),
                        })
                        break
        except Exception as exc:
            result["steps"].append({"knowledge": "error", "error": str(exc)[:50]})

        # Step 6: Run first AI cycle
        try:
            from core.autonomous.controller import AutonomousController
            ac = AutonomousController(auto_approve=False)
            ac.initialize()
            cycle = ac.run_cycle(store_id)
            result["steps"].append({
                "first_cycle": "OK",
                "phases": len(cycle.get("phases", {})),
                "insights": cycle.get("phases", {}).get("layers", {}).get("total_insights", 0),
            })
            self._update_health(store_id, cycle)
        except Exception as exc:
            result["steps"].append({"first_cycle": "error", "error": str(exc)[:50]})

        self._log_event(store_id, "setup_complete", json.dumps(result))
        return result

    # ── STORE MANAGER DB ─────────────────────────

    @staticmethod
    def _save_to_store_manager(store_id: str, shop_url: str, token: str) -> None:
        try:
            from data_pipeline.store.store_manager import StoreManager
            sm = StoreManager()
            # Register store in main DB
            conn = sm._get_conn()
            conn.execute(
                "INSERT OR REPLACE INTO stores (store_id, shop_url, status, created_at, updated_at) VALUES (?,?,?,?,?)",
                (store_id, shop_url, "active", time.time(), time.time()),
            )
            conn.commit()
            sm.set_credentials(store_id, shop_url, token)
        except Exception:
            pass

    # ── QUERIES ──────────────────────────────────

    def list_stores(self) -> list[dict]:
        conn = self._conn()
        try:
            rows = conn.execute("SELECT * FROM stores ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_store(self, store_id: str) -> dict | None:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM stores WHERE store_id = ?", (store_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_active_stores(self) -> list[str]:
        conn = self._conn()
        try:
            rows = conn.execute("SELECT store_id FROM stores WHERE status = 'active'").fetchall()
            return [r["store_id"] for r in rows]
        finally:
            conn.close()

    def remove_store(self, store_id: str) -> dict:
        conn = self._conn()
        try:
            conn.execute("UPDATE stores SET status = 'removed' WHERE store_id = ?", (store_id,))
            conn.commit()
            self._log_event(store_id, "removed", "")
            return {"status": "removed", "store_id": store_id}
        finally:
            conn.close()

    # ── UPDATES ──────────────────────────────────

    def _update_counts(self, store_id: str, products: int, orders: int, customers: int) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE stores SET products_count=?, orders_count=?, customers_count=?, last_sync=? WHERE store_id=?",
                (products, orders, customers, time.time(), store_id))
            conn.commit()
        finally:
            conn.close()

    def _update_health(self, store_id: str, cycle_result: dict) -> None:
        health = cycle_result.get("phases", {}).get("brain", {}).get("health_score", 0)
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE stores SET health_score=?, last_cycle=? WHERE store_id=?",
                (health, time.time(), store_id))
            conn.commit()
        finally:
            conn.close()

    def _log_event(self, store_id: str, event: str, details: str = "") -> None:
        conn = self._conn()
        try:
            conn.execute(
                "INSERT INTO store_events (store_id, event, details, timestamp) VALUES (?,?,?,?)",
                (store_id, event, details[:500], time.time()))
            conn.commit()
        finally:
            conn.close()

    def get_events(self, store_id: str = "", limit: int = 20) -> list[dict]:
        conn = self._conn()
        try:
            if store_id:
                rows = conn.execute(
                    "SELECT * FROM store_events WHERE store_id=? ORDER BY timestamp DESC LIMIT ?",
                    (store_id, limit)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM store_events ORDER BY timestamp DESC LIMIT ?",
                    (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_stats(self) -> dict:
        conn = self._conn()
        try:
            total = conn.execute("SELECT COUNT(*) as c FROM stores").fetchone()
            active = conn.execute("SELECT COUNT(*) as c FROM stores WHERE status='active'").fetchone()
            return {
                "total_stores": total["c"] if total else 0,
                "active_stores": active["c"] if active else 0,
            }
        finally:
            conn.close()


# Singleton
_instance = None
def get_store_registry():
    global _instance
    if _instance is None:
        _instance = StoreRegistry()
    return _instance
