"""Structured logging for ShopAI.

Controlled via environment variables:

    SHOPAI_LOG_LEVEL    DEBUG | INFO | WARNING | ERROR | CRITICAL   (default: WARNING)
    SHOPAI_LOG_FORMAT   text | json                                 (default: text)
    SHOPAI_LOG_FILE     path to a log file (enables rotation)       (default: stdout only)
    SHOPAI_LOG_MAX_MB   rotate when file exceeds N MB               (default: 10)
    SHOPAI_LOG_BACKUPS  number of rotated files to keep             (default: 5)

The text format stays close to the original so existing log scrapers keep
working:
    2026-04-06 14:05:12 [INFO] shopai.auth: token refreshed

The JSON format emits one object per line with canonical fields, plus any
extra data passed via the `extra={"event_data": {...}}` logging kwarg or
the `log_event()` helper:
    {"ts": "...", "level": "INFO", "logger": "shopai.auth",
     "msg": "token refreshed", "event": "auth.refresh", "store": "s1"}

All loggers share one configured handler set — calling `get_logger()`
multiple times with the same name returns the same instance.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import time
from pathlib import Path
from typing import Any


_loggers: dict[str, logging.Logger] = {}

# --- Config (read once at import) ------------------------------------------

_LOG_LEVEL = getattr(
    logging, os.environ.get("SHOPAI_LOG_LEVEL", "WARNING").upper(),
    logging.WARNING,
)
_LOG_FORMAT = os.environ.get("SHOPAI_LOG_FORMAT", "text").lower()
_LOG_FILE = os.environ.get("SHOPAI_LOG_FILE", "").strip()
try:
    _LOG_MAX_BYTES = int(float(os.environ.get("SHOPAI_LOG_MAX_MB", "10")) * 1024 * 1024)
except ValueError:
    _LOG_MAX_BYTES = 10 * 1024 * 1024
try:
    _LOG_BACKUPS = int(os.environ.get("SHOPAI_LOG_BACKUPS", "5"))
except ValueError:
    _LOG_BACKUPS = 5

_TEXT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


# --- JSON formatter --------------------------------------------------------

class JsonFormatter(logging.Formatter):
    """Emits one JSON object per log line.

    Canonical fields: ts, level, logger, msg. Any structured data attached
    to the record via `extra={"event_data": {...}}` is merged into the
    top-level object so downstream log processors can filter on it.
    """

    # Fields automatically added to every LogRecord by the logging module.
    # We skip these when scanning for user-supplied `extra` keys so custom
    # per-call fields ride along without a nested dict.
    _STANDARD_ATTRS = frozenset({
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message", "asctime", "taskName",
    })

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
                  + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        # Merge structured data from `extra={"event_data": {...}}`
        event_data = getattr(record, "event_data", None)
        if isinstance(event_data, dict):
            for k, v in event_data.items():
                if k not in payload:
                    payload[k] = v

        # Also merge arbitrary per-call `extra={"field": value}` kwargs
        for k, v in record.__dict__.items():
            if k in self._STANDARD_ATTRS or k == "event_data":
                continue
            if k.startswith("_"):
                continue
            if k not in payload:
                payload[k] = v

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


# --- Handler construction --------------------------------------------------

def _build_handlers() -> list[logging.Handler]:
    handlers: list[logging.Handler] = []

    if _LOG_FORMAT == "json":
        formatter: logging.Formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(_TEXT_FORMAT)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    handlers.append(stream)

    if _LOG_FILE:
        try:
            path = Path(_LOG_FILE)
            path.parent.mkdir(parents=True, exist_ok=True)
            rot = logging.handlers.RotatingFileHandler(
                _LOG_FILE,
                maxBytes=_LOG_MAX_BYTES,
                backupCount=_LOG_BACKUPS,
                encoding="utf-8",
            )
            rot.setFormatter(formatter)
            handlers.append(rot)
        except Exception as exc:  # noqa: BLE001
            # Never fail the app because logging setup failed — write the
            # error to stderr and fall back to stdout-only.
            print(f"[logger] failed to open {_LOG_FILE}: {exc}", file=sys.stderr)

    return handlers


# Lazily cache handlers so every logger reuses the same file handle
# (prevents RotatingFileHandler backup collisions with multiple handlers).
_SHARED_HANDLERS: list[logging.Handler] | None = None


def _get_shared_handlers() -> list[logging.Handler]:
    global _SHARED_HANDLERS
    if _SHARED_HANDLERS is None:
        _SHARED_HANDLERS = _build_handlers()
    return _SHARED_HANDLERS


def get_logger(name: str, level: int | None = None) -> logging.Logger:
    """Return a configured logger for the given component name.

    Called from ~260 call sites; interface is stable. Pass `level` to
    override the module-wide default for one logger.
    """
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(f"shopai.{name}")
    logger.setLevel(level if level is not None else _LOG_LEVEL)
    # Prevent double emission via the root logger
    logger.propagate = False

    if not logger.handlers:
        for handler in _get_shared_handlers():
            logger.addHandler(handler)

    _loggers[name] = logger
    return logger


# --- Public helpers --------------------------------------------------------

def log_event(logger: logging.Logger, event: str, level: int = logging.INFO,
              msg: str | None = None, **fields: Any) -> None:
    """Emit a structured log event.

    In JSON mode the fields become top-level keys. In text mode they are
    appended to the message as `key=value` pairs.

    Example:
        log_event(log, "pricing.adjusted", product_id="p123", delta=0.12)
    """
    message = msg or event
    if _LOG_FORMAT == "json":
        logger.log(
            level, message,
            extra={"event_data": {"event": event, **fields}},
        )
    else:
        if fields:
            pairs = " ".join(f"{k}={v}" for k, v in fields.items())
            logger.log(level, "%s %s", event if msg else message, pairs)
        else:
            logger.log(level, event if msg else message)


def reset_for_tests() -> None:
    """Clear all cached loggers and handlers. Tests only."""
    global _SHARED_HANDLERS
    for lg in _loggers.values():
        for h in list(lg.handlers):
            try:
                h.close()
            except Exception:  # noqa: BLE001
                pass
            lg.removeHandler(h)
    _loggers.clear()
    if _SHARED_HANDLERS:
        for h in _SHARED_HANDLERS:
            try:
                h.close()
            except Exception:  # noqa: BLE001
                pass
    _SHARED_HANDLERS = None


def reload_config() -> None:
    """Re-read env vars and rebuild handlers. Tests / config reload."""
    global _LOG_LEVEL, _LOG_FORMAT, _LOG_FILE, _LOG_MAX_BYTES, _LOG_BACKUPS
    _LOG_LEVEL = getattr(
        logging, os.environ.get("SHOPAI_LOG_LEVEL", "WARNING").upper(),
        logging.WARNING,
    )
    _LOG_FORMAT = os.environ.get("SHOPAI_LOG_FORMAT", "text").lower()
    _LOG_FILE = os.environ.get("SHOPAI_LOG_FILE", "").strip()
    try:
        _LOG_MAX_BYTES = int(float(os.environ.get("SHOPAI_LOG_MAX_MB", "10")) * 1024 * 1024)
    except ValueError:
        _LOG_MAX_BYTES = 10 * 1024 * 1024
    try:
        _LOG_BACKUPS = int(os.environ.get("SHOPAI_LOG_BACKUPS", "5"))
    except ValueError:
        _LOG_BACKUPS = 5
    reset_for_tests()
