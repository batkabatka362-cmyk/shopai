"""Multi-Channel adapter registry — reads products from registered platforms.

Currently supports read-side enumeration only. Write-side sync (push
products from one channel to another) is not implemented; add an
adapter-specific `push_products` method when write support is needed.
"""
from __future__ import annotations


class MultiChannelSync:
    """Registry of platform adapters for cross-channel reads."""

    def __init__(self):
        self._channels = {}

    def register_channel(self, name, adapter):
        self._channels[name] = adapter

    def fetch_all(self):
        """Fetch products from every registered adapter. Read-only."""
        results = {}
        for name, adapter in self._channels.items():
            if not hasattr(adapter, "get_products"):
                results[name] = {"status": "no_get_products"}
                continue
            try:
                remote = adapter.get_products()
                results[name] = {"products": len(remote), "status": "fetched"}
            except Exception as e:
                results[name] = {"status": "error", "error": str(e)[:50]}
        return {"channels": results, "total": len(self._channels)}

    # Backward-compat alias
    sync_all = fetch_all

    def get_stats(self):
        return {"channels": len(self._channels), "names": list(self._channels.keys())}


_instance = None
def get_multi_channel():
    global _instance
    if _instance is None:
        _instance = MultiChannelSync()
    return _instance
