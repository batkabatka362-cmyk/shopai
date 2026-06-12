"""Unified external webhook handler -- routes per-vendor
events to engines under active_store scope."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


# Topic -> list of (engine_name, data_key) mappings.
# Topics are vendor-prefixed: gorgias.ticket_created,
# aftership.tracking_status_updated, ga4.purchase, etc.
EVENT_ENGINE_MAP: dict[str, list[dict[str, str]]] = {
    # ── Gorgias (W963-145) ──────────────────────────
    "gorgias.ticket_created": [
        {
            "engine": "customer_support",
            "data_key": "ticket",
        },
    ],
    "gorgias.ticket_updated": [
        {
            "engine": "customer_support",
            "data_key": "ticket",
        },
    ],
    "gorgias.message_created": [
        {
            "engine": "customer_support",
            "data_key": "message",
        },
    ],

    # ── AfterShip (W963-144) ────────────────────────
    "aftership.tracking_status_updated": [
        {
            "engine": "delivery_feedback",
            "data_key": "tracking",
        },
        {
            "engine": "shipping_alert_autonomy",
            "data_key": "tracking",
        },
    ],
    "aftership.tracking_delivered": [
        {
            "engine": "delivery_feedback",
            "data_key": "tracking",
        },
        {
            "engine": "order_followup_autonomy",
            "data_key": "tracking",
        },
    ],

    # ── GA4 (W963-146) ──────────────────────────────
    # GA4 is push-out only; no incoming events. Reserved
    # for future Measurement Protocol callbacks if
    # Google ships them.
}


@dataclass
class WebhookOutcome:
    """One handle() invocation's result envelope."""
    event_id: str
    vendor: str
    topic: str
    store_id: str = ""
    status: str = "pending"   # processed/rejected/skipped/error
    reason: str = ""
    engines_triggered: int = 0
    results: list[dict[str, Any]] = field(
        default_factory=list,
    )


