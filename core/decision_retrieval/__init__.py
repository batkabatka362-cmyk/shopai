"""Decision-time retrieval (RAG layer).

AGI roadmap Phase 2 layer 2. Before making a decision, engines
ask: "what similar decisions did we make in the past and how did
they turn out?" -- and get back the top-k most relevant past
actions joined with their outcomes.

The retriever is a thin facade over the existing
``pending_actions`` + ``action_outcomes`` tables (PR #57+). It
filters and scores candidates by engine + action_type + capability
+ params overlap + recency, then joins each with its measured
outcomes (revenue impact, polarity).

This is NOT a vector / embedding store. The data volume is small
enough (thousands of actions per engine, not millions) that
deterministic filtering + Jaccard-style overlap is sufficient
and cheap. Future revision can add embeddings without changing
the public surface.
"""
from __future__ import annotations

from .retriever import DecisionRetrieval, retrieve_similar

__all__ = ["DecisionRetrieval", "retrieve_similar"]
