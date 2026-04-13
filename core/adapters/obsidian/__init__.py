"""Obsidian vault adapter — local knowledge base integration.

Reads markdown notes from an Obsidian vault on disk, parses
YAML frontmatter / wikilinks / tags, and exposes them through
the standard adapter pattern. Bidirectional: can also write
learned knowledge back as markdown notes.

Capabilities:

  * ``VAULT_READ_NOTES``   — list / filter notes from the vault
  * ``VAULT_SEARCH_NOTES`` — full-text search across note content
  * ``VAULT_WRITE_NOTE``   — create or update a markdown note

Configuration:

  * ``OBSIDIAN_VAULT_PATH`` — absolute path to the vault root
"""
from __future__ import annotations

from .vault import ObsidianVaultAdapter

__all__ = ["ObsidianVaultAdapter"]
