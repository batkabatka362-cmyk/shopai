"""Backup/Recovery Engine — storage writer.

Writes serialized backup data to disk with proper naming conventions.
"""
from __future__ import annotations

import os
from typing import Any


def write_backup(
    serialized: bytes | str,
    backup_id: str,
    storage_path: str,
) -> dict[str, Any]:
    """Write serialized backup data to the storage path.

    Args:
        serialized: The serialized data (bytes if compressed, str if raw JSON).
        backup_id: Unique backup identifier.
        storage_path: Directory to write the backup file.

    Returns:
        Structured dict confirming the write.
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

        # Ensure storage directory exists
        os.makedirs(storage_path, exist_ok=True)

        # Determine filename based on data type
        is_compressed = isinstance(serialized, bytes)
        if is_compressed:
            filename = f"{backup_id}.json.gz"
        else:
            filename = f"{backup_id}.json"

        filepath = os.path.join(storage_path, filename)

        # Write the file
        if is_compressed:
            with open(filepath, "wb") as fh:
                fh.write(serialized)
        else:
            with open(filepath, "w", encoding="utf-8") as fh:
                fh.write(serialized)

        # Verify file was written
        if not os.path.isfile(filepath):
            return {
                "status": "error",
                "path": filepath,
                "written": False,
                "error": "File not found after write",
            }

        return {
            "status": "success",
            "path": filepath,
            "written": True,
        }
    except Exception as exc:
        return {
            "status": "error",
            "path": "",
            "written": False,
            "error": f"Storage write failed: {exc}",
        }
