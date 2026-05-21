"""Centralized log management with in-memory storage and optional file persistence."""

import json
import logging
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

_meta_logger = logging.getLogger(__name__)


class LogManager:
    """In-memory log manager with querying, export, and cleanup capabilities."""

    LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

    def __init__(self, persist_path: Optional[str] = None):
        self._logs: list[dict] = []
        self._persist_path = persist_path

    def log(self, level: str, message: str, context: Optional[dict] = None) -> None:
        """Record a log entry."""
        level = level.upper()
        if level not in self.LEVELS:
            level = "INFO"
        entry = {
            "id": uuid.uuid4().hex[:12],
            "level": level,
            "message": message,
            "context": context or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": context.get("source", "unknown") if context else "unknown",
        }
        self._logs.append(entry)
        if self._persist_path:
            self._append_to_file(entry)

    def query(
        self,
        level: Optional[str] = None,
        since: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query logs with optional filters.

        Args:
            level: Filter by log level.
            since: ISO timestamp string; return logs after this time.
            keyword: Substring search in message.
            limit: Max results to return.
        """
        results = self._logs
        if level:
            level = level.upper()
            results = [r for r in results if r["level"] == level]
        if since:
            results = [r for r in results if r["timestamp"] >= since]
        if keyword:
            kw = keyword.lower()
            results = [r for r in results if kw in r["message"].lower()]
        return results[-limit:]

    def get_error_summary(self, hours: int = 24) -> dict:
        """Summarize errors in the last N hours grouped by first line / context."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        errors = [
            e for e in self._logs
            if e["level"] in ("ERROR", "CRITICAL") and e["timestamp"] >= cutoff
        ]
        counts: dict[str, int] = {}
        for e in errors:
            key = e["message"][:80]
            counts[key] = counts.get(key, 0) + 1
        return {
            "total_errors": len(errors),
            "unique_errors": len(counts),
            "by_message": counts,
            "hours": hours,
        }

    def export(self, filepath: str, format: str = "json") -> None:
        """Export logs to a file."""
        if format == "json":
            with open(filepath, "w") as f:
                json.dump(self._logs, f, indent=2)
        elif format == "csv":
            with open(filepath, "w") as f:
                f.write("id,level,timestamp,source,message\n")
                for entry in self._logs:
                    msg = entry["message"].replace('"', '""')
                    f.write(f'{entry["id"]},{entry["level"]},{entry["timestamp"]},{entry["source"]},"{msg}"\n')
        else:
            with open(filepath, "w") as f:
                for entry in self._logs:
                    f.write(f'[{entry["timestamp"]}] {entry["level"]} - {entry["message"]}\n')

    def clear(self, older_than: Optional[str] = None) -> int:
        """Clear logs, optionally only those older than a given ISO timestamp.

        Returns the number of entries removed.
        """
        if older_than is None:
            count = len(self._logs)
            self._logs.clear()
            return count
        before = len(self._logs)
        self._logs = [e for e in self._logs if e["timestamp"] >= older_than]
        return before - len(self._logs)

    def _append_to_file(self, entry: dict) -> None:
        try:
            with open(self._persist_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as exc:
            # A LOG MANAGER silently dropping log writes is
            # the worst possible silent failure -- we lose the
            # signal we'd need to debug the very thing we're
            # logging. ``_meta_logger`` is a separate (stdlib)
            # logger so we don't recurse into ourselves.
            _meta_logger.warning(
                "LogManager._append_to_file failed (%s): %s",
                self._persist_path, exc,
            )
