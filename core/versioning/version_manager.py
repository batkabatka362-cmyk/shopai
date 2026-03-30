"""VersionManager — tracks engine and system versions."""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("versioning.manager")

_VERSION_PATH = "/tmp/shopai_versions/versions.json"
SYSTEM_VERSION = "1.0.0"


class VersionManager:
    """Tracks versions of engines, configs, and schemas."""

    def __init__(self) -> None:
        self._versions: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self._load()

    def register_version(self, component: str, version: str, changes: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Register a new version for a component."""
        entry = {
            "version": version,
            "changes": changes,
            "metadata": metadata or {},
            "timestamp": time.time(),
            "status": "active",
        }
        with self._lock:
            if component not in self._versions:
                self._versions[component] = []
            self._versions[component].append(entry)
            self._persist()
        logger.info("Version registered: %s v%s", component, version)
        return entry

    def get_current(self, component: str) -> dict[str, Any] | None:
        """Get current (latest active) version."""
        with self._lock:
            versions = self._versions.get(component, [])
            active = [v for v in versions if v["status"] == "active"]
            return active[-1] if active else None

    def get_history(self, component: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._versions.get(component, []))

    def list_components(self) -> dict[str, str]:
        """List all components with current version."""
        with self._lock:
            result = {}
            for comp, versions in self._versions.items():
                active = [v for v in versions if v["status"] == "active"]
                result[comp] = active[-1]["version"] if active else "unknown"
            return result

    def mark_deprecated(self, component: str, version: str) -> bool:
        with self._lock:
            for v in self._versions.get(component, []):
                if v["version"] == version:
                    v["status"] = "deprecated"
                    self._persist()
                    return True
            return False

    def get_system_version(self) -> dict[str, Any]:
        return {
            "system": SYSTEM_VERSION,
            "components": self.list_components(),
        }

    def _persist(self) -> None:
        os.makedirs(os.path.dirname(_VERSION_PATH), exist_ok=True)
        try:
            with open(_VERSION_PATH, "w") as f:
                json.dump(self._versions, f)
        except OSError:
            pass

    def _load(self) -> None:
        if os.path.exists(_VERSION_PATH):
            try:
                with open(_VERSION_PATH) as f:
                    self._versions = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
