"""Backup/Recovery Engine — storage writer.

Writes serialized backup data to disk at the specified storage path.
Handles both compressed (.json.gz) and uncompressed (.json) formats.
"""
from __future__ import annotations

import os
from typing import Any


def write_backup(
    serialized: bytes | str,
    backup_id: str,
    storage_path: str,
) -> dict[str, Any]:
    """Write serialized backup data to storage.

    Args:
        serialized: The serialized (and possibly compressed) backup data.
        backup_id: Unique identifier for this backup.
        storage_path: Directory path where the backup file will be written.

    Returns:
        Structured dict confirming the write with the file path.
    """
    try:
        if not backup_id:
            return {
                "status": "error",
                "path": "",
                "written": False,
                "error": "backup_id is required",
            }

        if not storage_path:
            return {
                "status": "error",
                "path": "",
                "written": False,
                "error": "storage_path is required",
            }

        # Determine file extension based on data type
        if isinstance(serialized, bytes):
            # Check if it looks like gzip (magic bytes)
            is_gzip = (
                len(serialized) >= 2
                and serialized[:2] == b"\x1f\x8b"
            )
            extension = ".json.gz" if is_gzip else ".json"
        else:
            extension = ".json"

        # Ensure storage directory exists
        os.makedirs(storage_path, exist_ok=True)

        filename = f"{backup_id}{extension}"
        filepath = os.path.join(storage_path, filename)

        # Write the data
        if isinstance(serialized, bytes):
            with open(filepath, "wb") as fh:
                fh.write(serialized)
        else:
            with open(filepath, "w", encoding="utf-8") as fh:
                fh.write(serialized)

        return {
            "status": "success",
            "path": os.path.abspath(filepath),
            "written": True,
        }
    except Exception as exc:
        return {
            "status": "error",
            "path": "",
            "written": False,
            "error": f"Storage write failed: {exc}",
        }
