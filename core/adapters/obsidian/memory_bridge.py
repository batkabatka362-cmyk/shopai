"""VaultMemoryBridge — bidirectional sync between Obsidian vault
and ShopAI's UnifiedMemory.

Two operations:

  * **import_vault** — scans ``.md`` files, classifies each via
    QualityEngine, ingests KNOWLEDGE + SIGNAL records into
    UnifiedMemory (NOISE is skipped).
  * **export_knowledge** — queries UnifiedMemory for high-quality
    learned knowledge and writes each item as a markdown note
    into a designated vault subfolder.

Both operations are idempotent: import skips notes whose
content hash hasn't changed since the last run; export checks
for existing notes before writing.

Design notes
------------

* **No direct dependency on UnifiedMemory at import time** — the
  bridge receives the memory instance as a parameter so tests
  can inject a mock.
* **QualityEngine** usage is best-effort: if the engine isn't
  available, all notes are classified as KNOWLEDGE.
* **Thread-safe** — no shared mutable state. All state flows
  through the vault filesystem and the memory instance.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.logger import get_logger

from . import parser

logger = get_logger("adapters.obsidian.bridge")

# File that tracks which notes have been imported and their
# content hashes, so re-import skips unchanged notes.
_IMPORT_STATE_FILE = ".shopai_import_state.json"


class VaultMemoryBridge:
    """Bidirectional sync between an Obsidian vault and
    UnifiedMemory."""

    def __init__(self, vault_path: str | Path) -> None:
        self.vault_path = Path(vault_path)

    # ── Import: vault → memory ────────────────────────────────

    def import_vault(
        self,
        memory: Any,
        *,
        folder: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Scan vault notes and ingest into UnifiedMemory.

        Parameters
        ----------
        memory
            A ``UnifiedMemory`` instance (or any object with an
            ``ingest(category, data, source)`` method).
        folder : str, optional
            Only import notes from this subfolder.
        tags : list[str], optional
            Only import notes that have ALL of these tags.

        Returns
        -------
        dict with ``imported``, ``skipped``, ``errors`` counts.
        """
        state = self._load_import_state()
        search_root = self.vault_path / folder if folder else self.vault_path

        if not search_root.is_dir():
            return {"imported": 0, "skipped": 0, "errors": 0}

        imported = 0
        skipped = 0
        errors = 0

        for md_path in search_root.rglob("*.md"):
            parts = md_path.relative_to(self.vault_path).parts
            if any(p.startswith(".") for p in parts):
                continue

            try:
                note = parser.parse_note(md_path, vault_root=self.vault_path)
            except Exception:  # noqa: BLE001
                errors += 1
                continue

            # Tag filter
            if tags:
                note_tags = set(note.get("tags", []))
                if not all(t in note_tags for t in tags):
                    continue

            # Idempotency: skip if content hash unchanged
            rel_path = note["path"]
            content_hash = note["content_hash"]
            if state.get(rel_path) == content_hash:
                skipped += 1
                continue

            # Classify via QualityEngine (best-effort)
            mem_class = self._classify_note(note)
            if mem_class == "noise":
                skipped += 1
                state[rel_path] = content_hash
                continue

            # Ingest into memory
            try:
                memory.ingest(
                    category="vault_note",
                    data={
                        "title": note["title"],
                        "body": note["body"],
                        "tags": note["tags"],
                        "wikilinks": note["wikilinks"],
                        "frontmatter": note["frontmatter"],
                        "vault_path": rel_path,
                        "content_hash": content_hash,
                        "memory_class": mem_class,
                    },
                    source="obsidian_vault",
                )
                state[rel_path] = content_hash
                imported += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("failed to ingest %s: %s", rel_path, exc)
                errors += 1

        self._save_import_state(state)
        logger.info(
            "vault import: %d imported, %d skipped, %d errors",
            imported, skipped, errors,
        )
        return {"imported": imported, "skipped": skipped, "errors": errors}

    # ── Export: memory → vault ────────────────────────────────

    def export_knowledge(
        self,
        memory: Any,
        *,
        folder: str = "ShopAI/Learned",
        limit: int = 50,
    ) -> dict[str, Any]:
        """Export high-quality knowledge from memory as vault notes.

        Parameters
        ----------
        memory
            A ``UnifiedMemory`` instance (or any object with a
            ``retrieve(category, context)`` method).
        folder : str
            Subfolder in the vault for exported notes.
        limit : int
            Max notes to export per run.

        Returns
        -------
        dict with ``exported`` and ``skipped`` counts.
        """
        try:
            result = memory.retrieve("vault_note", {"source": "learned"})
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to retrieve knowledge: %s", exc)
            return {"exported": 0, "skipped": 0}

        cases = result.get("best_cases", [])
        if not cases:
            return {"exported": 0, "skipped": 0}

        target_dir = self.vault_path / folder
        exported = 0
        skipped_count = 0

        for case in cases[:limit]:
            data = case if isinstance(case, dict) else {}
            title = data.get("title", "") or data.get("category", "Untitled")
            if not title:
                skipped_count += 1
                continue

            # Check if already exported
            safe_name = parser._sanitise_filename(title)
            target = target_dir / f"{safe_name}.md"
            if target.exists():
                skipped_count += 1
                continue

            body = data.get("body", "") or data.get("value", "")
            if isinstance(body, dict):
                body = json.dumps(body, indent=2, ensure_ascii=False)

            frontmatter = {
                "title": title,
                "source": "shopai",
                "exported_at": datetime.now(tz=timezone.utc).isoformat(),
                "tags": ["shopai", "learned"],
            }
            if data.get("confidence"):
                frontmatter["confidence"] = float(data["confidence"])

            try:
                parser.write_note(
                    self.vault_path, title, str(body),
                    frontmatter=frontmatter, folder=folder,
                )
                exported += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("failed to export %r: %s", title, exc)

        logger.info(
            "vault export: %d exported, %d skipped",
            exported, skipped_count,
        )
        return {"exported": exported, "skipped": skipped_count}

    # ── QualityEngine classification ──────────────────────────

    @staticmethod
    def _classify_note(note: dict[str, Any]) -> str:
        """Classify a note using QualityEngine if available.

        Returns one of: ``"knowledge"``, ``"error"``, ``"signal"``,
        ``"noise"``. Falls back to ``"knowledge"`` if the engine
        is not importable.
        """
        try:
            from core.memory.quality_engine import (
                MemoryRecord,
                classify,
            )
            record = MemoryRecord(
                kind="vault_note",
                data=note,
                source="obsidian_vault",
            )
            return classify(record).value
        except Exception:  # noqa: BLE001
            # QualityEngine not available — treat all as knowledge.
            return "knowledge"

    # ── Import state persistence ──────────────────────────────

    def _load_import_state(self) -> dict[str, str]:
        """Load the hash→path mapping from the vault's state file."""
        state_file = self.vault_path / _IMPORT_STATE_FILE
        if not state_file.is_file():
            return {}
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _save_import_state(self, state: dict[str, str]) -> None:
        """Persist the hash→path mapping."""
        state_file = self.vault_path / _IMPORT_STATE_FILE
        try:
            state_file.write_text(
                json.dumps(state, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to save import state: %s", exc)
