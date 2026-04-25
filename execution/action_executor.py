"""ActionExecutor — the AI's "hands" for taking real actions on Shopify.

Takes engine decisions and executes them on real Shopify stores.
Supports: product CRUD, price updates, inventory updates, collection management.

Safety: All actions go through approval pipeline before execution.
"""
from __future__ import annotations

import copy
import threading
import time
import uuid
import json
from typing import Any

from utils.logger import get_logger

logger = get_logger("action_executor")


# Action types the brain emits as strategic recommendations rather than
# per-product API calls. They are tracked in memory + the cycle journal
# for learning but don't map to a concrete Shopify write on their own.
# When the matching adapter lands (email/ads/image sourcer) these will
# promote to real executors.
_ADVISORY_ACTIONS = frozenset({
    "pricing_recommendation",  # store-wide price strategy
    "update_costs",            # flag products missing cost_per_item
    "add_images",               # flag products needing imagery
    "marketing_push",           # email/ad campaign trigger
    "promote_high_margin",     # feature high-margin SKUs in collections
    "add_products",             # sourcing queue
    "kill_launch",              # ROAS bucketer → kill advisory
    "scale_launch",             # ROAS bucketer → scale advisory
})


class ActionExecutor:
    """Executes AI-decided actions on real Shopify stores."""

    def __init__(self, store_manager: Any = None) -> None:
        self._store_manager = store_manager
        self._action_log: list[dict[str, Any]] = []
        self._auto_approve = False  # Safety: manual approval by default
        self._pending_actions: list[dict[str, Any]] = []
        # Lock guarding _pending_actions / _action_log mutations.
        # Multiple cycles + the approval CLI can race on these
        # lists; without the lock, two callers could see the
        # same pending action at once or interleave appends to
        # the audit log.
        self._lock = threading.Lock()

    def set_store_manager(self, sm: Any) -> None:
        self._store_manager = sm

    def set_auto_approve(self, enabled: bool) -> None:
        """Enable/disable auto-approval of actions. DANGEROUS — use with caution."""
        self._auto_approve = enabled
        logger.warning("Auto-approve set to %s", enabled)

    # ── Action Pipeline ──────────────────────────────────────

    def propose_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """Propose an action for approval. Returns action with ID and status."""
        # Use uuid4 instead of int(time.time()*1000): millisecond
        # timestamps collide when multiple actions are proposed in
        # the same millisecond (rapid-fire automation, multi-thread
        # cycles). A collision broke _find_pending (first-match
        # wins) and the dedup filters that re-build _pending_actions
        # by id, so removing one action removed both with the same
        # id.
        action_id = f"act_{uuid.uuid4().hex[:16]}"
        # Defensive deep-copy of params: previously the proposed
        # dict held a REFERENCE to the caller's params dict, so any
        # mutation by the caller (or by `_dispatch_action`'s
        # `params.pop("product_id")` below) leaked into the audit
        # log entry and any retry logic.
        proposed = {
            "id": action_id,
            "type": action.get("type", "unknown"),
            "store_id": action.get("store_id", ""),
            "params": copy.deepcopy(action.get("params", {})),
            "reason": action.get("reason", ""),
            "engine": action.get("engine", ""),
            "confidence": action.get("confidence", 0),
            "status": "pending",
            "proposed_at": time.time(),
        }

        if self._auto_approve:
            return self.execute_action(proposed)

        with self._lock:
            self._pending_actions.append(proposed)
        logger.info("Action proposed: %s [%s] — awaiting approval", action_id, proposed["type"])
        return proposed

    def approve_action(self, action_id: str) -> dict[str, Any]:
        """Approve and execute a pending action."""
        action = self._find_pending(action_id)
        if not action:
            return {"error": f"Action {action_id} not found or already executed"}
        return self.execute_action(action)

    def reject_action(self, action_id: str, reason: str = "") -> dict[str, Any]:
        """Reject a pending action."""
        action = self._find_pending(action_id)
        if not action:
            return {"error": f"Action {action_id} not found"}
        action["status"] = "rejected"
        action["rejected_reason"] = reason
        action["rejected_at"] = time.time()
        with self._lock:
            self._pending_actions = [a for a in self._pending_actions if a["id"] != action_id]
            self._action_log.append(action)
        return action

    def approve_all(self) -> list[dict[str, Any]]:
        """Approve and execute all pending actions."""
        # Snapshot under the lock so a concurrent propose_action
        # doesn't bloat the iteration.
        with self._lock:
            snapshot = list(self._pending_actions)
        results = []
        for action in snapshot:
            results.append(self.execute_action(action))
        with self._lock:
            # Drop only the snapshot we just processed; new
            # pending entries that arrived during the loop stay.
            snapshot_ids = {a["id"] for a in snapshot}
            self._pending_actions = [
                a for a in self._pending_actions
                if a["id"] not in snapshot_ids
            ]
        return results

    def get_pending(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._pending_actions)

    # ── Execution ────────────────────────────────────────────

    def execute_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """Execute an approved action on Shopify."""
        action_type = action.get("type", "")
        store_id = action.get("store_id", "")
        # Hand the dispatcher its own copy of params so its
        # destructive ops (e.g. `params.pop("product_id")`) don't
        # mutate the action stored in pending / audit log.
        params = copy.deepcopy(action.get("params", {}))

        start = time.monotonic()
        try:
            creds = self._get_credentials(store_id)
            if not creds:
                raise ValueError(f"No credentials for store: {store_id}")

            result = self._dispatch_action(action_type, creds, params)

            elapsed = time.monotonic() - start
            action["status"] = "executed"
            action["result"] = result
            action["executed_at"] = time.time()
            action["duration_s"] = round(elapsed, 3)

            with self._lock:
                self._pending_actions = [a for a in self._pending_actions if a["id"] != action.get("id")]
                self._action_log.append(action)

            logger.info("Action executed: %s [%s] in %.2fs", action.get("id"), action_type, elapsed)
            return action

        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - start
            action["status"] = "failed"
            action["error"] = str(exc)
            action["duration_s"] = round(elapsed, 3)
            with self._lock:
                self._pending_actions = [a for a in self._pending_actions if a["id"] != action.get("id")]
                self._action_log.append(action)
            logger.error("Action failed: %s [%s]: %s", action.get("id"), action_type, exc)
            return action

    def _dispatch_action(self, action_type: str, creds: dict, params: dict) -> dict[str, Any]:
        """Route action to the right executor."""
        shop_url = creds["shop_url"]
        api_key = creds["api_key"]

        if action_type == "update_price":
            from execution.shopify.product_updater import ProductUpdater
            updater = ProductUpdater()
            return updater.update_price(
                shop_url, api_key,
                params.get("product_id", ""),
                params["variant_id"],
                params["price"],
            )

        elif action_type == "update_product":
            from execution.shopify.product_updater import ProductUpdater
            updater = ProductUpdater()
            pid = params.pop("product_id")
            return updater.update_product(shop_url, api_key, pid, params)

        elif action_type == "update_inventory":
            from execution.shopify.product_updater import ProductUpdater
            updater = ProductUpdater()
            return updater.update_inventory(
                shop_url, api_key,
                params["inventory_item_id"],
                params["location_id"],
                params["quantity"],
            )

        elif action_type == "create_product":
            from execution.shopify.product_creator import ProductCreator
            creator = ProductCreator()
            return creator.create_product(shop_url, api_key, params)

        elif action_type == "bulk_update":
            from execution.shopify.product_updater import ProductUpdater
            updater = ProductUpdater()
            return updater.update_bulk(shop_url, api_key, params.get("updates", []))

        elif action_type == "get_store_info":
            from execution.shopify.store_manager import StoreManager as ShopifyStoreMgr
            mgr = ShopifyStoreMgr()
            return mgr.get_store_info(shop_url, api_key)

        elif action_type in _ADVISORY_ACTIONS:
            # Strategic decisions the brain emits without an immediate
            # per-product API call (e.g. "products need cost data",
            # "marketing push campaign"). Record them as advisories so
            # the cycle doesn't mark them as failed — the memory layer
            # still captures the decision for later reinforcement.
            logger.info(
                "Advisory recorded: %s (params=%s)",
                action_type, {k: v for k, v in params.items() if k != "api_key"},
            )
            return {
                "status": "advisory",
                "action_type": action_type,
                "note": "advisory decision — no direct Shopify write",
                "params": params,
            }

        else:
            raise ValueError(f"Unknown action type: {action_type}")

    # ── Helpers ──────────────────────────────────────────────

    def _get_credentials(self, store_id: str) -> dict[str, str] | None:
        if self._store_manager:
            return self._store_manager.get_credentials(store_id)
        return None

    def _find_pending(self, action_id: str) -> dict[str, Any] | None:
        with self._lock:
            for a in self._pending_actions:
                if a.get("id") == action_id:
                    return a
        return None

    def get_action_log(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return self._action_log[-limit:]

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            log_snapshot = list(self._action_log)
            pending_count = len(self._pending_actions)
        executed = sum(1 for a in log_snapshot if a.get("status") == "executed")
        failed = sum(1 for a in log_snapshot if a.get("status") == "failed")
        rejected = sum(1 for a in log_snapshot if a.get("status") == "rejected")
        return {
            "pending": pending_count,
            "executed": executed,
            "failed": failed,
            "rejected": rejected,
            "total": len(log_snapshot),
            "auto_approve": self._auto_approve,
        }


class DecisionExecutor:
    """Bridges engine decisions to ActionExecutor.

    Takes engine output (recommendations) and converts to executable actions.
    """

    def __init__(self, action_executor: ActionExecutor) -> None:
        self._executor = action_executor

    def execute_pricing_decisions(
        self, store_id: str, pricing_results: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Convert pricing engine output to price update actions."""
        actions = []
        recommendations = pricing_results.get("data", {}).get("recommendations", [])
        for rec in recommendations:
            if rec.get("new_price") and rec.get("variant_id"):
                action = self._executor.propose_action({
                    "type": "update_price",
                    "store_id": store_id,
                    "engine": "pricing",
                    "confidence": rec.get("confidence", 0),
                    "reason": rec.get("reason", "AI pricing optimization"),
                    "params": {
                        "product_id": rec.get("product_id", ""),
                        "variant_id": rec["variant_id"],
                        "price": rec["new_price"],
                    },
                })
                actions.append(action)
        return actions

    def execute_inventory_decisions(
        self, store_id: str, inventory_results: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Convert inventory engine output to inventory update actions."""
        actions = []
        recommendations = inventory_results.get("data", {}).get("recommendations", [])
        for rec in recommendations:
            if rec.get("quantity") is not None:
                action = self._executor.propose_action({
                    "type": "update_inventory",
                    "store_id": store_id,
                    "engine": "inventory",
                    "confidence": rec.get("confidence", 0),
                    "reason": rec.get("reason", "AI inventory optimization"),
                    "params": {
                        "inventory_item_id": rec.get("inventory_item_id", ""),
                        "location_id": rec.get("location_id", ""),
                        "quantity": rec["quantity"],
                    },
                })
                actions.append(action)
        return actions

    def execute_product_decisions(
        self, store_id: str, product_results: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Convert product engine output to product create/update actions."""
        actions = []
        recommendations = product_results.get("data", {}).get("recommendations", [])
        for rec in recommendations:
            action_type = rec.get("action", "update_product")
            if action_type == "create":
                action = self._executor.propose_action({
                    "type": "create_product",
                    "store_id": store_id,
                    "engine": "product_selection",
                    "confidence": rec.get("confidence", 0),
                    "reason": rec.get("reason", "AI product recommendation"),
                    "params": rec.get("product_data", {}),
                })
            else:
                action = self._executor.propose_action({
                    "type": "update_product",
                    "store_id": store_id,
                    "engine": "product_optimization",
                    "confidence": rec.get("confidence", 0),
                    "reason": rec.get("reason", "AI product optimization"),
                    "params": rec.get("updates", {}),
                })
            actions.append(action)
        return actions
