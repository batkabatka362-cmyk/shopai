"""ObsidianVaultAdapter — local Obsidian vault as a knowledge base.

Reads / searches / writes markdown notes in an Obsidian vault on
the local filesystem. No network calls, no Obsidian REST plugin
required — just a path to the vault directory.

Capabilities:

  * ``VAULT_READ_NOTES``   — list notes (optionally filtered by
                              folder, tags, or specific path)
  * ``VAULT_SEARCH_NOTES`` — full-text search across note content
  * ``VAULT_WRITE_NOTE``   — create or overwrite a markdown note

Configuration:

  * ``OBSIDIAN_VAULT_PATH`` env var → ``obsidian_vault_path``
    config alias. Must point to an existing directory.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from utils.logger import get_logger

from ..base import (
    AdapterCategory,
    AdapterResult,
    BaseAdapter,
    Capability,
)
from ..config import get_config
from ..errors import (
    AdapterError,
    AdapterNotConfigured,
    AdapterValidationError,
)
from . import parser

logger = get_logger("adapters.obsidian")


class ObsidianVaultAdapter(BaseAdapter):
    """Adapter for reading / writing an Obsidian vault on disk."""

    name = "obsidian"
    category = AdapterCategory.KNOWLEDGE_BASE
    capabilities = {
        Capability.VAULT_READ_NOTES,
        Capability.VAULT_SEARCH_NOTES,
        Capability.VAULT_WRITE_NOTE,
    }
    cost_per_call = 0.0
    priority = 80

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        vault = self._vault_path()
        return vault is not None and vault.is_dir()

    def _vault_path(self) -> Path | None:
        """Resolve the vault root from config."""
        raw = get_config().get("obsidian_vault_path")
        if not raw:
            return None
        p = Path(raw)
        return p if p.is_dir() else None

    # ── Capability dispatch ────────────────────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        vault = self._vault_path()
        if vault is None:
            raise AdapterNotConfigured(
                self.name,
                "vault path not set or not a directory "
                "(set $OBSIDIAN_VAULT_PATH)",
            )

        if capability == Capability.VAULT_READ_NOTES:
            data = self._read_notes(vault, params)
        elif capability == Capability.VAULT_SEARCH_NOTES:
            data = self._search_notes(vault, params)
        elif capability == Capability.VAULT_WRITE_NOTE:
            data = self._write_note(vault, params)
        else:
            raise AdapterValidationError(
                self.name,
                f"unsupported capability: {capability.value}",
            )

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data=data,
        )

    # ── Read ──────────────────────────────────────────────────

    def _read_notes(
        self, vault: Path, params: dict[str, Any],
    ) -> dict[str, Any]:
        """Read notes — either a specific note by path or a
        filtered list."""
        note_path = params.get("path")
        if note_path:
            full = vault / note_path
            if not full.is_file():
                raise AdapterValidationError(
                    self.name,
                    f"note not found: {note_path}",
                )
            # Security: prevent path traversal outside vault.
            try:
                full.resolve().relative_to(vault.resolve())
            except ValueError:
                raise AdapterValidationError(
                    self.name,
                    "path must be inside the vault",
                )
            note = parser.parse_note(full, vault_root=vault)
            return {"notes": [note], "count": 1}

        folder = params.get("folder")
        tags = params.get("tags")
        limit = int(params.get("limit", 50))
        notes = parser.list_notes(
            vault, folder=folder, tags=tags, limit=limit,
        )
        return {"notes": notes, "count": len(notes)}

    # ── Search ────────────────────────────────────────────────

    def _search_notes(
        self, vault: Path, params: dict[str, Any],
    ) -> dict[str, Any]:
        query = params.get("query")
        if not query or not isinstance(query, str):
            raise AdapterValidationError(
                self.name,
                "'query' is required for vault search",
            )
        limit = int(params.get("limit", 20))
        tags = params.get("tags")
        folder = params.get("folder")

        results = parser.search_notes(
            vault, query, limit=limit, tags=tags, folder=folder,
        )
        return {"notes": results, "count": len(results)}

    # ── Write ─────────────────────────────────────────────────

    def _write_note(
        self, vault: Path, params: dict[str, Any],
    ) -> dict[str, Any]:
        title = params.get("title")
        if not title or not isinstance(title, str):
            raise AdapterValidationError(
                self.name,
                "'title' is required for writing a note",
            )
        body = params.get("body", "")
        if not isinstance(body, str):
            raise AdapterValidationError(
                self.name,
                "'body' must be a string",
            )
        frontmatter = params.get("frontmatter") or {}
        folder = params.get("folder", "")

        try:
            written = parser.write_note(
                vault, title, body,
                frontmatter=frontmatter, folder=folder,
            )
        except Exception as exc:
            raise AdapterError(
                self.name,
                f"failed to write note: {exc}",
            ) from exc

        rel = str(written.relative_to(vault))
        logger.info("wrote note: %s", rel)
        return {"path": rel, "title": title}
