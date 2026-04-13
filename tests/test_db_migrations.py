"""Tests for the SQLite migration framework."""
import sqlite3
import tempfile
from pathlib import Path

import pytest


def _conn():
    return sqlite3.connect(":memory:")


class TestMigrator:
    def test_creates_version_table(self):
        from core.db.migrations import Migrator
        c = _conn()
        Migrator(c, "test", [])
        row = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='_schema_version'"
        ).fetchone()
        assert row is not None

    def test_current_version_empty(self):
        from core.db.migrations import Migrator
        m = Migrator(_conn(), "test", [])
        assert m.current_version() == 0

    def test_applies_migrations_in_order(self):
        from core.db.migrations import Migrator
        c = _conn()
        applied_order = []

        def m1(conn):
            applied_order.append(1)
            conn.execute("CREATE TABLE t1 (id INTEGER PRIMARY KEY)")

        def m2(conn):
            applied_order.append(2)
            conn.execute("CREATE TABLE t2 (id INTEGER PRIMARY KEY)")

        m = Migrator(c, "test", [(2, "t2", m2), (1, "t1", m1)])
        count = m.run()
        assert count == 2
        assert applied_order == [1, 2]
        assert m.current_version() == 2
        # Both tables should exist
        tables = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert {"t1", "t2", "_schema_version"}.issubset(tables)

    def test_idempotent_run(self):
        from core.db.migrations import Migrator
        c = _conn()
        calls = {"n": 0}

        def m1(conn):
            calls["n"] += 1
            conn.execute("CREATE TABLE x (id INTEGER)")

        Migrator(c, "test", [(1, "x", m1)]).run()
        Migrator(c, "test", [(1, "x", m1)]).run()  # second run, same migration
        assert calls["n"] == 1

    def test_adds_new_migration_only(self):
        from core.db.migrations import Migrator
        c = _conn()
        Migrator(c, "test", [(1, "a", lambda conn: conn.execute("CREATE TABLE a(id INT)"))]).run()

        calls = []
        Migrator(c, "test", [
            (1, "a", lambda conn: calls.append("a")),
            (2, "b", lambda conn: (calls.append("b"), conn.execute("CREATE TABLE b(id INT)"))[0]),
        ]).run()
        assert calls == ["b"]  # v1 skipped, v2 applied

    def test_failed_migration_rolls_back_and_raises(self):
        from core.db.migrations import Migrator
        c = _conn()

        def boom(conn):
            conn.execute("CREATE TABLE ok (id INTEGER)")
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            Migrator(c, "test", [(1, "boom", boom)]).run()

        # Version unchanged
        m = Migrator(c, "test", [])
        assert m.current_version() == 0

    def test_pending_and_applied(self):
        from core.db.migrations import Migrator
        c = _conn()
        migs = [
            (1, "a", lambda conn: conn.execute("CREATE TABLE a(id INT)")),
            (2, "b", lambda conn: conn.execute("CREATE TABLE b(id INT)")),
            (3, "c", lambda conn: conn.execute("CREATE TABLE c(id INT)")),
        ]
        m = Migrator(c, "test", migs[:2])  # only 1,2 known
        m.run()
        assert m.current_version() == 2

        m2 = Migrator(c, "test", migs)  # now 3 known
        assert [x[0] for x in m2.pending()] == [3]
        applied = m2.applied()
        assert len(applied) == 2
        assert applied[0]["version"] == 1
        assert applied[1]["version"] == 2

    def test_migration_description_stored(self):
        from core.db.migrations import Migrator
        c = _conn()
        Migrator(c, "test", [
            (1, "initial schema", lambda conn: conn.execute("CREATE TABLE x(id INT)")),
        ]).run()
        row = c.execute(
            "SELECT name FROM _schema_version WHERE version=1"
        ).fetchone()
        assert row[0] == "initial schema"


class TestSchemaRegistry:
    def test_register_and_query(self, tmp_path):
        from core.db.migrations import (
            _SCHEMA_REGISTRY, Migrator, get_all_schema_info, register_schema,
        )
        _SCHEMA_REGISTRY.clear()
        db = tmp_path / "x.db"
        # Create DB at version 2
        c = sqlite3.connect(str(db))
        Migrator(c, "x", [
            (1, "v1", lambda conn: conn.execute("CREATE TABLE a(id INT)")),
            (2, "v2", lambda conn: conn.execute("CREATE TABLE b(id INT)")),
        ]).run()
        c.close()

        register_schema("x_db", db, target_version=2)
        info = get_all_schema_info()
        assert len(info) == 1
        assert info[0]["name"] == "x_db"
        assert info[0]["current_version"] == 2
        assert info[0]["status"] == "up_to_date"
        assert info[0]["pending"] == 0

    def test_pending_status(self, tmp_path):
        from core.db.migrations import (
            _SCHEMA_REGISTRY, Migrator, get_all_schema_info, register_schema,
        )
        _SCHEMA_REGISTRY.clear()
        db = tmp_path / "y.db"
        c = sqlite3.connect(str(db))
        Migrator(c, "y", [
            (1, "v1", lambda conn: conn.execute("CREATE TABLE a(id INT)")),
        ]).run()
        c.close()

        register_schema("y_db", db, target_version=3)
        info = get_all_schema_info()
        assert info[0]["current_version"] == 1
        assert info[0]["pending"] == 2
        assert info[0]["status"] == "pending"

    def test_missing_db(self, tmp_path):
        from core.db.migrations import (
            _SCHEMA_REGISTRY, get_all_schema_info, register_schema,
        )
        _SCHEMA_REGISTRY.clear()
        register_schema("ghost", tmp_path / "nope.db", target_version=1)
        info = get_all_schema_info()
        assert info[0]["exists"] is False
        assert info[0]["status"] == "missing"

    def test_cli_db_status_runs(self, capsys):
        """Smoke test: `shopai db status` should print a table of DBs."""
        import cli
        cli.main(["db", "status"])
        out = capsys.readouterr().out
        assert "NAME" in out
        assert "VERSION" in out
        # At least one of the retrofitted DBs should appear
        assert any(name in out for name in (
            "brain_memory", "memory_intelligence", "shopai",
        ))

    def test_legacy_db_without_version_table(self, tmp_path):
        from core.db.migrations import (
            _SCHEMA_REGISTRY, get_all_schema_info, register_schema,
        )
        _SCHEMA_REGISTRY.clear()
        db = tmp_path / "legacy.db"
        c = sqlite3.connect(str(db))
        c.execute("CREATE TABLE legacy_stuff (id INTEGER)")
        c.commit()
        c.close()
        register_schema("legacy", db, target_version=1)
        info = get_all_schema_info()
        # Exists but has no _schema_version — counted as v0
        assert info[0]["exists"] is True
        assert info[0]["current_version"] == 0
        assert info[0]["status"] == "pending"
