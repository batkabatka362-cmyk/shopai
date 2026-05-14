"""Knowledge layer — bridges ShopAI state into external review tools.

The 17-day plan's step 2 calls for an Obsidian + NotebookLM memory
layer. This package is the bridge:

  * :class:`ObsidianExporter` — dump ShopAI state to a Markdown vault.
  * :class:`InsightDigest` — render a one-page rolling briefing.
  * :class:`ObsidianImporter` — read operator notes back into the
    persistent :class:`NotesStore`.

Round trip: export → operator annotates in Obsidian → import →
``get_default_store().get_engine_notes("cart_recovery")`` returns
the operator's prose, ready to surface in engine output / digest
/ future RAG prompts.
"""
from core.knowledge.digest import DigestStats, InsightDigest
from core.knowledge.exporter import ExportSummary, ObsidianExporter
from core.knowledge.importer import ImportSummary, ObsidianImporter
from core.knowledge.narrative_enricher import (
    enrich_action_dict,
    get_operator_context,
)
from core.knowledge.notes_store import NotesStore, get_default_store

__all__ = [
    "DigestStats",
    "ExportSummary",
    "ImportSummary",
    "InsightDigest",
    "NotesStore",
    "ObsidianExporter",
    "ObsidianImporter",
    "enrich_action_dict",
    "get_default_store",
    "get_operator_context",
]
