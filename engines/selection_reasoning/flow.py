"""Selection Reasoning Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Narrative Builder → Evidence Compiler → Comparison Builder →
  Confidence Assessor → Memory Writer → Output

Engine contract:
  Input:  {status, data: {decisions, evidence}, meta, error}
  Output: {status, data: {narratives: [{product_id, reasoning, confidence}]}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .narrative_builder import build_narratives
from .evidence_compiler import compile_evidence
from .comparison_builder import build_comparisons
from .confidence_assessor import assess_confidence
from .memory_reader import read_past_reasoning
from .memory_writer import write_reasoning_result


class SelectionReasoningEngine:
    """Selection Reasoning Engine — orchestrator only, no logic."""

    ENGINE_NAME = "selection_reasoning"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full reasoning pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            ReasoningOutput dict.
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

        decisions = data.get("decisions", [])
        evidence = data.get("evidence", [])

        if not decisions:
            return self._fail("Decision list is required", 0.0)

        # ---- Stage 1: Read past reasoning (non-blocking) ----
        _past = read_past_reasoning(limit=5)

        # ---- Stage 2: Narrative Builder ----
        narr_result = build_narratives(
            decisions=decisions,
            evidence=evidence,
        )
        if narr_result.get("status") == "error":
            return self._fail(
                f"Narrative building failed: {narr_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        narratives = narr_result.get("narratives", [])

        # ---- Stage 3: Evidence Compiler ----
        ev_result = compile_evidence(
            decisions=decisions,
            evidence=evidence,
        )
        if ev_result.get("status") == "error":
            return self._fail(
                f"Evidence compilation failed: {ev_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        compilations = ev_result.get("compilations", [])

        # ---- Stage 4: Comparison Builder ----
        comp_result = build_comparisons(
            decisions=decisions,
            evidence=evidence,
        )
        if comp_result.get("status") == "error":
            return self._fail(
                f"Comparison building failed: {comp_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        _comparisons = comp_result.get("comparisons", [])

        # ---- Stage 5: Confidence Assessor ----
        conf_result = assess_confidence(
            decisions=decisions,
            compilations=compilations,
            narratives=narratives,
        )
        if conf_result.get("status") == "error":
            return self._fail(
                f"Confidence assessment failed: {conf_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        assessments = conf_result.get("assessments", [])

        # ---- Stage 6: Assemble reasoning output ----
        narr_map = {str(n.get("product_id", "")): n for n in narratives}
        conf_map = {str(a.get("product_id", "")): a for a in assessments}
        comp_map = {str(c.get("product_id", "")): c for c in compilations}

        output_narratives: list[dict[str, Any]] = []
        for decision in decisions:
            pid = str(decision.get("product_id", "unknown"))
            narr = narr_map.get(pid, {})
            conf = conf_map.get(pid, {})
            comp = comp_map.get(pid, {})

            key_evidence: list[str] = []
            for ev in comp.get("supporting_evidence", [])[:3]:
                key_evidence.append(
                    f"{ev.get('metric', '')}: {ev.get('interpretation', ev.get('value', ''))}"
                )

            output_narratives.append({
                "product_id": pid,
                "reasoning": narr.get("narrative", "No reasoning available."),
                "confidence": conf.get("overall_confidence", 0.0),
                "key_evidence": key_evidence,
            })

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_reasoning_result(narratives=output_narratives)

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "narratives": output_narratives,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
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
