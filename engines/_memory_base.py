"""Shared helpers for per-engine ``.memory/`` loose-JSON stores.

Every engine under ``engines/`` has a ``memory_reader.py`` that walks its
own ``.memory/`` directory full of ``<hash>.json`` records. The original
pattern loaded **every** record on every call, then sorted and took the
top N — fine at 10 records, crippling at thousands (a single autonomous
cycle that touches 10 engines with 5k records each stalls for ~15s on
disk I/O it immediately discards).

This module centralises the load primitive so each engine can delegate
instead of keeping a near-identical O(N) copy. The two shared functions:

    ``load_recent_records(memory_dir, max_files=None)``
        Walk the directory with ``os.scandir`` (one syscall per entry
        instead of ``listdir + getmtime``), optionally keeping only the
        N most-recently-modified ``.json`` files. Returns a list of
        parsed dicts (malformed JSON / unreadable files silently skipped
        so a single bad record never takes down the engine).

    ``compute_input_hash(data)``
        Deterministic 16-hex-char sha256 over a JSON dump. Each engine's
        ``find_similar_past_run`` calls this to spot a duplicate input.
        Lifted verbatim from the boilerplate that previously lived in
        every engine.

The ``max_files`` cap is a pure speed knob — when the caller only needs
the top-K after an internal ``timestamp`` sort, reading ``K * 3`` recent
files is enough to paper over any mtime/timestamp skew while bounding
I/O to a constant per call.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any


def load_recent_records(
    memory_dir: str,
    max_files: int | None = None,
) -> list[dict[str, Any]]:
    """Load parsed JSON records from a ``.memory`` directory.

    Args:
        memory_dir: absolute path to the engine's ``.memory/`` directory.
        max_files: if set, cap the read to the N most-recently-modified
            files (by mtime). ``None`` preserves the legacy "read every
            file" contract for callers that genuinely need a full scan
            (e.g. inventory summaries over all history).

    Returns: a list of dicts. Empty on missing directory or scan error.
    Malformed JSON / unreadable files are silently skipped.
    """
    if not os.path.isdir(memory_dir):
        return []

    # scandir() returns filetype + stat in one syscall per entry,
    # vs listdir() + getmtime() which does two. On 5k-file directories
    # this halves the walk cost.
    candidates: list[tuple[float, str]] = []
    try:
        with os.scandir(memory_dir) as it:
            for entry in it:
                if not entry.name.endswith(".json"):
                    continue
                try:
                    mtime = entry.stat().st_mtime
                except OSError:
                    continue
                candidates.append((mtime, entry.path))
    except OSError:
        return []

    if max_files is not None and len(candidates) > max_files:
        candidates.sort(key=lambda t: t[0], reverse=True)
        candidates = candidates[:max_files]

    records: list[dict[str, Any]] = []
    for _mtime, fpath in candidates:
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    records.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return records


def compute_input_hash(input_data: dict[str, Any]) -> str:
    """Produce a deterministic 16-char hex hash of an input payload.

    Used by each engine's ``find_similar_past_run`` to spot a duplicate
    input without comparing full payloads. Matches the historical
    per-engine implementation so existing recorded ``input_hash`` values
    stay valid.
    """
    try:
        serialised = json.dumps(input_data, sort_keys=True, default=str)
        return hashlib.sha256(serialised.encode()).hexdigest()[:16]
    except Exception:
        return "unknown"
