"""Persistent Store -- namespace-based long-term storage backed by JSON files."""
from __future__ import annotations

import json
import os
import time
from typing import Any

_BASE_PATH = "/tmp/shopai_memory/"


class PersistentStore:
    """Namespace-based persistent key-value store backed by JSON files."""

    def __init__(self, base_path: str = _BASE_PATH) -> None:
        self._base_path: str = base_path
        self._namespaces: dict[str, dict[str, dict[str, Any]]] = {}
        os.makedirs(self._base_path, exist_ok=True)

    # ---- Public API -------------------------------------------------------

    def store(
        self,
        namespace: str,
        key: str,
        value: Any,
        metadata: dict | None = None,
    ) -> None:
        """Store a value under namespace/key with optional metadata."""
        ns = self._ensure_namespace(namespace)
        ns[key] = {
            "value": value,
            "metadata": metadata or {},
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        self._persist_namespace(namespace)

    def retrieve(self, namespace: str, key: str) -> Any:
        """Retrieve a value. Returns None if not found."""
        ns = self._ensure_namespace(namespace)
        entry = ns.get(key)
        if entry is None:
            return None
        return entry["value"]

    def search(self, namespace: str, query: str) -> list[dict]:
        """Keyword search in keys and metadata values (case-insensitive)."""
        ns = self._ensure_namespace(namespace)
        q = query.lower()
        results: list[dict] = []
        for key, entry in ns.items():
            searchable = key.lower()
            meta = entry.get("metadata", {})
            for v in meta.values():
                searchable += " " + str(v).lower()
            if q in searchable:
                results.append({
                    "key": key,
                    "value": entry["value"],
                    "metadata": meta,
                })
        return results

    def delete(self, namespace: str, key: str) -> bool:
        """Delete a key from a namespace. Returns True if it existed."""
        ns = self._ensure_namespace(namespace)
        if key not in ns:
            return False
        del ns[key]
        self._persist_namespace(namespace)
        return True

    def list_keys(self, namespace: str) -> list[str]:
        """List all keys in a namespace."""
        ns = self._ensure_namespace(namespace)
        return sorted(ns.keys())

    def list_namespaces(self) -> list[str]:
        """List all known namespaces (loaded + on-disk)."""
        on_disk: set[str] = set()
        try:
            for fname in os.listdir(self._base_path):
                if fname.endswith(".json"):
                    on_disk.add(fname[:-5])
        except OSError:
            pass
        return sorted(set(self._namespaces.keys()) | on_disk)

    def get_stats(self) -> dict:
        """Return statistics about the store."""
        namespaces = self.list_namespaces()
        total_keys = 0
        for ns_name in namespaces:
            ns = self._ensure_namespace(ns_name)
            total_keys += len(ns)
        return {
            "namespaces": len(namespaces),
            "total_keys": total_keys,
            "base_path": self._base_path,
        }

    # ---- Persistence ------------------------------------------------------

    def _persist_namespace(self, namespace: str) -> None:
        """Write a namespace to its JSON file."""
        path = os.path.join(self._base_path, f"{namespace}.json")
        try:
            os.makedirs(self._base_path, exist_ok=True)
            with open(path, "w") as f:
                json.dump(self._namespaces.get(namespace, {}), f, indent=2)
        except OSError:
            pass

    def _load_namespace(self, namespace: str) -> dict[str, dict[str, Any]]:
        """Load a namespace from its JSON file. Returns the dict."""
        path = os.path.join(self._base_path, f"{namespace}.json")
        if not os.path.exists(path):
            return {}
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    # ---- Private helpers --------------------------------------------------

    def _ensure_namespace(self, namespace: str) -> dict[str, dict[str, Any]]:
        """Return the in-memory dict for *namespace*, loading from disk if needed."""
        if namespace not in self._namespaces:
            self._namespaces[namespace] = self._load_namespace(namespace)
        return self._namespaces[namespace]
