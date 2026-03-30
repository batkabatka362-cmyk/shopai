"""DataRouter — routes the right data to each engine step.

Rule: Each step only gets what it needs.
  - Analyzer: gets raw metrics + features for decision
  - Worker: gets full context for execution
  - Creative: gets content-relevant fields only
  - Validator: gets everything for verification
"""
from __future__ import annotations

import copy
from typing import Any

from utils.logger import get_logger

logger = get_logger("data_context.router")

# Fields each model role should focus on
ROLE_FOCUS = {
    "analyzer": {
        "include_patterns": ["score", "metric", "stat", "count", "rate", "price", "cost", "margin", "trend"],
        "exclude_patterns": ["content", "description", "copy", "creative", "html", "template"],
    },
    "worker": {
        "include_patterns": [],  # Worker gets everything
        "exclude_patterns": ["_internal", "_debug"],
    },
    "creative": {
        "include_patterns": ["content", "description", "copy", "title", "headline", "brand", "voice", "style", "name"],
        "exclude_patterns": ["score", "metric", "internal", "hash", "debug"],
    },
    "validator": {
        "include_patterns": [],  # Validator gets everything
        "exclude_patterns": ["_debug"],
    },
}


class DataRouter:
    """Routes appropriate data subsets to each engine step."""

    def route(self, data: dict[str, Any], role: str) -> dict[str, Any]:
        """Filter data for a specific model role."""
        focus = ROLE_FOCUS.get(role)
        if focus is None or not focus["include_patterns"]:
            return self._exclude(data, focus["exclude_patterns"] if focus else [])

        result = {}
        include = focus["include_patterns"]
        exclude = focus["exclude_patterns"]

        for key, value in data.items():
            key_lower = key.lower()

            # Skip excluded
            if any(pat in key_lower for pat in exclude):
                continue

            # Include if matches pattern or is a required field
            if any(pat in key_lower for pat in include) or key.startswith("_"):
                result[key] = copy.deepcopy(value)

        # Always include essential context fields
        for essential in ("engine_name", "task_id", "_step", "_enrichment", "_product_stats"):
            if essential in data and essential not in result:
                result[essential] = copy.deepcopy(data[essential])

        return result

    @staticmethod
    def _exclude(data: dict[str, Any], patterns: list[str]) -> dict[str, Any]:
        """Copy data excluding fields matching patterns."""
        result = {}
        for key, value in data.items():
            key_lower = key.lower()
            if not any(pat in key_lower for pat in patterns):
                result[key] = copy.deepcopy(value)
        return result

    @staticmethod
    def merge_step_output(
        context: dict[str, Any],
        step_output: dict[str, Any],
        step_name: str,
    ) -> dict[str, Any]:
        """Merge step output into context without overwriting original data."""
        merged = copy.deepcopy(context)
        merged[f"_{step_name}_output"] = copy.deepcopy(step_output)
        # Also merge top-level non-conflicting keys
        for key, value in step_output.items():
            if key not in merged and not key.startswith("_"):
                merged[key] = value
        return merged
