"""Backup/Recovery Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the backup/recovery engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class BackupInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    sources: list[str]
    storage_path: str
    compress: bool
    options: dict[str, Any]


# ---------------------------------------------------------------------------
# Intermediate types — data collection
# ---------------------------------------------------------------------------

class SourceCollection(TypedDict):
    """Collected data for a single source."""
    records: list[dict[str, Any]]
    count: int
    size_bytes: int


class CollectedData(TypedDict):
    """Result from data_collector."""
    status: str
    collected: dict[str, SourceCollection]
    total_records: int


# ---------------------------------------------------------------------------
# Intermediate types — serialization
# ---------------------------------------------------------------------------

class SerializationResult(TypedDict):
    """Result from serializer."""
    status: str
    serialized: bytes | str
    checksum_sha256: str
    size_bytes: int
    compressed_size_bytes: int
    schema_version: str


# ---------------------------------------------------------------------------
# Intermediate types — storage write
# ---------------------------------------------------------------------------

class StorageWriteResult(TypedDict):
    """Result from storage_writer."""
    status: str
    path: str
    written: bool


# ---------------------------------------------------------------------------
# Intermediate types — integrity verification
# ---------------------------------------------------------------------------

class IntegrityResult(TypedDict):
    """Result from integrity_verifier."""
    status: str
    verified: bool
    checksum_match: bool
    records_verified: int
    errors: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — recovery test
# ---------------------------------------------------------------------------

class RecoveryTestResult(TypedDict):
    """Result from recovery_tester."""
    status: str
    dry_run_success: bool
    records_restorable: int
    estimated_restore_seconds: float


# ---------------------------------------------------------------------------
# Intermediate types — backup history
# ---------------------------------------------------------------------------

class BackupHistoryEntry(TypedDict, total=False):
    """Single backup history entry."""
    backup_id: str
    timestamp: str
    size: int
    records: int


class BackupHistoryResult(TypedDict):
    """Result from memory_reader."""
    status: str
    backups: list[BackupHistoryEntry]
    count: int


# ---------------------------------------------------------------------------
# Intermediate types — metadata write
# ---------------------------------------------------------------------------

class MetadataWriteResult(TypedDict):
    """Result from memory_writer."""
    status: str
    record_id: str
    path: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class BackupSummary(TypedDict):
    """Backup summary in engine output."""
    backup_id: str
    sources_backed_up: list[str]
    total_records: int
    checksum_sha256: str
    compressed: bool
    size_bytes: int
    compressed_size_bytes: int
    storage_path: str


class IntegritySummary(TypedDict):
    """Integrity summary in engine output."""
    verified: bool
    checksum_match: bool
    records_verified: int
    errors: list[str]


class RecoverySummary(TypedDict):
    """Recovery test summary in engine output."""
    dry_run_success: bool
    records_restorable: int
    estimated_restore_seconds: float


class BackupRecoveryData(TypedDict):
    """The 'data' block of the engine output."""
    backup: BackupSummary
    integrity: IntegritySummary
    recovery: RecoverySummary
    history_count: int


class BackupRecoveryMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class BackupRecoveryOutput(TypedDict):
    """Final output of the backup/recovery engine."""
    status: str
    data: BackupRecoveryData | None
    meta: BackupRecoveryMeta
    error: str | None
