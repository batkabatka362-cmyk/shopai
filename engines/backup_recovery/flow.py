"""Backup/Recovery Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  validate → memory_reader → data_collector → serializer → storage_writer →
  integrity_verifier → recovery_tester → memory_writer → output

Engine contract:
  Input:  {status, data: {sources, storage_path, compress, options}, meta, error}
  Output: {status, data: {backup, integrity, recovery, checksum_sha256}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import os
import time
import uuid
from typing import Any

from .data_collector import collect_data
from .serializer import serialize_data
from .storage_writer import write_backup
from .integrity_verifier import verify_integrity
from .recovery_tester import test_recovery
from .memory_reader import read_backup_history
from .memory_writer import write_backup_metadata


_DEFAULT_SOURCES = ["products", "orders", "customers", "settings"]
_DEFAULT_STORAGE_PATH = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")),
    ".backups",
)


class BackupRecoveryEngine:
    """Backup/Recovery Engine — orchestrator only, no logic."""

    ENGINE_NAME = "backup_recovery"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full backup/recovery pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            BackupOutput dict.
        """
        start = time.monotonic()

        # ---- Stage 0: Input validation (no mutation) ----
        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)

        if payload.get("status") == "fail":
            return self._fail(
                payload.get("error", "Upstream failure"), 0.0,
            )

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        sources = data.get("sources", _DEFAULT_SOURCES)
        storage_path = data.get("storage_path", _DEFAULT_STORAGE_PATH)
        compress = data.get("compress", True)
        options = data.get("options", {})

        if not sources:
            return self._fail("Source list is required", 0.0)

        # Generate backup_id: bkp_{date}_{time}_{hex6}
        now = time.gmtime()
        backup_id = "bkp_{date}_{time}_{hex}".format(
            date=time.strftime("%Y%m%d", now),
            time=time.strftime("%H%M%S", now),
            hex=uuid.uuid4().hex[:6],
        )

        # ---- Stage 1: Read backup history (non-blocking) ----
        _history = read_backup_history(limit=5)

        # ---- Stage 2: Data Collector ----
        collect_result = collect_data(
            sources=sources,
            options=options,
        )
        if collect_result.get("status") == "error":
            return self._fail(
                f"Data collection failed: {collect_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        collected = collect_result.get("collected", {})
        total_records = collect_result.get("total_records", 0)

        # ---- Stage 3: Serializer ----
        serial_result = serialize_data(
            collected=collected,
            compress=compress,
        )
        if serial_result.get("status") == "error":
            return self._fail(
                f"Serialization failed: {serial_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        serialized = serial_result.get("serialized", b"")
        checksum = serial_result.get("checksum_sha256", "")
        raw_size = serial_result.get("size_bytes", 0)
        compressed_size = serial_result.get("compressed_size_bytes", 0)

        # ---- Stage 4: Storage Writer ----
        write_result = write_backup(
            serialized=serialized,
            backup_id=backup_id,
            storage_path=storage_path,
        )
        if write_result.get("status") == "error":
            return self._fail(
                f"Storage write failed: {write_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        backup_path = write_result.get("path", "")

        # ---- Stage 5: Integrity Verifier ----
        integrity_result = verify_integrity(
            path=backup_path,
            expected_checksum=checksum,
            expected_records=total_records,
        )
        if integrity_result.get("status") == "error":
            return self._fail(
                f"Integrity verification failed: {integrity_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 6: Recovery Tester ----
        recovery_result = test_recovery(
            path=backup_path,
            sources=sources,
        )
        if recovery_result.get("status") == "error":
            return self._fail(
                f"Recovery test failed: {recovery_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 7: Memory Writer (non-fatal) ----
        # Build manifest for metadata
        manifest: dict[str, Any] = {}
        for source_name, source_data in collected.items():
            manifest[source_name] = {
                "count": source_data.get("count", 0),
                "size_bytes": source_data.get("size_bytes", 0),
            }

        _mem_result = write_backup_metadata(
            backup_id=backup_id,
            manifest=manifest,
            integrity=integrity_result,
            recovery=recovery_result,
            checksum=checksum,
            storage_path=storage_path,
            total_records=total_records,
            raw_size_bytes=raw_size,
            final_size_bytes=compressed_size,
            compressed=compress,
            sources=sources,
        )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "backup": {
                    "backup_id": backup_id,
                    "sources_backed_up": list(sources),
                    "total_records": total_records,
                    "raw_size_bytes": raw_size,
                    "final_size_bytes": compressed_size,
                    "compressed": compress,
                    "storage_path": backup_path,
                },
                "integrity": {
                    "verified": integrity_result.get("verified", False),
                    "checksum_match": integrity_result.get("checksum_match", False),
                    "records_verified": integrity_result.get("records_verified", 0),
                    "errors": integrity_result.get("errors", []),
                },
                "recovery": {
                    "dry_run_success": recovery_result.get("dry_run_success", False),
                    "records_restorable": recovery_result.get("records_restorable", 0),
                    "estimated_restore_seconds": recovery_result.get(
                        "estimated_restore_seconds", 0.0
                    ),
                },
                "checksum_sha256": checksum,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    # -------------------------------------------------------------------
    # Error output
    # -------------------------------------------------------------------

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        """Return a standardized failure output."""
        return {
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
