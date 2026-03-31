"""Storage configuration — centralized paths for all persistent data.

All ShopAI persistent data goes through this config.
Default: ~/.shopai/data/ (user home, survives reboots)
Override: SHOPAI_DATA_DIR environment variable
"""
from __future__ import annotations

import os

_DEFAULT_BASE = os.path.join(os.path.expanduser("~"), ".shopai", "data")
_BASE_DIR: str | None = None


def get_data_dir() -> str:
    """Get the base data directory for all ShopAI persistent storage."""
    global _BASE_DIR
    if _BASE_DIR is None:
        _BASE_DIR = os.environ.get("SHOPAI_DATA_DIR", _DEFAULT_BASE)
        os.makedirs(_BASE_DIR, exist_ok=True)
    return _BASE_DIR


def get_path(subdir: str) -> str:
    """Get a path under the data directory, creating it if needed."""
    path = os.path.join(get_data_dir(), subdir)
    os.makedirs(path, exist_ok=True)
    return path


# Standard subdirectories
def outcomes_dir() -> str:
    return get_path("outcomes")


def revenue_dir() -> str:
    return get_path("revenue")


def kpi_dir() -> str:
    return get_path("kpi")


def vector_db_path() -> str:
    return os.path.join(get_path("memory"), "vector_db.json")


def engine_memory_dir() -> str:
    return get_path("engine_memory")


def learned_weights_path() -> str:
    return os.path.join(get_path("learning"), "learned_weights.json")
