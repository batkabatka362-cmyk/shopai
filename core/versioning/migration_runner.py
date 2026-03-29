"""MigrationRunner — runs data/schema migrations safely."""
from __future__ import annotations

import copy
import time
from typing import Any, Callable

from utils.logger import get_logger
from utils.helpers import generate_id

logger = get_logger("versioning.migration")

Migration = Callable[[dict[str, Any]], dict[str, Any]]


class MigrationRunner:
    """Runs migrations with rollback support. Never destructive."""

    def __init__(self) -> None:
        self._migrations: list[dict[str, Any]] = []
        self._applied: list[dict[str, Any]] = []

    def add(self, name: str, version: str, up: Migration, down: Migration | None = None, description: str = "") -> None:
        """Register a migration."""
        self._migrations.append({
            "id": generate_id("mig"),
            "name": name,
            "version": version,
            "up": up,
            "down": down,
            "description": description,
        })

    def run_all(self, data: dict[str, Any]) -> dict[str, Any]:
        """Run all pending migrations on data. Returns migrated data."""
        result = copy.deepcopy(data)
        applied = []
        for mig in self._migrations:
            if mig["name"] in [a["name"] for a in self._applied]:
                continue
            start = time.monotonic()
            try:
                result = mig["up"](result)
                elapsed = time.monotonic() - start
                record = {"name": mig["name"], "version": mig["version"], "status": "applied",
                          "elapsed": round(elapsed, 3), "timestamp": time.time()}
                applied.append(record)
                self._applied.append(record)
                logger.info("Migration applied: %s (%.3fs)", mig["name"], elapsed)
            except Exception as exc:
                logger.error("Migration failed: %s — %s", mig["name"], exc)
                applied.append({"name": mig["name"], "status": "failed", "error": str(exc)})
                break

        return result

    def rollback_last(self, data: dict[str, Any]) -> dict[str, Any]:
        """Rollback the last applied migration."""
        if not self._applied:
            return data

        last_applied = self._applied[-1]
        mig = next((m for m in self._migrations if m["name"] == last_applied["name"]), None)
        if mig is None or mig["down"] is None:
            logger.warning("Cannot rollback %s — no down migration", last_applied["name"])
            return data

        result = copy.deepcopy(data)
        try:
            result = mig["down"](result)
            self._applied.pop()
            logger.info("Rolled back: %s", mig["name"])
        except Exception as exc:
            logger.error("Rollback failed: %s — %s", mig["name"], exc)
        return result

    def get_status(self) -> dict[str, Any]:
        return {
            "total_migrations": len(self._migrations),
            "applied": len(self._applied),
            "pending": len(self._migrations) - len(self._applied),
            "applied_list": [a["name"] for a in self._applied],
        }
