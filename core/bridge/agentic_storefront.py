"""Agentic Storefront bridge — ChatGPT/Perplexity/Copilot channel.

Wave B-1 of IMPLEMENTATION_PLAN_2026. On 24 Mar 2026 Shopify made
Agentic Storefronts default-on for 5.6M stores — products become
discoverable inside ChatGPT, Perplexity, Microsoft Copilot (and
Gemini via UCP roll-out). Attribution arrives on each order as
``source_name`` = ``chatgpt`` | ``perplexity`` | ``copilot`` |
``gemini`` | ``agentic`` (Shopify uses generic tag when exact
surface can't be resolved).

This module owns:

  * ``AgenticChannelStatus`` — read enrollment per AI surface via
    Shopify Admin GraphQL (``agenticStorefrontChannels`` query
    shipped Winter '26).
  * ``AgenticAttribution`` — parse ``source_name`` into a known
    channel and emit an outcome event per order.
  * Per-channel aggregates (GMV / orders / AOV over a window)
    so the brain can rebalance budget toward the highest-ROAS
    AI surface.

Pure stdlib + an injected Shopify GraphQL client. The GraphQL
client comes in via dependency injection so tests run offline.
Production callers pass in ``core/adapters/shopify/modern_client
.ShopifyModernClient`` (or a future 2026-04 refresh).

Docs reference:
  * shopify.com/news/winter-26-edition-agentic-storefronts
  * shopify.dev/docs/agents
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger


logger = get_logger("core.bridge.agentic_storefront")


_KNOWN_CHANNELS: tuple[str, ...] = (
    "chatgpt",
    "perplexity",
    "copilot",
    "gemini",
    "agentic",   # generic fallback Shopify uses
)


_STATUS_QUERY = """
query AgenticStorefrontChannels {
  agenticStorefrontChannels {
    edges {
      node {
        channelName
        enabled
        lastAttributedOrderAt
        totalOrderCount
      }
    }
  }
}
"""


@dataclass
class ChannelStatus:
    channel: str
    enabled: bool
    last_order_ts: float = 0.0
    total_orders: int = 0
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "enabled": self.enabled,
            "last_order_ts": self.last_order_ts,
            "total_orders": self.total_orders,
            "note": self.note,
        }


@dataclass
class ChannelMetrics:
    channel: str
    orders: int
    gmv_usd: float
    refunds_usd: float
    aov_usd: float
    window_days: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "orders": self.orders,
            "gmv_usd": round(self.gmv_usd, 2),
            "refunds_usd": round(self.refunds_usd, 2),
            "aov_usd": round(self.aov_usd, 2),
            "window_days": self.window_days,
        }


def normalize_source(source_name: str) -> str:
    """Normalize a Shopify ``source_name`` into one of our canonical
    channel tags. Unknown sources collapse to ``""`` so callers can
    distinguish "no channel" from "known agentic".
    """
    if not source_name:
        return ""
    s = str(source_name).lower().strip()
    for c in _KNOWN_CHANNELS:
        if c in s:
            return c
    # Shopify sometimes uses a longer tag, e.g.
    # "ai_agent:chatgpt" — split and try
    for token in s.replace(":", " ").replace(
        "_", " ",
    ).split():
        if token in _KNOWN_CHANNELS:
            return token
    return ""


class AgenticStorefrontBridge:
    """Owner-facing status + attribution reader."""

    def __init__(
        self,
        *,
        graphql_client: Any = None,
        now_fn: Any = None,
    ) -> None:
        self._client = graphql_client
        self._now_fn = now_fn or time.time
        self._lock = threading.RLock()
        self._last_status_ts = 0.0
        self._cached_status: tuple[
            ChannelStatus, ...
        ] = ()

    # ── Status ───────────────────────────────────────────

    def status(
        self, *, force: bool = False,
    ) -> tuple[ChannelStatus, ...]:
        """Return enrollment + summary per channel.

        Caches for 5 min between calls unless ``force=True``.
        Falls back to per-channel 'unknown' when the Admin
        API lacks the Winter '26 query (older shop versions).
        """
        with self._lock:
            now = float(self._now_fn())
            if (
                not force
                and self._cached_status
                and (now - self._last_status_ts) < 300
            ):
                return self._cached_status
        if self._client is None:
            return self._unknown_status("no graphql client")
        try:
            resp = self._client.execute(
                _STATUS_QUERY,
                expected_cost=3.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "agentic status graphql failed: %s", exc,
            )
            return self._unknown_status(
                f"graphql error: {exc}",
            )
        edges = (
            (resp or {})
            .get("data", {})
            .get("agenticStorefrontChannels", {})
            .get("edges", [])
            or []
        )
        found: dict[str, ChannelStatus] = {}
        for edge in edges:
            node = (edge or {}).get("node") or {}
            raw_name = str(
                node.get("channelName", "") or "",
            ).lower()
            name = normalize_source(raw_name) or raw_name
            if not name:
                continue
            found[name] = ChannelStatus(
                channel=name,
                enabled=bool(node.get("enabled")),
                last_order_ts=float(
                    node.get(
                        "lastAttributedOrderAt", 0,
                    ) or 0,
                ),
                total_orders=int(
                    node.get("totalOrderCount", 0) or 0,
                ),
            )
        # Fill known channels not returned by Shopify so the
        # owner sees a complete picture
        out: list[ChannelStatus] = []
        for c in _KNOWN_CHANNELS:
            out.append(
                found.get(c, ChannelStatus(
                    channel=c,
                    enabled=False,
                    note="not reported by Shopify",
                )),
            )
        with self._lock:
            self._cached_status = tuple(out)
            self._last_status_ts = float(self._now_fn())
        return self._cached_status

    def _unknown_status(
        self, reason: str,
    ) -> tuple[ChannelStatus, ...]:
        return tuple(
            ChannelStatus(
                channel=c, enabled=False, note=reason,
            )
            for c in _KNOWN_CHANNELS
        )

    # ── Attribution + metrics ───────────────────────────

    @staticmethod
    def classify_order(
        order: dict[str, Any],
    ) -> str:
        """Classify a Shopify order payload into an agentic
        channel. Returns ``""`` for non-agentic orders."""
        if not isinstance(order, dict):
            return ""
        for key in (
            "source_name", "channel", "source",
        ):
            val = order.get(key)
            if val:
                channel = normalize_source(str(val))
                if channel:
                    return channel
        # Check note_attributes for agent-specific flags
        attrs = order.get("note_attributes") or []
        if isinstance(attrs, list):
            for attr in attrs:
                if not isinstance(attr, dict):
                    continue
                name = str(attr.get("name", "")).lower()
                value = str(attr.get("value", "")).lower()
                if name.startswith("agentic") or name.startswith("shopai_channel"):
                    channel = normalize_source(value)
                    if channel:
                        return channel
        return ""

    def aggregate(
        self,
        orders: list[dict[str, Any]],
        *,
        window_days: int = 7,
    ) -> list[ChannelMetrics]:
        """Roll up a list of orders into per-channel metrics.

        Orders outside the window are skipped. ``orders`` is any
        iterable of dicts with ``total_price`` / ``refund_amount``
        / ``created_at_ts`` (epoch seconds). The aggregate is
        deterministic; no side-effects.
        """
        now = float(self._now_fn())
        cutoff = now - (
            float(window_days) * 86400.0
        )
        by_channel: dict[str, dict[str, float]] = {}
        for o in orders or []:
            ts = float(o.get("created_at_ts", 0) or 0)
            if ts > 0 and ts < cutoff:
                continue
            channel = self.classify_order(o)
            if not channel:
                continue
            rec = by_channel.setdefault(
                channel,
                {"orders": 0, "gmv": 0.0, "refunds": 0.0},
            )
            rec["orders"] += 1
            try:
                rec["gmv"] += float(
                    o.get("total_price", 0) or 0,
                )
            except (TypeError, ValueError) as exc:
                logger.debug(
                    "bad total_price in order: %s", exc,
                )
            try:
                rec["refunds"] += float(
                    o.get("refund_amount", 0) or 0,
                )
            except (TypeError, ValueError) as exc:
                logger.debug(
                    "bad refund_amount in order: %s",
                    exc,
                )
        out: list[ChannelMetrics] = []
        for channel, rec in by_channel.items():
            orders_n = int(rec["orders"])
            gmv = float(rec["gmv"])
            aov = gmv / orders_n if orders_n > 0 else 0.0
            out.append(ChannelMetrics(
                channel=channel,
                orders=orders_n,
                gmv_usd=gmv,
                refunds_usd=float(rec["refunds"]),
                aov_usd=aov,
                window_days=int(window_days),
            ))
        out.sort(key=lambda m: -m.gmv_usd)
        return out


# ── Singleton ───────────────────────────────────────────────

_SINGLETON: AgenticStorefrontBridge | None = None
_SINGLETON_LOCK = threading.Lock()


def get_agentic_bridge() -> AgenticStorefrontBridge:
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = AgenticStorefrontBridge()
    return _SINGLETON


def reset_agentic_bridge_for_tests() -> None:
    global _SINGLETON
    with _SINGLETON_LOCK:
        _SINGLETON = None
