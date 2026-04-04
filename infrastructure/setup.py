"""ShopAI Setup — programmatic store connection and configuration.

Used by CLI setup wizard and can be called directly from code.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger("setup")

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ShopAISetup:
    """Handles initial setup and store connection."""

    def __init__(self) -> None:
        self._env_path = _PROJECT_ROOT / ".env"

    def load_env(self) -> dict[str, str]:
        """Load .env file if it exists."""
        if not self._env_path.exists():
            return {}
        from infrastructure.config.env_manager import EnvManager
        return EnvManager().load_env_file(str(self._env_path))

    def create_env(self, config: dict[str, str]) -> str:
        """Create .env file from config dict."""
        lines = ["# ShopAI Configuration (auto-generated)", ""]

        # Environment
        lines.append(f"SHOPAI_ENV={config.get('env', 'development')}")
        lines.append("")

        # Primary store
        if config.get("shop_url"):
            lines.append(f"SHOPAI_SHOPIFY_URL={config['shop_url']}")
        if config.get("api_key"):
            lines.append(f"SHOPAI_SHOPIFY_KEY={config['api_key']}")
        lines.append("")

        # Additional stores
        for i, store in enumerate(config.get("extra_stores", []), 2):
            lines.append(f"SHOPAI_STORE_{i}_URL={store.get('shop_url', '')}")
            lines.append(f"SHOPAI_STORE_{i}_KEY={store.get('api_key', '')}")
            if store.get("name"):
                lines.append(f"SHOPAI_STORE_{i}_NAME={store['name']}")
            if store.get("niche"):
                lines.append(f"SHOPAI_STORE_{i}_NICHE={store['niche']}")
            lines.append("")

        # AI Model
        lines.append(f"SHOPAI_OLLAMA_URL={config.get('ollama_url', 'http://localhost:11434')}")
        lines.append("")

        # Server
        lines.append(f"SHOPAI_API_HOST={config.get('api_host', '0.0.0.0')}")
        lines.append(f"SHOPAI_API_PORT={config.get('api_port', '8080')}")
        lines.append("")

        lines.append(f"SHOPAI_LOG_LEVEL={config.get('log_level', 'INFO')}")

        content = "\n".join(lines) + "\n"
        self._env_path.write_text(content)
        logger.info("Created .env at %s", self._env_path)
        return str(self._env_path)

    def setup_store(self, shop_url: str, api_key: str, **kwargs: Any) -> dict[str, Any]:
        """Full setup: create .env, init DB, test connection, initial sync."""
        results: dict[str, Any] = {"steps": []}

        # Step 1: Create/update .env
        self.create_env({"shop_url": shop_url, "api_key": api_key, **kwargs})
        os.environ["SHOPAI_SHOPIFY_URL"] = shop_url
        os.environ["SHOPAI_SHOPIFY_KEY"] = api_key
        results["steps"].append({"step": "env_created", "status": "ok"})

        # Step 2: Init store in DB
        from data_pipeline.store.store_manager import StoreManager
        sm = StoreManager()
        store_id = shop_url.replace(".myshopify.com", "").replace("https://", "")
        sm.add_store(
            store_id, shop_url, api_key,
            name=kwargs.get("name", ""),
            niche=kwargs.get("niche", ""),
            store_type=kwargs.get("store_type", "dropshipping"),
        )
        results["steps"].append({"step": "store_registered", "status": "ok", "store_id": store_id})

        # Step 3: Test connection
        conn_result = sm.test_connection(store_id)
        results["steps"].append({
            "step": "connection_test",
            "status": "ok" if conn_result.get("connected") else "failed",
            "detail": conn_result,
        })

        # Step 4: Initial sync (only if connected)
        if conn_result.get("connected"):
            from data_pipeline.store.sync_service import SyncService
            sync = SyncService(sm)
            sync_result = sync.sync_store(store_id)
            results["steps"].append({
                "step": "initial_sync",
                "status": sync_result.get("status", "unknown"),
                "synced": sync_result.get("synced", {}),
            })
        else:
            results["steps"].append({"step": "initial_sync", "status": "skipped", "reason": "not connected"})

        results["store_id"] = store_id
        results["status"] = "complete"
        return results

    def add_extra_store(self, shop_url: str, api_key: str, **kwargs: Any) -> dict[str, Any]:
        """Add an additional store to existing setup."""
        from data_pipeline.store.store_manager import StoreManager
        sm = StoreManager()
        store_id = kwargs.get("store_id") or shop_url.replace(".myshopify.com", "").replace("https://", "")

        result = sm.add_store(
            store_id, shop_url, api_key,
            name=kwargs.get("name", ""),
            niche=kwargs.get("niche", ""),
            store_type=kwargs.get("store_type", "dropshipping"),
        )

        # Test connection
        conn = sm.test_connection(store_id)

        return {
            "store_id": store_id,
            "connected": conn.get("connected", False),
            "status": "added",
        }

    def get_setup_status(self) -> dict[str, Any]:
        """Check current setup status."""
        status: dict[str, Any] = {
            "env_file": self._env_path.exists(),
            "shopify_configured": False,
            "stores": [],
            "db_exists": False,
        }

        # Check env
        if self._env_path.exists():
            self.load_env()
            status["shopify_configured"] = bool(
                os.environ.get("SHOPAI_SHOPIFY_URL") and os.environ.get("SHOPAI_SHOPIFY_KEY")
            )

        # Check DB
        db_path = _PROJECT_ROOT / "data" / "shopai.db"
        status["db_exists"] = db_path.exists()

        # Check stores
        if status["db_exists"]:
            try:
                from data_pipeline.store.store_manager import StoreManager
                sm = StoreManager()
                status["stores"] = [
                    {"id": s["store_id"], "url": s["shop_url"]}
                    for s in sm.list_stores()
                ]
            except Exception:
                pass

        return status
