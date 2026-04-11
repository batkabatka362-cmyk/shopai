"""Auto Research Engine — orchestrates the full research pipeline.

This is the FLOW file.  It ONLY orchestrates — no business logic here.
Every step delegates to a dedicated module; this file wires them together.

Pipeline:
  Goal → Query Builder → Search Executor → Content Extractor →
  Content Filter → Feature Builder → Analyzer → Synthesizer →
  Validator → Scorer → Output

Engine contract:
  Input:  ResearchGoal  (query, context, max_sources, depth)
  Output: ResearchOutput (status, data, meta, error)

Model usage summary:
  - Query Builder:  Qwen   (structured query generation)
  - Analyzer:       Mistral (pattern detection & validation)
  - Synthesizer:    LLaMA  (creative narrative synthesis)
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .types import ResearchGoal, ResearchOutput
from .query_builder import build_queries
from .search_executor import execute_searches
from .content_extractor import extract_content
from .content_filter import filter_content
from .feature_builder import build_features
from .analyzer import analyze_features
from .synthesizer import synthesize
from .validator import validate_output
from .scorer import score_results
from .memory_writer import write_to_memory
from .memory_reader import find_related_research


class AutoResearchEngine:
    """Auto Research Engine — orchestrator only, no logic."""

    ENGINE_NAME = "auto_research"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full research pipeline.

        Accepts a raw dict (will be validated and deep-copied).
        Returns a ``ResearchOutput``-shaped dict — always a structured
        dict, never raises.
        """
        start = time.monotonic()

        try:
            return self._execute_pipeline(input_payload, start)
        except Exception as exc:
            return self._error_output(
                reason=f"Unexpected pipeline error: {exc}",
                elapsed=time.monotonic() - start,
            )

    # ------------------------------------------------------------------
    # Private pipeline
    # ------------------------------------------------------------------

    def _execute_pipeline(
        self,
        input_payload: dict[str, Any],
        start: float,
    ) -> dict[str, Any]:
        """Run each pipeline stage in sequence, short-circuiting on failure."""

        # Stage 0: Input validation & deep copy
        goal = self._validate_input(input_payload)
        if goal is None:
            return self._error_output(
                reason="Invalid input: requires 'query' (non-empty string).",
                elapsed=time.monotonic() - start,
            )

        original_query: str = goal["query"]

        # Stage 0.5: Check memory for recent related research
        prior = find_related_research(original_query, min_confidence=0.5, max_results=3)

        # Stage 1: Query Builder  (model: Qwen)
        queries = build_queries(goal)
        if not queries:
            return self._error_output(
                reason="Query builder produced no queries from the given goal.",
                elapsed=time.monotonic() - start,
            )

        # Stage 2: Search Executor  (no model — I/O layer)
        max_per_query = max(goal.get("max_sources", 10) // max(len(queries), 1), 2)
        raw_results = execute_searches(queries, max_results_per_query=max_per_query)
        if not raw_results:
            return self._error_output(
                reason="Search executor returned no results.",
                elapsed=time.monotonic() - start,
            )

        # Stage 3: Content Extractor  (no model — text processing)
        extracted = extract_content(raw_results)
        if not extracted:
            return self._error_output(
                reason="Content extractor could not extract usable content.",
                elapsed=time.monotonic() - start,
            )

        # Stage 4: Content Filter  (no model — heuristic scoring)
        filtered = filter_content(extracted, original_query)
        if not filtered:
            return self._error_output(
                reason="All extracted content was below quality/relevance thresholds.",
                elapsed=time.monotonic() - start,
            )

        # Stage 5: Feature Builder  (model: Qwen)
        # This is the ONLY bridge between raw content and analysis.
        features = build_features(filtered, original_query)
        if not features:
            return self._error_output(
                reason="Feature builder could not produce any features.",
                elapsed=time.monotonic() - start,
            )

        # Stage 6: Analyzer  (model: Mistral)
        analysis = analyze_features(features, original_query)

        # Stage 7: Synthesizer  (model: LLaMA)
        synthesis = synthesize(analysis, features, original_query)

        # Stage 8: Scorer  (no model — numeric scoring)
        score = score_results(features, analysis)

        # Stage 9: Assemble output
        sources = list({f["source_url"] for f in features})
        elapsed = time.monotonic() - start

        output: dict[str, Any] = {
            "status": "success",
            "data": {
                "insight": synthesis["insight"],
                "key_findings": synthesis["key_findings"],
                "recommended_action": synthesis["recommended_action"],
                "confidence": score["confidence"],
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "query": original_query,
                "sources": sources,
                "timestamp": _now(),
                "elapsed_seconds": round(elapsed, 3),
                "models": {
                    "query_builder": "qwen",
                    "analyzer": "mistral",
                    "synthesizer": "llama",
                },
                "pipeline_stats": {
                    "queries_generated": len(queries),
                    "raw_results": len(raw_results),
                    "extracted": len(extracted),
                    "filtered": len(filtered),
                    "features": len(features),
                    "patterns": len(analysis.get("patterns", [])),
                    "contradictions": len(analysis.get("contradictions", [])),
                },
                "score_breakdown": score["detail_breakdown"],
                "prior_research_found": len(prior),
            },
            "error": None,
        }

        # Stage 10: Validator  (model: Mistral)
        validation = validate_output(output)
        if not validation["valid"]:
            return self._error_output(
                reason=f"Validation failed: {'; '.join(validation['issues'])}",
                elapsed=time.monotonic() - start,
            )

        # Stage 11: Persist to memory
        write_to_memory(output)

        return output

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    def _validate_input(self, payload: dict[str, Any]) -> ResearchGoal | None:
        """Validate and normalise the input into a ``ResearchGoal``.

        Returns ``None`` if the input is unusable.
        Never mutates *payload*.
        """
        if not isinstance(payload, dict):
            return None

        safe = copy.deepcopy(payload)

        # Engine contract: payload is {status, data, meta, error}
        data = safe.get("data", safe)  # fallback to raw dict
        if not isinstance(data, dict):
            return None

        query = data.get("query", "") or data.get("goal", "")
        if not isinstance(query, str) or not query.strip():
            return None

        return ResearchGoal(
            query=query.strip(),
            context=str(data.get("context", "")).strip(),
            max_sources=int(data.get("max_sources", 10)),
            depth=str(data.get("depth", "standard")),
        )

    # ------------------------------------------------------------------
    # Error output helper
    # ------------------------------------------------------------------

    def _error_output(self, *, reason: str, elapsed: float) -> dict[str, Any]:
        """Build a well-formed error response."""
        return {
            "status": "fail",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "sources": [],
                "timestamp": _now(),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
