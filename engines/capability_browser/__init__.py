"""Capability Browser Engine — W963-30.

Substrate registry browser. Given a goal ("get traffic",
"convert better", "first sale", etc.), returns ranked engines
+ actions that move toward that goal. Exposes the existing
core/capability_registry (104+ entries) to operators AND the
AI brain (W963-28 store_strategist).

This is the substrate gap the bible flagged in line 80-83:
"Theme design-yg mobile app shig bolgo" goes from "AI greps
filenames" → "AI queries the registry and composes."

Bible scoring:
  Q2 (substrate composability): the registry already exists;
     this engine makes it discoverable + searchable +
     composable via a Pattern Q surface.
  Q3 (AI self-learning): the future AI brain queries this
     before composing a plan; baseline ranking is the
     substrate the LLM layers on top of.

CLI:
  shopai capability-browse                       -- list all
  shopai capability-browse "get traffic"          -- search
  shopai capability-browse --kind engine          -- filter
  shopai capability-browse --tag cold_start
  shopai capability-browse --top 5
  shopai capability-browse --json
"""
from .flow import CapabilityBrowserEngine

__all__ = ["CapabilityBrowserEngine"]
