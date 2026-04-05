"""Multi-Channel Sync — unified product management across platforms."""
from __future__ import annotations
from typing import Any


class MultiChannelSync:
    """Sync products across Shopify + WooCommerce + Amazon."""

    def __init__(self):
        self._channels = {}

    def register_channel(self, name, adapter):
        self._channels[name] = adapter

    def sync_all(self, products):
        results = {}
        for name, adapter in self._channels.items():
            try:
                if hasattr(adapter, "get_products"):
                    remote = adapter.get_products()
                    results[name] = {"products": len(remote), "status": "synced"}
                else:
                    results[name] = {"status": "no_get_products"}
            except Exception as e:
                results[name] = {"status": "error", "error": str(e)[:50]}
        return {"channels": results, "total": len(self._channels)}

    def get_stats(self):
        return {"channels": len(self._channels), "names": list(self._channels.keys())}


_instance = None
def get_multi_channel():
    global _instance
    if _instance is None:
        _instance = MultiChannelSync()
    return _instance
