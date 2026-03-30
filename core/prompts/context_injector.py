"""ContextInjector — injects computed context into prompts automatically.

Takes pre-computed data (scores, stats, features) and injects it into
the prompt so the model has real intelligence to work with.
"""
from __future__ import annotations

import json
from typing import Any


class ContextInjector:
    """Injects computed data context into prompts."""

    def inject(self, prompt: str, data: dict[str, Any], max_context_chars: int = 2000) -> str:
        """Inject relevant context into a prompt."""
        context_parts = []
        chars_used = 0

        # Priority 1: Pre-computed scores
        for key in ("_pre_computed", "_pre_scored_products", "_pricing_analysis"):
            if key in data and chars_used < max_context_chars:
                val = self._compact(data[key])
                context_parts.append(f"[{key[1:]}]: {val}")
                chars_used += len(val)

        # Priority 2: Enrichment stats
        for key in ("_product_stats", "_customer_stats", "_order_stats"):
            if key in data and chars_used < max_context_chars:
                val = self._compact(data[key])
                context_parts.append(f"[{key[1:]}]: {val}")
                chars_used += len(val)

        # Priority 3: Data quality
        quality = data.get("_data_quality", {})
        if quality and chars_used < max_context_chars:
            context_parts.append(f"[data_quality]: {quality.get('quality_tier', '?')} ({quality.get('completeness', 0):.0%})")

        # Priority 4: Prior step outputs (compact)
        for key in sorted(data.keys()):
            if key.startswith("_") and key.endswith("_output") and chars_used < max_context_chars:
                step = key.replace("_", "").replace("output", "")
                val = self._compact_output(data[key])
                context_parts.append(f"[prior_{step}]: {val}")
                chars_used += len(val)

        if not context_parts:
            return prompt

        context_block = "\n".join(context_parts)
        return f"## Computed Context\n{context_block}\n\n## Task\n{prompt}"

    @staticmethod
    def _compact(data: Any, max_len: int = 500) -> str:
        """Compact data for prompt injection."""
        if isinstance(data, list):
            if len(data) > 5:
                data = data[:5]
        try:
            s = json.dumps(data, default=str)
            return s[:max_len] + "..." if len(s) > max_len else s
        except (TypeError, ValueError):
            return str(data)[:max_len]

    @staticmethod
    def _compact_output(output: Any, max_len: int = 300) -> str:
        """Compact a step output — only key fields."""
        if not isinstance(output, dict):
            return str(output)[:max_len]
        # Only include non-internal, non-model-metadata fields
        filtered = {k: v for k, v in output.items()
                    if not k.startswith("_") and k not in ("raw_prompt", "context_keys", "request_id", "model", "role")}
        try:
            s = json.dumps(filtered, default=str)
            return s[:max_len] + "..." if len(s) > max_len else s
        except (TypeError, ValueError):
            return str(filtered)[:max_len]