class VendorHandler:
    """Base class for vendor-specific webhook handlers.

    Each vendor implements:
      - verify_hmac(body, signature) -> bool
      - extract_topic(payload, request_headers) -> str
        (e.g. 'gorgias.ticket_created')
      - extract_store_identifier(payload, headers)
        -> str (shop URL, tenant_id, etc.)
      - normalise_payload(topic, payload) -> dict
        (vendor-shape -> engine-shape under data_key)
    """

    name: str = "unknown"

    def verify_hmac(
        self, raw_body: bytes,
        signature: str,
    ) -> bool:
        """Default: HMAC unset means no verification.
        Override per vendor."""
        return True

    def extract_topic(
        self, payload: dict[str, Any],
        headers: dict[str, str],
    ) -> str:
        raise NotImplementedError

    def extract_store_identifier(
        self, payload: dict[str, Any],
        headers: dict[str, str],
    ) -> str:
        """Return whatever identifies the store. For
        Shopify-rooted vendors this is the shop URL.
        For Gorgias it's the subdomain. For AfterShip
        it's an org-scoped identifier or the order_id."""
        return ""

    def normalise_payload(
        self, topic: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Vendor-specific -> engine-compatible shape.
        Default: pass through."""
        return payload


# Idempotency: same event_id seen twice = skip.
# Bounded LRU set kept in-process.
_SEEN_EVENT_IDS: set[str] = set()
_SEEN_EVENT_IDS_ORDER: list[str] = []
_SEEN_LOCK = threading.Lock()
_SEEN_CAP = 10000


def _mark_seen(event_id: str) -> bool:
    """True if NEW, False if duplicate."""
    if not event_id:
        return True
    with _SEEN_LOCK:
        if event_id in _SEEN_EVENT_IDS:
            return False
        _SEEN_EVENT_IDS.add(event_id)
        _SEEN_EVENT_IDS_ORDER.append(event_id)
        # LRU cap eviction
        while len(
            _SEEN_EVENT_IDS_ORDER,
        ) > _SEEN_CAP:
            oldest = _SEEN_EVENT_IDS_ORDER.pop(0)
            _SEEN_EVENT_IDS.discard(oldest)
        return True


class ExternalWebhookHandler:
    """Dispatcher for external (non-Shopify) webhooks.

    Operator wires this into their HTTP server: route
    `POST /webhooks/<vendor>/` to handle() with the
    vendor's VendorHandler registered.

    Each handle() call:
      1. Identifies vendor + verifies HMAC
      2. Extracts topic
      3. Resolves store_id via vendor's identifier
         (StoreManager.find_by_shop_url for shop-rooted
         vendors)
      4. Dedups by event_id
      5. Routes via EVENT_ENGINE_MAP
      6. Wraps each engine.run in active_store(sid)
         (Pattern CD compliant)
    """

    def __init__(
        self,
        verify_signatures: bool = True,
    ) -> None:
        self._vendors: dict[str, VendorHandler] = {}
        self._stats: dict[str, int] = {
            "received": 0, "processed": 0,
            "rejected": 0, "skipped": 0,
            "duplicate": 0,
        }
        self._lock = threading.Lock()
        self._verify = verify_signatures

    def register_vendor(
        self, handler: VendorHandler,
    ) -> None:
        if not handler.name:
            raise ValueError(
                "vendor handler missing name",
            )
        self._vendors[handler.name] = handler

    def handle(
        self,
        vendor: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        raw_body: bytes | None = None,
        signature: str = "",
        event_id: str = "",
    ) -> WebhookOutcome:
        with self._lock:
            self._stats["received"] += 1

        headers = headers or {}
        if not isinstance(payload, dict):
            payload = {}

        outcome = WebhookOutcome(
            event_id=event_id,
            vendor=vendor,
            topic="",
        )

        handler = self._vendors.get(vendor)
        if handler is None:
            outcome.status = "rejected"
            outcome.reason = (
                f"no_handler_for_vendor:{vendor}"
            )
            with self._lock:
                self._stats["rejected"] += 1
            return outcome

        # HMAC verification (when secret configured)
        if self._verify and raw_body is not None:
            if not handler.verify_hmac(
                raw_body, signature,
            ):
                outcome.status = "rejected"
                outcome.reason = "invalid_hmac"
                with self._lock:
                    self._stats["rejected"] += 1
                return outcome

        # Extract topic
        try:
            topic = handler.extract_topic(
                payload, headers,
            )
        except Exception as exc:  # noqa: BLE001
            outcome.status = "rejected"
            outcome.reason = (
                f"topic_extract_raised:{exc}"
            )
            with self._lock:
                self._stats["rejected"] += 1
            return outcome
        outcome.topic = topic
        topic_key = f"{vendor}.{topic}" if (
            "." not in topic
        ) else topic

        # Dedup
        if event_id and not _mark_seen(event_id):
            outcome.status = "skipped"
            outcome.reason = "duplicate_event_id"
            with self._lock:
                self._stats["duplicate"] += 1
            return outcome

        # Resolve store_id
        try:
            store_identifier = (
                handler.extract_store_identifier(
                    payload, headers,
                )
            )
            store_id = self._resolve_store_id(
                store_identifier,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "store_id resolve failed: %s", exc,
            )
            store_id = ""
        outcome.store_id = store_id

        # Route to engines
        mappings = EVENT_ENGINE_MAP.get(topic_key) or []
        if not mappings:
            outcome.status = "skipped"
            outcome.reason = (
                f"no_mapping_for_{topic_key}"
            )
            with self._lock:
                self._stats["skipped"] += 1
            return outcome

        # Normalise vendor payload
        try:
            normalised = handler.normalise_payload(
                topic, payload,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "normalise_payload raised: %s", exc,
            )
            normalised = payload

        # Wrap engine.run in active_store when sid
        # resolves
        try:
            from core.context import (
                active_store as _w963_147_active_store,
            )
        except Exception:  # noqa: BLE001
            _w963_147_active_store = None  # type: ignore[assignment]

        results = []
        for m in mappings:
            engine_name = m.get("engine", "")
            data_key = m.get("data_key", "data")
            if not engine_name:
                continue
            engine_data = {data_key: normalised}
            if (
                store_id
                and _w963_147_active_store is not None
            ):
                with _w963_147_active_store(store_id):
                    res = self._trigger_engine(
                        engine_name, engine_data,
                        event_id,
                    )
            else:
                res = self._trigger_engine(
                    engine_name, engine_data, event_id,
                )
            results.append(res)
        outcome.engines_triggered = len(results)
        outcome.results = results
        outcome.status = "processed"
        with self._lock:
            self._stats["processed"] += 1
        return outcome

    @staticmethod
    def _resolve_store_id(
        identifier: str,
    ) -> str:
        """W963-128: shop URL -> store_id via StoreManager.
        For non-Shopify-rooted vendors this just returns
        identifier as-is (it's already a sid)."""
        if not identifier:
            return ""
        try:
            from data_pipeline.store.store_manager import (
                StoreManager,
            )
            sm = StoreManager()
            # Try as shop URL first
            sid = sm.find_by_shop_url(identifier)
            if sid:
                return sid
            # Then as direct sid
            if sm.has_store(identifier):
                return identifier
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "_resolve_store_id raised: %s", exc,
            )
        return ""

    @staticmethod
    def _trigger_engine(
        engine_name: str,
        data: dict[str, Any],
        event_id: str,
    ) -> dict[str, Any]:
        try:
            from engines.registry import (
                get_engine, is_registered,
            )
            if not is_registered(engine_name):
                return {
                    "engine": engine_name,
                    "status": "skipped",
                    "reason": "not_registered",
                }
            engine = get_engine(engine_name)
            if engine is None:
                return {
                    "engine": engine_name,
                    "status": "skipped",
                    "reason": "not_resolved",
                }
            result = engine.run(data)
            status = "?"
            if isinstance(result, dict):
                status = str(
                    result.get("status", "?"),
                )
            return {
                "engine": engine_name,
                "status": status,
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "external webhook trigger %s "
                "raised: %s", engine_name, exc,
            )
            return {
                "engine": engine_name,
                "status": "error",
                "error": str(exc)[:200],
            }

    def get_stats(self) -> dict[str, int]:
        with self._lock:
            return dict(self._stats)
