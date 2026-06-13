"""Structured JSON Logger — persistent log file with structured entries."""
from __future__ import annotations
import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from utils.logger import get_logger
logger = get_logger("structured_log")

_LOG_PATH = Path(__file__).resolve().parents[2] / "data" / "structured_log.json"


class StructuredLogger:
    """Writes structured JSON log entries to file."""

    def __init__(self):
        # W962-47: per-instance lock spans log() append + flush()
        # so concurrent producers don't race on the buffer or
        # the load-extend-write of the persisted log.
        self._lock = threading.RLock()
        self._buffer: list[dict] = []
        self._flush_interval = 10  # Write every 10 entries

    def log(self, level: str, component: str, message: str,
            data: dict | None = None) -> None:
        entry = {
            "level": level,
            "component": component,
            "message": message,
            "data": data or {},
            "timestamp": time.time(),
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with self._lock:
            self._buffer.append(entry)
            should_flush = len(self._buffer) >= self._flush_interval
        if should_flush:
            self.flush()

    def log_cycle(self, cycle_result: dict) -> None:
        """Log a complete cycle result."""
        self.log("info", "cycle", "Cycle complete", {
            "duration": cycle_result.get("duration_s", 0),
            "phases": len(cycle_result.get("phases", {})),
            "status": cycle_result.get("status", ""),
        })

    def flush(self) -> None:
        """W962-47: spanning lock around read+extend+write,
        atomic write via temp + os.replace."""
        with self._lock:
            if not self._buffer:
                return
            try:
                _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
                existing = []
                if _LOG_PATH.exists():
                    try:
                        existing = json.loads(_LOG_PATH.read_text())
                    except Exception as exc:  # noqa: BLE001
                        logger.debug(
                            "structured_log read failed (treating "
                            "as empty): %s", exc,
                        )
                        existing = []
                existing.extend(self._buffer)
                # Keep last 500
                if len(existing) > 500:
                    existing = existing[-500:]
                tmp = _LOG_PATH.with_suffix(
                    _LOG_PATH.suffix + ".tmp." + str(os.getpid())
                )
                tmp.write_text(json.dumps(existing, indent=2))
                os.replace(tmp, _LOG_PATH)
                self._buffer.clear()
            except Exception as exc:
                logger.debug("structured_log flush failed: %s", exc)

    def get_recent(self, limit: int = 20) -> list[dict]:
        try:
            if _LOG_PATH.exists():
                entries = json.loads(_LOG_PATH.read_text())
                return entries[-limit:]
        except Exception as exc:
            logger.debug("structured_log get_recent failed: %s", exc)
        return self._buffer[-limit:]

    def get_stats(self) -> dict:
        try:
            if _LOG_PATH.exists():
                entries = json.loads(_LOG_PATH.read_text())
                return {"total": len(entries), "buffered": len(self._buffer)}
        except Exception as exc:
            logger.debug("structured_log get_stats failed: %s", exc)
        return {"total": 0, "buffered": len(self._buffer)}


_instance = None
def get_structured_logger():
    global _instance
    if _instance is None:
        _instance = StructuredLogger()
    return _instance
