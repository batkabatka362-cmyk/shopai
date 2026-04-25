"""TikTok Shop order poller — bridges TTS orders → brain bus.

TikTok Shop has no server-to-server webhook on the free
tier, so ShopAI pulls orders on each autopilot cycle. This
engine keeps a tiny SQLite "seen" cache so each order
generates exactly one brain outcome regardless of how many
times the poller runs over its lifetime (§4b.D idempotent).
"""
from engines.tiktok_shop_poller.poller import (
    TikTokShopPoller,
    PollerSummary,
)

__all__ = ["TikTokShopPoller", "PollerSummary"]
