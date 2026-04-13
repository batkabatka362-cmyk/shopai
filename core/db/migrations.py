"""Lightweight SQLite migration framework.

Tracks applied schema changes in a `_schema_version` table so that each DB
can evolve without breaking existing deployments.

Usage:
    from core.db.migrations import Migrator, Migration

    MIGRATIONS: list[Migration] = [
        (1, "create tables", _v1_initial_schema),
        (2, "add index on timestamp", _v2_add_ts_index),
    ]

    def _init_schema(self) -> None:
        Migrator(self._conn(), "my_db", MIGRATIONS).run()

Each migration is a tuple `(version, description, callable)` where the
callable takes a `sqlite3.Connection` and performs the DDL. The callable
should NOT call `commit()` — the Migrator handles commits + rollbacks.

Migrations are applied in ascending version order. Any version <= the
current DB version is skipped. All applied migrations are recorded in
`_schema_version(version INTEGER PK, name TEXT, applied_at REAL)`.

The framework is intentionally minimal: no down-migrations, no schema diff
detection, no automatic rollback across migrations. Failures raise.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

from utils.logger import get_logger

logger = get_logger("db.migrations")

MigrationFn = Callable[[sqlite3.Connection], None]
Migration = tuple[int, str, MigrationFn]


class Migrator:
    """Applies pending migrations to a SQLite connection."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        name: str,
        migrations: list[Migration],
    ) -> None:
        self._conn = conn
        self._name = name
        self._migrations = sorted(migrations, key=lambda m: m[0])
        self._ensure_version_table()

    def _ensure_version_table(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _schema_version (
                version    INTEGER PRIMARY KEY,
                name       TEXT NOT NULL,
                applied_at REAL NOT NULL
            )
            """
        )
        self._conn.commit()

    def current_version(self) -> int:
        row = self._conn.execute(
            "SELECT MAX(version) FROM _schema_version"
        ).fetchone()
        if row and row[0] is not None:
            return int(row[0])
        return 0

    def applied(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT version, name, applied_at FROM _schema_version ORDER BY version"
        ).fetchall()
        return [
            {"version": r[0], "name": r[1], "applied_at": r[2]}
            for r in rows
        ]

    def pending(self) -> list[Migration]:
        current = self.current_version()
        return [m for m in self._migrations if m[0] > current]

    def run(self) -> int:
        """Apply all pending migrations in order. Returns count applied."""
        applied = 0
        for version, desc, fn in self._migrations:
            existing = self._conn.execute(
                "SELECT 1 FROM _schema_version WHERE version = ?", (version,)
            ).fetchone()
            if existing:
                continue
            try:
                fn(self._conn)
                self._conn.execute(
                    "INSERT INTO _schema_version (version, name, applied_at) VALUES (?, ?, ?)",
                    (version, desc, time.time()),
                )
                self._conn.commit()
                logger.info(
                    "[%s] migration v%d applied: %s", self._name, version, desc
                )
                applied += 1
            except Exception as exc:
                try:
                    self._conn.rollback()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("migration rollback failed: %s", exc)
                logger.error(
                    "[%s] migration v%d FAILED: %s — %s",
                    self._name, version, desc, exc,
                )
                raise
        return applied


# Registry of all DB paths + their expected current version. Populated
# by modules as they initialize. Used by `shopai db status` CLI.
_SCHEMA_REGISTRY: dict[str, tuple[Path, int]] = {}


def register_schema(name: str, db_path: Path, target_version: int) -> None:
    """Called by each DB module to advertise its schema for `db status`."""
    _SCHEMA_REGISTRY[name] = (Path(db_path), target_version)


def get_all_schema_info() -> list[dict[str, Any]]:
    """Return status for every registered DB (for CLI / health checks)."""
    results = []
    for name, (path, target) in sorted(_SCHEMA_REGISTRY.items()):
        info: dict[str, Any] = {
            "name": name,
            "path": str(path),
            "target_version": target,
            "exists": path.exists(),
            "current_version": 0,
            "pending": target,
            "status": "missing",
        }
        if path.exists():
            try:
                conn = sqlite3.connect(str(path), timeout=5)
                try:
                    try:
                        row = conn.execute(
                            "SELECT MAX(version) FROM _schema_version"
                        ).fetchone()
                        current = int(row[0]) if row and row[0] is not None else 0
                    except sqlite3.OperationalError:
                        # table doesn't exist — legacy DB
                        current = 0
                finally:
                    conn.close()
                info["current_version"] = current
                info["pending"] = max(0, target - current)
                info["status"] = "up_to_date" if current >= target else "pending"
            except Exception as exc:  # noqa: BLE001
                info["status"] = f"error: {exc}"
        results.append(info)
    return results
