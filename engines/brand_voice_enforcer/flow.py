"""Brand Voice Enforcer Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Content + Voice → Content Analyzer → Tone Checker → Vocabulary Filter →
  Consistency Scorer → Memory Writer → Output

Engine contract:
  Input:  {status, data: {content: [{type, text}], brand_voice: {tone, vocabulary, dos, donts}}, meta, error}
  Output: {status, data: {scores, overall_score, corrections, recommendations}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .content_analyzer import analyze_content
from .tone_checker import check_tone
from .vocabulary_filter import filter_vocabulary
from .consistency_scorer import score_consistency
from .memory_reader import read_past_enforcements
from .memory_writer import write_enforcement_result


class BrandVoiceEnforcerEngine:
    """Brand Voice Enforcer Engine — orchestrator only, no logic."""

    ENGINE_NAME = "brand_voice_enforcer"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full voice enforcement pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            VoiceEnforcerOutput dict.
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

        content = data.get("content", [])
        if not content:
            return self._fail("Content list is required", 0.0)

        brand_voice = data.get("brand_voice", {})
        if not isinstance(brand_voice, dict):
            return self._fail("brand_voice must be a dict", 0.0)

        # ---- Stage 1: Read past enforcements (non-blocking) ----
        _past = read_past_enforcements(limit=5)

        # ---- Stage 2: Content Analyzer ----
        analysis_result = analyze_content(
            content=content,
            brand_voice=brand_voice,
        )
        if analysis_result.get("status") == "error":
            return self._fail(
                f"Content analysis failed: {analysis_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        analyses = analysis_result.get("analyses", [])

        # ---- Stage 3: Tone Checker ----
        tone_result = check_tone(
            content=content,
            brand_voice=brand_voice,
        )
        if tone_result.get("status") == "error":
            return self._fail(
                f"Tone checking failed: {tone_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        tone_checks = tone_result.get("tone_checks", [])

        # ---- Stage 4: Vocabulary Filter ----
        vocab_result = filter_vocabulary(
            content=content,
            brand_voice=brand_voice,
        )
        if vocab_result.get("status") == "error":
            return self._fail(
                f"Vocabulary filtering failed: {vocab_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        vocabulary_results = vocab_result.get("vocabulary_results", [])

        # ---- Stage 5: Consistency Scorer ----
        consistency_result = score_consistency(
            analyses=analyses,
            tone_checks=tone_checks,
            vocabulary_results=vocabulary_results,
            content=content,
        )
        if consistency_result.get("status") == "error":
            return self._fail(
                f"Consistency scoring failed: {consistency_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        scores = consistency_result.get("scores", [])
        overall_score = consistency_result.get("overall_score", 0)
        corrections = consistency_result.get("corrections", [])
        recommendations = consistency_result.get("recommendations", [])

        # ---- Stage 6: Memory Writer (non-fatal) ----
        _write_result = write_enforcement_result(
            scores=scores,
            overall_score=overall_score,
            corrections=corrections,
            recommendations=recommendations,
            content_count=len(content),
        )

        # ---- Stage 7: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "scores": [
                    {
                        "content_idx": s.get("content_idx", 0),
                        "consistency_score": s.get("consistency_score", 0),
                        "issues": s.get("issues", []),
                    }
                    for s in scores
                ],
                "overall_score": overall_score,
                "corrections": corrections,
                "recommendations": recommendations,
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
