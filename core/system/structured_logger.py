"""Structured JSON Logger — persistent log file with structured entries."""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any
from utils.logger import get_logger
logger = get_logger("structured_log")

_LOG_PATH = Path(__file__).resolve().parents[2] / "data" / "structured_log.json"


class StructuredLogger:
    """Writes structured JSON log entries to file."""

    def __init__(self):
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
        self._buffer.append(entry)
        if len(self._buffer) >= self._flush_interval:
            self.flush()

    def log_cycle(self, cycle_result: dict) -> None:
        """Log a complete cycle result."""
        self.log("info", "cycle", "Cycle complete", {
            "duration": cycle_result.get("duration_s", 0),
            "phases": len(cycle_result.get("phases", {})),
            "status": cycle_result.get("status", ""),
        })

    def flush(self) -> None:
        if not self._buffer:
            return
        try:
            _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            existing = []
            if _LOG_PATH.exists():
                try:
                    existing = json.loads(_LOG_PATH.read_text())
                except Exception:
                    existing = []
            existing.extend(self._buffer)
            # Keep last 500
            if len(existing) > 500:
                existing = existing[-500:]
            _LOG_PATH.write_text(json.dumps(existing, indent=2))
            self._buffer.clear()
        except Exception:
            pass

    def get_recent(self, limit: int = 20) -> list[dict]:
        try:
            if _LOG_PATH.exists():
                entries = json.loads(_LOG_PATH.read_text())
                return entries[-limit:]
        except Exception:
            pass
        return self._buffer[-limit:]

    def get_stats(self) -> dict:
        try:
            if _LOG_PATH.exists():
                entries = json.loads(_LOG_PATH.read_text())
                return {"total": len(entries), "buffered": len(self._buffer)}
        except Exception:
            pass
        return {"total": 0, "buffered": len(self._buffer)}


_instance = None
def get_structured_logger():
    global _instance
    if _instance is None:
        _instance = StructuredLogger()
    return _instance
