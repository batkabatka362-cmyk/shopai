"""StoreManager — manages multiple Shopify stores.

Each store has its own credentials, config, and data.
Supports adding/removing stores, switching active store, and batch operations.
"""
from __future__ import annotations

import os
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("store_manager")


class StoreManager:
    """Manages multiple Shopify stores for ShopAI."""

    def __init__(self, db: Any = None) -> None:
        from data_pipeline.store.db import ShopAIDatabase
        self._db: ShopAIDatabase = db or ShopAIDatabase()
        self._active_store_id: str = ""
        self._store_credentials: dict[str, dict[str, str]] = {}

    # ── Store CRUD ───────────────────────────────────────────

    def add_store(
        self,
        store_id: str,
        shop_url: str,
        api_key: str = "",
        name: str = "",
        niche: str = "",
        store_type: str = "dropshipping",
        client_id: str = "",
        client_secret: str = "",
    ) -> dict[str, Any]:
        """Register a new Shopify store. Supports OAuth (client_id+secret) or legacy key."""
        self._store_credentials[store_id] = {
            "shop_url": shop_url,
            "api_key": api_key,
            "client_id": client_id,
            "client_secret": client_secret,
        }
        result = self._db.add_store(
            store_id, shop_url,
            name=name, niche=niche, store_type=store_type,
            config={"api_version": "2024-01"},
        )
        logger.info("Store added: %s (%s)", store_id, shop_url)

        if not self._active_store_id:
            self._active_store_id = store_id

        return result

    def remove_store(self, store_id: str) -> dict[str, Any]:
        """Deactivate a store (soft delete)."""
        self._store_credentials.pop(store_id, None)
        conn = self._db._get_conn()
        conn.execute(
            "UPDATE stores SET status = 'inactive', updated_at = ? WHERE store_id = ?",
            (time.time(), store_id),
        )
        conn.commit()
        if self._active_store_id == store_id:
            stores = self._db.list_stores()
            self._active_store_id = stores[0]["store_id"] if stores else ""
        return {"store_id": store_id, "status": "removed"}

    def get_store(self, store_id: str) -> dict[str, Any] | None:
        return self._db.get_store(store_id)

    def list_stores(self) -> list[dict[str, Any]]:
        stores = self._db.list_stores()
        for s in stores:
            s["is_active"] = s["store_id"] == self._active_store_id
            s["has_credentials"] = s["store_id"] in self._store_credentials
        return stores

    # ── Active Store ─────────────────────────────────────────

    def set_active_store(self, store_id: str) -> dict[str, Any]:
        store = self._db.get_store(store_id)
        if not store:
            return {"error": f"Store {store_id} not found"}
        self._active_store_id = store_id
        logger.info("Active store set to: %s", store_id)
        return {"active_store": store_id, "shop_url": store["shop_url"]}

    @property
    def active_store_id(self) -> str:
        return self._active_store_id

    @property
    def active_store(self) -> dict[str, Any] | None:
        if not self._active_store_id:
            return None
        return self._db.get_store(self._active_store_id)

    # ── Credentials ──────────────────────────────────────────

    def get_credentials(self, store_id: str = "") -> dict[str, str]:
        """Get API credentials for a store. Supports OAuth auto-refresh."""
        sid = store_id or self._active_store_id
        if sid in self._store_credentials:
            creds = dict(self._store_credentials[sid])
            # Try OAuth token refresh
            creds["api_key"] = self._resolve_token(creds)
            return creds
        # Fallback to env vars (single-store mode)
        return {
            "shop_url": os.environ.get("SHOPAI_SHOPIFY_URL", ""),
            "api_key": self._resolve_env_token(),
        }

    @staticmethod
    def _resolve_token(creds: dict[str, str]) -> str:
        """Resolve token — use OAuth if client_id/secret present, else static key."""
        if creds.get("client_id") and creds.get("client_secret"):
            try:
                from core.auth.shopify_auth import ShopifyAuth
                auth = ShopifyAuth(creds["shop_url"], creds["client_id"], creds["client_secret"])
                return auth.get_token()
            except Exception:
                pass
        return creds.get("api_key", "")

    @staticmethod
    def _resolve_env_token() -> str:
        """Resolve token from env — OAuth or legacy."""
        client_id = os.environ.get("SHOPAI_SHOPIFY_CLIENT_ID", "")
        client_secret = os.environ.get("SHOPAI_SHOPIFY_CLIENT_SECRET", "")
        shop_url = os.environ.get("SHOPAI_SHOPIFY_URL", "")
        if client_id and client_secret and shop_url:
            try:
                from core.auth.shopify_auth import ShopifyAuth
                auth = ShopifyAuth(shop_url, client_id, client_secret)
                return auth.get_token()
            except Exception:
                pass
        return os.environ.get("SHOPAI_SHOPIFY_KEY", "")

    def set_credentials(self, store_id: str, shop_url: str, api_key: str) -> None:
        self._store_credentials[store_id] = {
            "shop_url": shop_url,
            "api_key": api_key,
        }

    # ── Store Data Access ────────────────────────────────────

    def get_products(self, store_id: str = "", **kwargs: Any) -> list[dict[str, Any]]:
        sid = store_id or self._active_store_id
        return self._db.get_products(sid, **kwargs)

    def get_orders(self, store_id: str = "", **kwargs: Any) -> list[dict[str, Any]]:
        sid = store_id or self._active_store_id
        return self._db.get_orders(sid, **kwargs)

    def get_customers(self, store_id: str = "", **kwargs: Any) -> list[dict[str, Any]]:
        sid = store_id or self._active_store_id
        return self._db.get_customers(sid, **kwargs)

    def get_stats(self, store_id: str = "") -> dict[str, Any]:
        sid = store_id or self._active_store_id
        return self._db.get_store_stats(sid)

    def get_all_stats(self) -> list[dict[str, Any]]:
        """Get stats for all active stores."""
        stores = self._db.list_stores()
        return [self._db.get_store_stats(s["store_id"]) for s in stores]

    # ── Connection Test ──────────────────────────────────────

    def test_connection(self, store_id: str = "") -> dict[str, Any]:
        """Test Shopify API connection for a store."""
        creds = self.get_credentials(store_id)
        if not creds.get("shop_url") or not creds.get("api_key"):
            return {"connected": False, "error": "Missing credentials"}

        try:
            from core.bridge.shopify_bridge import ShopifyBridge
            bridge = ShopifyBridge(creds["shop_url"], creds["api_key"])
            return bridge.connect()
        except Exception as exc:
            return {"connected": False, "error": str(exc)}

    @property
    def db(self) -> Any:
        return self._db
