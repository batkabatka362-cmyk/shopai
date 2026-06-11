"""StoreManager — manages multiple Shopify stores.

Each store has its own credentials, config, and data.
Supports adding/removing stores, switching active store, and batch operations.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("store_manager")

# Cache ShopifyAuth instances per (shop_url, client_id, client_secret) to avoid
# repeated token cache loads and refresh attempts on every credential lookup.
# get_credentials() may be called multiple times per cycle.
_auth_instances: dict[tuple[str, str, str], Any] = {}
_auth_lock = threading.Lock()


def _get_auth_instance(shop_url: str, client_id: str, client_secret: str) -> Any:
    """Return a cached ShopifyAuth instance, creating it on first access.

    Thread-safe: pre-audit two concurrent first-callers with
    the same key could both pass the ``None`` check and both
    construct a ShopifyAuth — the second assignment silently
    overwrote the first, discarding its token cache state.
    Audit pass 48.
    """
    key = (shop_url, client_id, client_secret)
    with _auth_lock:
        auth = _auth_instances.get(key)
        if auth is None:
            from core.auth.shopify_auth import ShopifyAuth
            auth = ShopifyAuth(shop_url, client_id, client_secret)
            _auth_instances[key] = auth
        return auth


class StoreManager:
    """Manages multiple Shopify stores for ShopAI."""

    # W949: persist active store across CLI invocations
    _ACTIVE_STORE_PATH = "data/.active_store"

    def __init__(self, db: Any = None) -> None:
        from data_pipeline.store.db import ShopAIDatabase
        import os
        self._db: ShopAIDatabase = db or ShopAIDatabase()
        # W949 bugfix: load persisted active store id at init.
        # W951 (Pattern J): under pytest, never read from the
        # persistence file -- tests need clean state per
        # fixture, not cross-test leakage.
        if os.environ.get("PYTEST_CURRENT_TEST"):
            self._active_store_id = ""
        else:
            try:
                if os.path.exists(self._ACTIVE_STORE_PATH):
                    with open(
                        self._ACTIVE_STORE_PATH, "r",
                        encoding="utf-8",
                    ) as f:
                        candidate = f.read().strip()
                    # W958 bugfix: validate the persisted
                    # active store still exists in the DB.
                    # Stale .active_store from pre-W953 test
                    # leakage (e.g. "store2") used to crash
                    # downstream consumers with FK constraint
                    # failures.
                    if candidate and self._db.get_store(
                        candidate,
                    ):
                        self._active_store_id = candidate
                    else:
                        self._active_store_id = ""
                        if candidate:
                            logger.info(
                                "persisted active store %r "
                                "not found in registry; "
                                "ignoring stale value",
                                candidate,
                            )
                else:
                    self._active_store_id = ""
            except Exception:  # noqa: BLE001
                self._active_store_id = ""
        self._store_credentials: dict[str, dict[str, str]] = {}
        # Protects _active_store_id and _store_credentials from
        # concurrent access. Multiple API handlers can call
        # add_store / set_active_store / get_credentials in
        # parallel. Audit pass 48.
        self._lock = threading.RLock()

    def _persist_active(self, store_id: str) -> None:
        """W949: write active store id to disk so subsequent
        CLI invocations pick it up. Best-effort -- a failure
        does not break the in-memory operation.

        W951 (Pattern J): short-circuit under pytest so tests
        with their own StoreManager fixtures don't see
        cross-test leakage from this disk file.
        """
        import os
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        try:
            os.makedirs(
                os.path.dirname(self._ACTIVE_STORE_PATH),
                exist_ok=True,
            )
            with open(
                self._ACTIVE_STORE_PATH, "w",
                encoding="utf-8",
            ) as f:
                f.write(store_id or "")
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "active store persist failed: %s", exc,
            )

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
        if not isinstance(store_id, str) or not store_id:
            return {"error": "store_id required"}
        if not isinstance(shop_url, str) or not shop_url:
            return {"error": "shop_url required"}

        # W963-125 round-8 #2: refuse registration when
        # this sid normalises to the SAME per-store
        # env-var key as an already-registered sid.
        # Without this guard, operator adding both
        # 'store-a' and 'store_a' would silently share
        # one set of SHOPAI_STORE_STORE_A_* credentials
        # for ALL adapter categories (Meta Ads tokens,
        # OpenAI keys, etc.), routing spend + mutations
        # to the wrong account.
        try:
            from core.adapters._per_store_credentials import (
                sid_normalises_to_same_env,
            )
            with self._lock:
                existing = list(
                    self._store_credentials.keys(),
                )
            for other in existing:
                if sid_normalises_to_same_env(
                    store_id, other,
                ):
                    return {
                        "error": (
                            f"store_id {store_id!r} "
                            f"collides with existing "
                            f"{other!r} -- they normalise "
                            "to the same per-store env-var "
                            "key (W963-125 guard). Pick a "
                            "distinct sid; e.g. use "
                            "'store_a_2' instead of "
                            "'store-a' when 'store_a' "
                            "already exists."
                        ),
                    }
        except Exception as exc:  # noqa: BLE001
            # Collision check failure must not block
            # registration -- log + continue (degraded
            # mode).
            logger.debug(
                "sid collision check raised: %s", exc,
            )

        # Write the DB row FIRST. If the DB add fails, we don't
        # want the in-memory credentials to be left hanging.
        # Audit pass 48.
        result = self._db.add_store(
            store_id, shop_url,
            name=name, niche=niche, store_type=store_type,
            config={"api_version": "2024-01"},
        )
        with self._lock:
            self._store_credentials[store_id] = {
                "shop_url": shop_url,
                "api_key": api_key or "",
                "client_id": client_id or "",
                "client_secret": client_secret or "",
            }
            became_active = False
            if not self._active_store_id:
                self._active_store_id = store_id
                became_active = True
        # W949: persist auto-promoted active store
        if became_active:
            self._persist_active(store_id)
        logger.info("Store added: %s (%s)", store_id, shop_url)
        return result

    def update_store_niche(
        self, store_id: str, niche: str,
    ) -> dict[str, Any]:
        """Wave 77: update a store's niche without re-adding.

        Operator wants to adjust a store's niche after
        observing it; previously this meant `remove` + `add`
        which loses credentials. This is a simple SQL UPDATE.
        """
        if not isinstance(store_id, str) or not store_id:
            return {"error": "store_id required"}
        if not isinstance(niche, str):
            return {"error": "niche must be string"}
        niche = niche.strip().lower()
        store = self._db.get_store(store_id)
        if not store:
            return {"error": f"store '{store_id}' not found"}
        import time as _t
        conn = self._db._get_conn()
        try:
            conn.execute(
                "UPDATE stores SET niche = ?, updated_at = ? "
                "WHERE store_id = ?",
                (niche, _t.time(), store_id),
            )
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"db update failed: {exc}"}
        logger.info(
            "Store niche updated: %s -> %s", store_id, niche,
        )
        return {
            "store_id": store_id,
            "niche": niche,
            "status": "updated",
        }

    def remove_store(self, store_id: str) -> dict[str, Any]:
        """Deactivate a store (soft delete)."""
        with self._lock:
            self._store_credentials.pop(store_id, None)
        conn = self._db._get_conn()
        conn.execute(
            "UPDATE stores SET status = 'inactive', updated_at = ? WHERE store_id = ?",
            (time.time(), store_id),
        )
        conn.commit()
        new_active = None
        with self._lock:
            if self._active_store_id == store_id:
                stores = self._db.list_stores()
                self._active_store_id = (
                    stores[0]["store_id"] if stores else ""
                )
                new_active = self._active_store_id
        # W949: persist active change after store removal
        if new_active is not None:
            self._persist_active(new_active)
        return {"store_id": store_id, "status": "removed"}

    def get_store(self, store_id: str) -> dict[str, Any] | None:
        return self._db.get_store(store_id)

    def list_stores(self) -> list[dict[str, Any]]:
        stores = self._db.list_stores()
        with self._lock:
            active = self._active_store_id
            creds_keys = set(self._store_credentials.keys())
        # Make defensive copies so caller mutation doesn't
        # leak into the DB row cache. Audit pass 48.
        result = []
        for s in stores:
            if not isinstance(s, dict):
                continue
            row = dict(s)
            row["is_active"] = row.get("store_id") == active
            row["has_credentials"] = row.get("store_id") in creds_keys
            result.append(row)
        return result

    # ── Active Store ─────────────────────────────────────────

    def set_active_store(self, store_id: str) -> dict[str, Any]:
        store = self._db.get_store(store_id)
        if not store:
            return {"error": f"Store {store_id} not found"}
        with self._lock:
            self._active_store_id = store_id
        # W949 bugfix: persist to disk so next CLI process
        # picks it up (was in-memory only).
        self._persist_active(store_id)
        logger.info("Active store set to: %s", store_id)
        return {"active_store": store_id, "shop_url": store["shop_url"]}

    @property
    def active_store_id(self) -> str:
        with self._lock:
            return self._active_store_id

    @property
    def active_store(self) -> dict[str, Any] | None:
        with self._lock:
            sid = self._active_store_id
        if not sid:
            return None
        return self._db.get_store(sid)

    # ── Credentials ──────────────────────────────────────────

    def has_store(self, store_id: str) -> bool:
        """W963-124: return True iff store_id is a known
        per-store entry (not just an env fallback).

        Used by W963-115's _resolve_credentials to detect
        the case where `active_store(sid)` was set for an
        unknown sid -- without this check, get_credentials
        falls back to env vars and the adapter silently
        routes the call to the env-default store. Money-
        class bug.
        """
        if not isinstance(store_id, str) or not store_id:
            return False
        with self._lock:
            return store_id in self._store_credentials

    def find_by_shop_url(self, shop_url: str) -> str:
        """W963-128: reverse lookup from shop URL to
        store_id. Shopify webhooks include the shop URL
        in X-Shopify-Shop-Domain but engines reference
        stores by store_id. The webhook handler uses this
        to map back so engine.run can be wrapped in
        active_store(sid) for per-store routing.

        Returns the matching store_id, or empty string
        when no store matches. Tolerates the leading
        'https://' or trailing '/' that some webhook
        clients send: normalised before comparison.
        """
        if not isinstance(shop_url, str) or not shop_url:
            return ""
        normalised = (
            shop_url.replace("https://", "")
            .replace("http://", "")
            .rstrip("/")
            .lower()
        )
        with self._lock:
            for sid, creds in self._store_credentials.items():
                stored = str(
                    creds.get("shop_url", ""),
                )
                stored_norm = (
                    stored.replace("https://", "")
                    .replace("http://", "")
                    .rstrip("/")
                    .lower()
                )
                if stored_norm == normalised:
                    return sid
        return ""

    def get_credentials(self, store_id: str = "") -> dict[str, str]:
        """Get API credentials for a store. Supports OAuth auto-refresh."""
        with self._lock:
            sid = store_id or self._active_store_id
            # Snapshot the credentials dict inside the lock so
            # a concurrent ``set_credentials`` can't mutate our
            # copy mid-read.
            cached = self._store_credentials.get(sid) if sid else None
            creds: dict[str, str] | None = dict(cached) if cached else None
        if creds is not None:
            # Token refresh runs OUTSIDE the lock — it may
            # make a blocking HTTP call.
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
                auth = _get_auth_instance(creds["shop_url"],
                                           creds["client_id"],
                                           creds["client_secret"])
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
                auth = _get_auth_instance(shop_url, client_id, client_secret)
                return auth.get_token()
            except Exception:
                pass
        return os.environ.get("SHOPAI_SHOPIFY_KEY", "")

    def set_credentials(self, store_id: str, shop_url: str, api_key: str) -> None:
        if not isinstance(store_id, str) or not store_id:
            return
        with self._lock:
            self._store_credentials[store_id] = {
                "shop_url": shop_url if isinstance(shop_url, str) else "",
                "api_key": api_key if isinstance(api_key, str) else "",
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
