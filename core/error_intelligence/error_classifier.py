"""ErrorClassifier — classifies errors into actionable categories."""
from __future__ import annotations

import re
from typing import Any


class ErrorClassifier:
    """Classifies errors by type, severity, and recoverability."""

    CATEGORIES = {
        "input_validation": {
            "patterns": [r"missing required field", r"input validation", r"empty", r"required"],
            "severity": "medium",
            "recoverable": True,
        },
        "model_failure": {
            "patterns": [r"model inference", r"timeout", r"connection refused", r"ollama", r"vllm"],
            "severity": "high",
            "recoverable": True,
        },
        "data_quality": {
            "patterns": [r"invalid format", r"parse error", r"type error", r"negative price", r"nan"],
            "severity": "medium",
            "recoverable": True,
        },
        "engine_crash": {
            "patterns": [r"traceback", r"exception", r"attributeerror", r"keyerror", r"indexerror"],
            "severity": "critical",
            "recoverable": False,
        },
        "resource_limit": {
            "patterns": [r"memory", r"disk", r"quota", r"rate limit", r"too many"],
            "severity": "high",
            "recoverable": True,
        },
        "configuration": {
            "patterns": [r"config", r"not found", r"unknown engine", r"no route", r"missing module"],
            "severity": "high",
            "recoverable": False,
        },
        "dependency": {
            "patterns": [r"import", r"module", r"package", r"dependency", r"circular"],
            "severity": "critical",
            "recoverable": False,
        },
        "permission": {
            "patterns": [r"permission", r"access denied", r"forbidden", r"unauthorized", r"401", r"403"],
            "severity": "high",
            "recoverable": False,
        },
    }

    def classify(self, error: str | Exception) -> dict[str, Any]:
        """Classify an error into a category with metadata."""
        error_str = str(error).lower()
        error_type = type(error).__name__ if isinstance(error, Exception) else "str"

        for category, config in self.CATEGORIES.items():
            for pattern in config["patterns"]:
                if re.search(pattern, error_str):
                    return {
                        "category": category,
                        "severity": config["severity"],
                        "recoverable": config["recoverable"],
                        "error_type": error_type,
                        "matched_pattern": pattern,
                        "message": str(error)[:200],
                    }

        return {
            "category": "unknown",
            "severity": "medium",
            "recoverable": False,
            "error_type": error_type,
            "matched_pattern": None,
            "message": str(error)[:200],
        }

    def classify_batch(self, errors: list[str | Exception]) -> dict[str, Any]:
        """Classify multiple errors and return summary."""
        results = [self.classify(e) for e in errors]
        by_category: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        for r in results:
            by_category[r["category"]] = by_category.get(r["category"], 0) + 1
            by_severity[r["severity"]] = by_severity.get(r["severity"], 0) + 1

        return {
            "total": len(results),
            "by_category": by_category,
            "by_severity": by_severity,
            "critical_count": by_severity.get("critical", 0),
            "recoverable_count": sum(1 for r in results if r["recoverable"]),
            "classifications": results,
        }
