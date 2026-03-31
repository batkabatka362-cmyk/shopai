import logging
import os
import sys
from typing import Optional


_loggers: dict[str, logging.Logger] = {}
_log_level = getattr(logging, os.environ.get("SHOPAI_LOG_LEVEL", "WARNING").upper(), logging.WARNING)


def get_logger(name: str, level: Optional[int] = None) -> logging.Logger:
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(f"shopai.{name}")
    logger.setLevel(level if level is not None else _log_level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        logger.addHandler(handler)

    _loggers[name] = logger
    return logger
