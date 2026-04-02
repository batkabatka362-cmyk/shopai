"""Global Brain — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Two modes:
  INGEST:   Engine Outputs → Data Ingestor → Knowledge Extractor →
            Pattern Aggregator → Knowledge Structurer → Deduplicator →
            Scorer → Vector Store + Memory Store → Output

  RETRIEVE: Query → Retriever → Context Provider → Output

Engine contract:
  Input:  {status, data: {mode, ...}, meta, error}
  Output: {status, data: {...}, meta: {engine, ...}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .data_ingestor import ingest_engine_output
from .knowledge_extractor import extract_knowledge
from .pattern_aggregator import aggregate_patterns
from .knowledge_structurer import structure_knowledge
from .deduplicator import deduplicate_knowledge
from .scorer import score_knowledge
from .memory_writer import write_to_stores
from .memory_reader import read_from_stores
from .retriever import retrieve_knowledge
from .context_provider import build_context


class GlobalBrainEngine:
    """Global Brain Engine — orchestrator only, no logic."""

    ENGINE_NAME = "global_brain"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the global brain pipeline in ingest or retrieve mode.

        Args:
            input_payload: Engine contract input dict.

        Returns:
            GlobalBrainOutput dict.
        """
        start = time.monotonic()

        # ---- Stage 0: Input validation (no mutation) ----
        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)

        if payload.get("status") == "fail":
            return self._fail(
                payload.get("error", "Upstream failure"), 0.0,
            )

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        mode = str(data.get("mode", "")).lower()
        if mode not in ("ingest", "retrieve"):
            return self._fail(
                f"Unknown mode '{mode}'. Must be 'ingest' or 'retrieve'.",
                0.0,
            )

        # ---- Dispatch to mode handler ----
        if mode == "ingest":
            return self._run_ingest(data, start)
        else:
            return self._run_retrieve(data, start)

    # -------------------------------------------------------------------
    # INGEST mode
    # -------------------------------------------------------------------

    def _run_ingest(
        self, data: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        """Run the full ingest pipeline.

        Pipeline:
            Engine Outputs → Data Ingestor → Knowledge Extractor →
            Pattern Aggregator → Knowledge Structurer → Deduplicator →
            Scorer → Memory Writer → Output
        """
        source_engine = str(data.get("source_engine", "unknown"))
        engine_data = data.get("data", {})

        if not isinstance(engine_data, dict):
            return self._fail("Ingest 'data.data' must be a dict", time.monotonic() - start)

        # ---- Stage 1: Data Ingestor ----
        ingest_result = ingest_engine_output(
            source_engine=source_engine,
            data=engine_data,
        )
        if ingest_result.get("status") == "error":
            return self._fail(
                f"Ingestion failed: {ingest_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        raw_items = ingest_result.get("raw_items", [])
        if not raw_items:
            return self._fail(
                "No knowledge items extracted from input",
                time.monotonic() - start,
            )

        # ---- Stage 2: Knowledge Extractor (Mistral) ----
        extract_result = extract_knowledge(raw_items=raw_items)
        if extract_result.get("status") == "error":
            return self._fail(
                f"Extraction failed: {extract_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        extracted_items = extract_result.get("extracted_items", [])

        # ---- Stage 3: Pattern Aggregator (Mistral) ----
        pattern_result = aggregate_patterns(extracted_items=extracted_items)
        if pattern_result.get("status") == "error":
            return self._fail(
                f"Pattern aggregation failed: {pattern_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        patterns = pattern_result.get("patterns", [])

        # ---- Stage 4: Knowledge Structurer (Qwen) ----
        structure_result = structure_knowledge(extracted_items=extracted_items)
        if structure_result.get("status") == "error":
            return self._fail(
                f"Structuring failed: {structure_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        structured_items = structure_result.get("structured_items", [])

        # ---- Stage 5: Deduplicator ----
        dedup_result = deduplicate_knowledge(structured_items=structured_items)
        unique_items = dedup_result.get("unique_items", [])

        # ---- Stage 6: Scorer ----
        score_result = score_knowledge(unique_items=unique_items)
        scored_items = score_result.get("scored_items", [])

        # ---- Stage 7: Memory Writer (non-fatal) ----
        write_result = write_to_stores(scored_items=scored_items)
        embeddings_stored = write_result.get("vector_written", 0)

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        # Build knowledge output (strip internal scoring details)
        knowledge_output = [
            {
                "knowledge_id": item.get("knowledge_id", ""),
                "content": item.get("content", ""),
                "knowledge_type": item.get("knowledge_type", ""),
                "category": item.get("category", ""),
                "subcategory": item.get("subcategory", ""),
                "source_engine": item.get("source_engine", ""),
                "confidence": item.get("confidence", 0.0),
                "score": item.get("score", 0.0),
                "tags": item.get("tags", []),
            }
            for item in scored_items
        ]

        return {
            "status": "success",
            "data": {
                "knowledge": knowledge_output,
                "patterns": patterns,
                "embeddings_stored": embeddings_stored,
                "context_ready": embeddings_stored > 0,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "mode": "ingest",
                "source_engine": source_engine,
                "items_ingested": len(raw_items),
                "items_extracted": len(extracted_items),
                "items_stored": len(scored_items),
                "patterns_detected": len(patterns),
                "duplicates_removed": dedup_result.get("duplicates_removed", 0),
                "near_duplicates_merged": dedup_result.get("near_duplicates_merged", 0),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    # -------------------------------------------------------------------
    # RETRIEVE mode
    # -------------------------------------------------------------------

    def _run_retrieve(
        self, data: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        """Run the retrieve pipeline.

        Pipeline:
            Query → Retriever → Context Provider → Output
        """
        query = str(data.get("query", "")).strip()
        requesting_engine = str(data.get("requesting_engine", "unknown"))
        max_results = int(data.get("max_results", 5))

        if not query:
            return self._fail(
                "Retrieve mode requires a non-empty 'query'",
                time.monotonic() - start,
            )

        # ---- Stage 1: Retriever ----
        retrieval_result = retrieve_knowledge(
            query=query,
            max_results=max_results,
        )
        if retrieval_result.get("status") == "error":
            return self._fail(
                f"Retrieval failed: {retrieval_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        retrieval_results = retrieval_result.get("retrieval_results", [])

        # ---- Stage 2: Load stored patterns for context ----
        stored_data = read_from_stores(query=query, top_k=max_results)
        # Patterns are stored across memory; load from memory store
        # to find any previously detected patterns
        stored_patterns = _load_stored_patterns()

        # ---- Stage 3: Context Provider (LLaMA) ----
        context_result = build_context(
            retrieval_results=retrieval_results,
            patterns=stored_patterns,
            requesting_engine=requesting_engine,
        )
        if context_result.get("status") == "error":
            return self._fail(
                f"Context building failed: {context_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 4: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "context": context_result.get("context", []),
                "related_patterns": context_result.get("related_patterns", []),
                "recommendations": context_result.get("recommendations", []),
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "mode": "retrieve",
                "query": query,
                "requesting_engine": requesting_engine,
                "results_returned": len(retrieval_results),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    # -------------------------------------------------------------------
    # Error output
    # -------------------------------------------------------------------

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        """Return a standardized failure output."""
        return {
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }


# ---------------------------------------------------------------------------
# Module-level helper (not business logic, just data loading for flow)
# ---------------------------------------------------------------------------

def _load_stored_patterns() -> list[dict[str, Any]]:
    """Load previously stored patterns from memory.

    Patterns are stored as knowledge items with knowledge_type markers.
    This scans memory for pattern-type entries.
    """
    try:
        from .memory_store import MemoryStore
        store = MemoryStore()
        all_records = store.read_all(limit=200)
        patterns: list[dict[str, Any]] = []
        for record in all_records:
            knowledge = record.get("knowledge", {})
            # Check if this is a pattern-sourced item
            tags = knowledge.get("tags", [])
            if "pattern" in tags or knowledge.get("knowledge_type") == "correlation":
                patterns.append({
                    "pattern_id": knowledge.get("knowledge_id", ""),
                    "description": knowledge.get("content", ""),
                    "pattern_type": "recurring",
                    "supporting_items": [knowledge.get("knowledge_id", "")],
                    "frequency": 1,
                    "confidence": knowledge.get("confidence", 0.5),
                    "first_seen": knowledge.get("timestamp", ""),
                    "last_seen": knowledge.get("timestamp", ""),
                })
        return patterns
    except Exception:
        return []
