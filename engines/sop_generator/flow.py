"""SOP Generator Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.

Pipeline:
  Input → Pattern Extractor → Procedure Builder → Template Formatter →
  Coverage Checker → Memory Writer → Output

Engine contract:
  Input:  {status, data: {execution_history, operations}, meta, error}
  Output: {status, data: {sops, coverage, gaps}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .pattern_extractor import extract_patterns
from .procedure_builder import build_procedures
from .template_formatter import format_templates
from .coverage_checker import check_coverage
from .memory_reader import read_past_sops
from .memory_writer import write_sop_result


class SopGeneratorEngine:
    """SOP Generator Engine — orchestrator only, no logic."""

    ENGINE_NAME = "sop_generator"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()

        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)
        if payload.get("status") == "fail":
            return self._fail(payload.get("error", "Upstream failure"), 0.0)

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        execution_history = data.get("execution_history", [])
        operations = data.get("operations", [])

        if not operations:
            return self._fail("Operations list is required", 0.0)

        _past = read_past_sops(limit=5)

        # Stage 1: Pattern Extractor
        pattern_result = extract_patterns(execution_history=execution_history, operations=operations)
        if pattern_result.get("status") == "error":
            return self._fail(f"Pattern extraction failed: {pattern_result.get('error', 'unknown')}", time.monotonic() - start)
        patterns = pattern_result.get("patterns", [])

        # Stage 2: Procedure Builder
        proc_result = build_procedures(patterns=patterns, operations=operations)
        if proc_result.get("status") == "error":
            return self._fail(f"Procedure building failed: {proc_result.get('error', 'unknown')}", time.monotonic() - start)
        sops = proc_result.get("sops", [])

        # Stage 3: Template Formatter
        fmt_result = format_templates(sops=sops)
        if fmt_result.get("status") == "error":
            return self._fail(f"Template formatting failed: {fmt_result.get('error', 'unknown')}", time.monotonic() - start)
        formatted_sops = fmt_result.get("formatted_sops", [])

        # Stage 4: Coverage Checker
        cov_result = check_coverage(sops=formatted_sops, operations=operations)
        if cov_result.get("status") == "error":
            return self._fail(f"Coverage check failed: {cov_result.get('error', 'unknown')}", time.monotonic() - start)
        coverage = cov_result.get("coverage", {})
        gaps = cov_result.get("gaps", [])

        # Stage 5: Memory Writer (non-fatal)
        _write_result = write_sop_result(sops=formatted_sops, coverage=coverage, gaps=gaps)

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "sops": formatted_sops,
                "coverage": coverage,
                "gaps": gaps,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        return {
            "status": "error", "data": None,
            "meta": {"engine": self.ENGINE_NAME, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
            "error": reason,
        }
