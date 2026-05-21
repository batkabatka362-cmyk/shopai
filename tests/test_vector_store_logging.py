"""Tests for ``engines.global_brain.vector_store`` -- silent-
failure fix on ``_save`` + ``_load``.

Mirrors the profit_tracker / global_brain_memory patterns.
Silent loss of the vector store means search calls return
cold-start results next session and the operator never knows
the persistence step failed.
"""
from __future__ import annotations

import json
import logging
from unittest.mock import patch

import pytest


class TestVectorStoreLogging:

    def test_save_failure_logs_warning(self, tmp_path, caplog):
        from engines.global_brain import vector_store
        store_path = tmp_path / "store.json"
        with pytest.MonkeyPatch.context() as mp, \
                caplog.at_level(logging.WARNING):
            mp.setattr(
                vector_store, "_STORE_PATH", str(store_path),
            )
            vs = vector_store.VectorStore()
            vs._entries = [{"id": 1}]
            with patch(
                "builtins.open",
                side_effect=OSError("disk full"),
            ):
                vs._save()
        log_messages = [r.message for r in caplog.records]
        assert any(
            "VectorStore._save failed" in m
            and "disk full" in m
            for m in log_messages
        )

    def test_save_success_no_log(self, tmp_path, caplog):
        from engines.global_brain import vector_store
        store_path = tmp_path / "store.json"
        with pytest.MonkeyPatch.context() as mp, \
                caplog.at_level(logging.WARNING):
            mp.setattr(
                vector_store, "_STORE_PATH", str(store_path),
            )
            vs = vector_store.VectorStore()
            vs._save()
        warnings = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING
        ]
        assert warnings == []

    def test_load_corrupt_logs_warning(self, tmp_path, caplog):
        from engines.global_brain import vector_store
        store_path = tmp_path / "store.json"
        store_path.write_text("not valid json {{{")
        with pytest.MonkeyPatch.context() as mp, \
                caplog.at_level(logging.WARNING):
            mp.setattr(
                vector_store, "_STORE_PATH", str(store_path),
            )
            vs = vector_store.VectorStore()
        # Store starts empty after corrupt load (behavior contract)
        assert vs._entries == []
        msgs = [r.message for r in caplog.records]
        assert any(
            "VectorStore._load failed" in m for m in msgs
        )

    def test_load_missing_file_silent(self, tmp_path, caplog):
        from engines.global_brain import vector_store
        store_path = tmp_path / "missing.json"
        with pytest.MonkeyPatch.context() as mp, \
                caplog.at_level(logging.DEBUG):
            mp.setattr(
                vector_store, "_STORE_PATH", str(store_path),
            )
            vs = vector_store.VectorStore()
        assert vs._entries == []
        # No log records for the normal first-run path
        assert caplog.records == []

    def test_save_load_round_trip(self, tmp_path):
        from engines.global_brain import vector_store
        store_path = tmp_path / "store.json"
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                vector_store, "_STORE_PATH", str(store_path),
            )
            vs1 = vector_store.VectorStore()
            vs1._entries = [{"id": "x"}]
            vs1._save()
            vs2 = vector_store.VectorStore()
        assert vs2._entries == [{"id": "x"}]
