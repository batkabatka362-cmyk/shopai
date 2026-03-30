"""RootCauseAnalyzer — traces errors back to root cause."""
from __future__ import annotations

import re
from typing import Any


class RootCauseAnalyzer:
    """Analyzes error chains to find root cause."""

    CAUSE_MAP = {
        "input_validation": [
            {"trigger": "missing required field", "root": "Caller did not provide required data", "fix_area": "caller"},
            {"trigger": "input data is empty", "root": "Empty data passed to engine", "fix_area": "caller"},
        ],
        "model_failure": [
            {"trigger": "connection refused", "root": "Model server not running", "fix_area": "infrastructure"},
            {"trigger": "timeout", "root": "Model server overloaded or prompt too long", "fix_area": "performance"},
            {"trigger": "model inference not yet connected", "root": "Using placeholder — connect real model", "fix_area": "configuration"},
        ],
        "data_quality": [
            {"trigger": "negative price", "root": "Data source has invalid pricing data", "fix_area": "data_pipeline"},
            {"trigger": "parse error", "root": "Input format doesn't match expected schema", "fix_area": "data_pipeline"},
            {"trigger": "type error", "root": "Wrong data type passed — check data cleaning", "fix_area": "data_pipeline"},
        ],
        "engine_crash": [
            {"trigger": "keyerror", "root": "Engine assumes key exists but data doesn't have it", "fix_area": "engine_code"},
            {"trigger": "attributeerror", "root": "Object doesn't have expected attribute — check types", "fix_area": "engine_code"},
            {"trigger": "indexerror", "root": "List access out of bounds — check data length", "fix_area": "engine_code"},
        ],
        "configuration": [
            {"trigger": "unknown engine", "root": "Engine not registered in registry", "fix_area": "registry"},
            {"trigger": "no route", "root": "Task router has no mapping for this task type", "fix_area": "task_router"},
        ],
    }

    def analyze(self, error: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Find root cause of an error."""
        error_lower = str(error).lower()
        ctx = context or {}

        for category, causes in self.CAUSE_MAP.items():
            for cause in causes:
                if cause["trigger"] in error_lower:
                    return {
                        "category": category,
                        "trigger": cause["trigger"],
                        "root_cause": cause["root"],
                        "fix_area": cause["fix_area"],
                        "engine": ctx.get("engine_name", "unknown"),
                        "step": ctx.get("step_name", "unknown"),
                        "chain": self._build_cause_chain(error, cause, ctx),
                        "confidence": "high",
                    }

        return {
            "category": "unknown",
            "trigger": error_lower[:80],
            "root_cause": "Unable to determine — manual investigation needed",
            "fix_area": "unknown",
            "engine": ctx.get("engine_name", "unknown"),
            "step": ctx.get("step_name", "unknown"),
            "chain": [str(error)[:200]],
            "confidence": "low",
        }

    def analyze_chain(self, errors: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyze a chain of errors to find the original root cause."""
        if not errors:
            return {"root_cause": "No errors to analyze"}

        analyses = []
        for err in errors:
            error_msg = err.get("error", err.get("message", str(err)))
            analysis = self.analyze(error_msg, err)
            analyses.append(analysis)

        # Root cause is usually the first non-unknown error
        root = next(
            (a for a in analyses if a["confidence"] == "high"),
            analyses[0] if analyses else {"root_cause": "unknown"},
        )

        return {
            "root_cause": root["root_cause"],
            "fix_area": root.get("fix_area", "unknown"),
            "error_chain_length": len(analyses),
            "cascade_path": [a.get("trigger", "?") for a in analyses],
            "analyses": analyses,
        }

    @staticmethod
    def _build_cause_chain(error: str, cause: dict, context: dict) -> list[str]:
        chain = []
        engine = context.get("engine_name", "")
        step = context.get("step_name", "")

        if engine:
            chain.append(f"Engine '{engine}' encountered error")
        if step:
            chain.append(f"During step '{step}'")
        chain.append(f"Trigger: {cause['trigger']}")
        chain.append(f"Root cause: {cause['root']}")
        chain.append(f"Fix area: {cause['fix_area']}")

        return chain
