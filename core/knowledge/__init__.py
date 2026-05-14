"""Knowledge layer — bridges ShopAI state into external review tools.

First citizen: Obsidian-compatible Markdown vault export. The user's
17-day plan calls for an Obsidian + NotebookLM memory layer; this
module is the export bridge that produces the Markdown surface.
"""
from core.knowledge.exporter import ExportSummary, ObsidianExporter

__all__ = ["ExportSummary", "ObsidianExporter"]
