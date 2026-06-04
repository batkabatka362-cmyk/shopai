"""Strategist Memory Engine — W963-43.

Persistent per-(store, signal) recommendation history. Records:

  - When store_strategist made a recommendation
  - What the recommendation was (action, signal, confidence)
  - What happened next (outcome polarity if known)

Exposes:
  - record(store, recommendation)  — append a new entry
  - recall(store, signal, k)       — last K matching entries
  - signal_stats(store, signal)    — positive_count, total

Future LLM brain queries this to know "did I make this same
recommendation last week? Did it work?" before generating a
new one. The deterministic baseline is the substrate the AI
layers on top of.

Bible scoring:
  Q3 (AI self-learning): substrate for the AI to learn over
     time. Each call writes; future calls read. Cumulative
     knowledge accrues without operator action.
  Q4 (resilience): if a recommendation repeatedly produces
     negative outcomes, future runs can skip it.

CLI:
  shopai memory-strategist                       -- list per-store
  shopai memory-strategist --store STORE --recall N
  shopai memory-strategist --signal funnel
  shopai memory-strategist --json
"""
from .flow import StrategistMemoryEngine

__all__ = ["StrategistMemoryEngine"]
