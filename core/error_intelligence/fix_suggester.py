"""FixSuggester — suggests fixes for classified errors. READ-ONLY, never applies."""
from __future__ import annotations
from typing import Any

from .error_classifier import ErrorClassifier
from .root_cause import RootCauseAnalyzer


class FixSuggester:
    """Suggests fixes for errors. NEVER modifies code or system — only suggests."""

    FIX_DATABASE = {
        "input_validation": {
            "missing required field": [
                "Check caller is passing all required fields",
                "Add default values for optional fields in InputHandler",
                "Validate data before submitting to engine",
            ],
            "input data is empty": [
                "Ensure data dict is not empty before engine call",
                "Check data pipeline output — may be filtering everything out",
            ],
        },
        "model_failure": {
            "connection refused": [
                "Start model server: ollama serve (for Ollama) or python -m vllm.entrypoints.api_server (for vLLM)",
                "Check model server is running on expected port (11434 for Ollama, 8000 for vLLM)",
                "Verify network connectivity to model server",
            ],
            "timeout": [
                "Reduce prompt length — shorten context",
                "Increase timeout setting in ModelRouter",
                "Check model server load — may need to scale",
            ],
            "model inference not yet connected": [
                "Install Ollama: curl -fsSL https://ollama.com/install.sh | sh",
                "Pull models: ollama pull mistral && ollama pull qwen2.5 && ollama pull llama3.1",
                "System works with computed results until models are connected",
            ],
        },
        "data_quality": {
            "negative price": [
                "Add PipelineValidator before engine processing",
                "Check data source for data corruption",
                "Add auto-repair rule: abs(price) if negative",
            ],
            "type error": [
                "Run DataContext.prepare() before engine — normalizes types",
                "Check data pipeline cleaning stage",
            ],
        },
        "engine_crash": {
            "keyerror": [
                "Use dict.get(key, default) instead of dict[key]",
                "Check if pre-processing added expected keys",
                "Verify input schema matches engine expectations",
            ],
            "attributeerror": [
                "Check object type before attribute access",
                "Verify import paths are correct",
            ],
        },
        "configuration": {
            "unknown engine": [
                "Check engine name spelling in registry",
                "Verify engine module exists in engines/ directory",
                "Run: from engines.registry import is_registered; is_registered('engine_name')",
            ],
        },
    }

    def __init__(self) -> None:
        self._classifier = ErrorClassifier()
        self._root_cause = RootCauseAnalyzer()

    def suggest(self, error: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Suggest fixes for an error. Returns suggestions, never applies them."""
        classification = self._classifier.classify(error)
        root = self._root_cause.analyze(error, context)

        suggestions = self._lookup_fixes(classification["category"], root.get("trigger", ""))

        if not suggestions:
            suggestions = self._generic_suggestions(classification)

        return {
            "error": str(error)[:200],
            "classification": classification,
            "root_cause": root,
            "suggestions": suggestions,
            "auto_fixable": classification["recoverable"],
            "priority": self._priority(classification),
        }

    def suggest_batch(self, errors: list[dict[str, Any]]) -> dict[str, Any]:
        """Suggest fixes for multiple errors. Groups by category."""
        results = []
        for err in errors:
            error_msg = err.get("error", err.get("message", str(err)))
            suggestion = self.suggest(error_msg, err)
            results.append(suggestion)

        by_category: dict[str, list] = {}
        for r in results:
            cat = r["classification"]["category"]
            by_category.setdefault(cat, []).append(r)

        return {
            "total_errors": len(results),
            "by_category": {k: len(v) for k, v in by_category.items()},
            "top_priority": sorted(results, key=lambda x: x["priority"])[:5],
            "all_suggestions": results,
        }

    def _lookup_fixes(self, category: str, trigger: str) -> list[str]:
        category_fixes = self.FIX_DATABASE.get(category, {})
        for pattern, fixes in category_fixes.items():
            if pattern in trigger.lower():
                return fixes
        # Return all fixes for the category if no specific match
        all_fixes = []
        for fixes in category_fixes.values():
            all_fixes.extend(fixes)
        return all_fixes[:5]

    @staticmethod
    def _generic_suggestions(classification: dict) -> list[str]:
        severity = classification["severity"]
        if severity == "critical":
            return [
                "Check system logs for stack trace",
                "Verify all dependencies are installed",
                "Run system health check: SystemMonitor().full_check()",
            ]
        if severity == "high":
            return [
                "Check engine input data format",
                "Verify model server is running",
                "Review recent changes to affected engine",
            ]
        return [
            "Check input data quality",
            "Review engine logs for details",
        ]

    @staticmethod
    def _priority(classification: dict) -> int:
        """Lower number = higher priority."""
        severity_map = {"critical": 1, "high": 2, "medium": 3, "low": 4}
        return severity_map.get(classification["severity"], 5)
