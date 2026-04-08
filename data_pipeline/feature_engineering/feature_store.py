"""FeatureStore — persists and retrieves named feature sets.

Feature sets are stored as JSON files under ``/tmp/shopai_features/``.
An in-process memory cache avoids redundant disk reads within a session.

The class behaves like a singleton (one shared ``_store`` dict per process)
but is instantiated normally — callers can pass the same instance around or
create multiple instances that share the underlying files.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

logger = logging.getLogger("data_pipeline.feature_store")

_STORE_DIR = "/tmp/shopai_features"

# Module-level in-process cache shared across all FeatureStore instances.
# Protected by ``_cache_lock`` — pre-audit two concurrent
# ``store()`` calls could race on the dict assignment.
# Audit pass 50.
_MEMORY_CACHE: dict[str, list[dict[str, Any]]] = {}
_cache_lock = threading.Lock()


class FeatureStoreError(Exception):
    """Raised when a store operation cannot be completed."""


class FeatureStore:
    """Stores and retrieves named feature sets on disk (JSON) with a memory cache.

    Args:
        store_dir: Base directory for persisted feature files.
                   Defaults to ``/tmp/shopai_features``.
    """

    def __init__(self, store_dir: str = _STORE_DIR) -> None:
        self._store_dir = store_dir
        os.makedirs(self._store_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(self, feature_set_name: str, features: list[dict[str, Any]]) -> None:
        """Persist *features* under *feature_set_name*.

        The data is written to disk and also cached in process memory.

        Args:
            feature_set_name: Identifier for the feature set (alphanumeric + ``_-``).
            features:         List of feature record dicts.

        Raises:
            FeatureStoreError: If the file cannot be written.
        """
        self._validate_name(feature_set_name)
        if not isinstance(features, list):
            features = []
        with _cache_lock:
            _MEMORY_CACHE[feature_set_name] = features
        self._persist(feature_set_name, features)
        logger.info(
            "FeatureStore: stored '%s' (%d records)", feature_set_name, len(features)
        )

    def retrieve(self, feature_set_name: str) -> list[dict[str, Any]]:
        """Retrieve a previously stored feature set.

        Checks the in-process memory cache first, then falls back to disk.

        Args:
            feature_set_name: Identifier of the feature set to retrieve.

        Returns:
            List of feature record dicts, or an empty list if not found.
        """
        if not isinstance(feature_set_name, str) or not feature_set_name:
            return []
        with _cache_lock:
            cached = _MEMORY_CACHE.get(feature_set_name)
        if cached is not None:
            logger.debug("FeatureStore: cache hit for '%s'", feature_set_name)
            return cached

        features = self._load(feature_set_name)
        if features is not None:
            with _cache_lock:
                _MEMORY_CACHE[feature_set_name] = features
            return features

        logger.warning("FeatureStore: feature set '%s' not found", feature_set_name)
        return []

    def list_feature_sets(self) -> list[str]:
        """Return the names of all persisted feature sets.

        Returns:
            Sorted list of feature set names.
        """
        names: list[str] = []
        try:
            for fname in os.listdir(self._store_dir):
                if fname.endswith(".json"):
                    names.append(fname[:-5])  # strip .json
        except OSError as exc:
            logger.warning("FeatureStore: cannot list store dir: %s", exc)
        return sorted(names)

    def delete(self, feature_set_name: str) -> None:
        """Delete a feature set from both the cache and disk.

        Args:
            feature_set_name: Identifier of the feature set to delete.

        Raises:
            FeatureStoreError: If the file exists but cannot be removed.
        """
        self._validate_name(feature_set_name)
        with _cache_lock:
            _MEMORY_CACHE.pop(feature_set_name, None)
        path = self._feature_path(feature_set_name)
        if os.path.isfile(path):
            try:
                os.remove(path)
                logger.info("FeatureStore: deleted '%s'", feature_set_name)
            except OSError as exc:
                raise FeatureStoreError(
                    f"Cannot delete feature set '{feature_set_name}': {exc}"
                ) from exc
        else:
            logger.debug("FeatureStore: delete called but '%s' not on disk", feature_set_name)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _persist(
        self,
        feature_set_name: str,
        features: list[dict[str, Any]],
    ) -> None:
        """Write *features* to ``<store_dir>/<feature_set_name>.json``.

        Raises:
            FeatureStoreError: On any I/O error.
        """
        os.makedirs(self._store_dir, exist_ok=True)
        path = self._feature_path(feature_set_name)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(features, fh, default=str, indent=2)
        except OSError as exc:
            raise FeatureStoreError(
                f"Cannot write feature set '{feature_set_name}' to {path}: {exc}"
            ) from exc
        logger.debug("FeatureStore: persisted %d records to %s", len(features), path)

    def _load(self, feature_set_name: str) -> list[dict[str, Any]] | None:
        """Read and return the feature set from disk, or ``None`` if absent."""
        path = self._feature_path(feature_set_name)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, list):
                logger.warning(
                    "FeatureStore: '%s' does not contain a list; returning empty",
                    feature_set_name,
                )
                return []
            logger.debug(
                "FeatureStore: loaded %d records from %s", len(data), path
            )
            return data
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("FeatureStore: cannot load '%s': %s", feature_set_name, exc)
            return None

    def _feature_path(self, feature_set_name: str) -> str:
        return os.path.join(self._store_dir, f"{feature_set_name}.json")

    @staticmethod
    def _validate_name(name: str) -> None:
        """Validate the feature set name.

        Pre-audit ``re.match()`` on a non-string (None, int)
        raised ``TypeError: expected string or bytes-like
        object`` instead of the documented FeatureStoreError.
        Path traversal is blocked by the regex (rejects ``/``
        and ``..``). Audit pass 50.
        """
        import re
        if not isinstance(name, str) or not name:
            raise FeatureStoreError(
                "Invalid feature set name: must be a non-empty string"
            )
        if not re.match(r"^[A-Za-z0-9_\-]+$", name):
            raise FeatureStoreError(
                f"Invalid feature set name '{name}': only alphanumeric, '_', and '-' allowed"
            )
