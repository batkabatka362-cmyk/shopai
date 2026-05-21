"""Batched tests for silent-failure fixes across three
persistence-pattern modules:

- ``knowledge.prompts.prompt_manager._persist`` / ``_load``
- ``knowledge.strategies.strategy_store._persist`` / ``_load``
- ``memory.long_term.persistent_store._persist_namespace`` /
  ``list_namespaces``

All follow the canonical ""silent ``except OSError: pass`` on
file IO"" pattern caught by Pattern S audit (#479). Operators
get warning-level logs on write/read failure; behavior
contracts preserved.
"""
from __future__ import annotations

import json
import logging
from unittest.mock import patch

import pytest


# ─── PromptManager ─────────────────────────────────────────────


class TestPromptManager:

    def test_persist_failure_logs(self, tmp_path, caplog):
        from knowledge.prompts.prompt_manager import PromptManager
        pm = PromptManager(
            persist_path=str(tmp_path / "p.json"),
        )
        pm._prompts = {
            "e:s": {
                "engine_name": "e", "step": "s",
                "template": "tpl", "current_version": 1,
                "versions": {1: {"template": "tpl"}},
            },
        }
        with patch(
            "builtins.open",
            side_effect=OSError("disk full"),
        ), caplog.at_level(logging.WARNING):
            pm._persist()
        msgs = [r.message for r in caplog.records]
        assert any(
            "PromptManager._persist failed" in m
            and "disk full" in m
            for m in msgs
        )

    def test_load_corrupt_logs(self, tmp_path, caplog):
        from knowledge.prompts.prompt_manager import PromptManager
        path = tmp_path / "p.json"
        path.write_text("not valid json {{{")
        with caplog.at_level(logging.WARNING):
            pm = PromptManager(persist_path=str(path))
            pm._load()
        msgs = [r.message for r in caplog.records]
        assert any(
            "PromptManager._load failed" in m for m in msgs
        )


# ─── StrategyStore ─────────────────────────────────────────────


class TestStrategyStore:

    def test_persist_failure_logs(self, tmp_path, caplog):
        from knowledge.strategies.strategy_store import StrategyStore
        ss = StrategyStore(
            persist_path=str(tmp_path / "s.json"),
        )
        ss._strategies = {"x": {"y": 1}}
        with patch(
            "builtins.open",
            side_effect=OSError("perm denied"),
        ), caplog.at_level(logging.WARNING):
            ss._persist()
        msgs = [r.message for r in caplog.records]
        assert any(
            "StrategyStore._persist failed" in m
            and "perm denied" in m
            for m in msgs
        )

    def test_load_corrupt_logs(self, tmp_path, caplog):
        from knowledge.strategies.strategy_store import StrategyStore
        path = tmp_path / "s.json"
        path.write_text("garbage{")
        with caplog.at_level(logging.WARNING):
            ss = StrategyStore(persist_path=str(path))
            ss._load()
        msgs = [r.message for r in caplog.records]
        assert any(
            "StrategyStore._load failed" in m for m in msgs
        )

    def test_load_missing_file_silent(self, tmp_path, caplog):
        from knowledge.strategies.strategy_store import StrategyStore
        with caplog.at_level(logging.DEBUG):
            ss = StrategyStore(
                persist_path=str(tmp_path / "missing.json"),
            )
            ss._load()
        # Normal first-run path -- no log
        assert caplog.records == []


# ─── PersistentStore ───────────────────────────────────────────


class TestPersistentStore:

    def test_list_namespaces_oserror_logs(
        self, tmp_path, caplog,
    ):
        from memory.long_term.persistent_store import (
            PersistentStore,
        )
        ps = PersistentStore(base_path=str(tmp_path))
        with patch(
            "os.listdir",
            side_effect=OSError("dir broken"),
        ), caplog.at_level(logging.WARNING):
            result = ps.list_namespaces()
        # Behavior contract: still returns in-memory keys
        assert result == []
        msgs = [r.message for r in caplog.records]
        assert any(
            "list_namespaces listdir failed" in m
            and "dir broken" in m
            for m in msgs
        )

    def test_persist_namespace_failure_logs(
        self, tmp_path, caplog,
    ):
        from memory.long_term.persistent_store import (
            PersistentStore,
        )
        ps = PersistentStore(base_path=str(tmp_path))
        ps._namespaces["ns"] = {"k": {"v": 1}}
        with patch(
            "builtins.open",
            side_effect=OSError("no space"),
        ), caplog.at_level(logging.WARNING):
            ps._persist_namespace("ns")
        msgs = [r.message for r in caplog.records]
        assert any(
            "_persist_namespace failed" in m
            and "namespace=ns" in m
            and "no space" in m
            for m in msgs
        )

    def test_happy_path_no_warning(self, tmp_path, caplog):
        from memory.long_term.persistent_store import (
            PersistentStore,
        )
        ps = PersistentStore(base_path=str(tmp_path))
        ps._namespaces["ns"] = {"k": {"v": 1}}
        with caplog.at_level(logging.WARNING):
            ps._persist_namespace("ns")
            ps.list_namespaces()
        warnings = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING
        ]
        assert warnings == []
