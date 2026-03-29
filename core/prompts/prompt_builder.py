"""PromptBuilder — builds intelligent prompts with context injection and CoT.

Upgrades raw prompts with:
  - System role definition per model role
  - Pre-computed data injection (scores, stats)
  - Chain-of-thought reasoning structure
  - Few-shot examples from successful runs
  - Output format specification
"""
from __future__ import annotations

import copy
import json
from typing import Any

from utils.logger import get_logger

logger = get_logger("prompts.builder")


SYSTEM_PROMPTS = {
    "analyzer": (
        "You are a data analyst for an e-commerce platform. "
        "Analyze the provided data objectively. Return structured JSON with: "
        "score (0-10), decision (approve/reject), reason (string), and detailed breakdown. "
        "Be precise with numbers. Never guess — only analyze what's in the data."
    ),
    "worker": (
        "You are an execution specialist for an e-commerce platform. "
        "Generate structured, actionable output based on the analysis. "
        "Return JSON with specific recommendations, rankings, and action items. "
        "Be concrete — include numbers, names, and specific actions."
    ),
    "creative": (
        "You are a creative strategist for an e-commerce brand. "
        "Enhance the output with compelling copy, strategic insights, and creative angles. "
        "Maintain accuracy — don't invent data. Add value through positioning and messaging."
    ),
    "validator": (
        "You are a quality assurance specialist. Validate the output for: "
        "completeness (all fields present), consistency (no contradictions), "
        "accuracy (numbers add up), and business viability. "
        "Return JSON with: valid (bool), score (0-10), issues (list), reason (string)."
    ),
}


class PromptBuilder:
    """Builds structured prompts with context, CoT, and examples."""

    def build(
        self,
        role: str,
        engine_name: str,
        step_name: str,
        user_prompt: str,
        data: dict[str, Any] | None = None,
        prior_outputs: dict[str, Any] | None = None,
        examples: list[dict[str, Any]] | None = None,
    ) -> dict[str, str]:
        """Build a full prompt with system + user + context.

        Returns: {"system": str, "user": str, "full": str}
        """
        system = SYSTEM_PROMPTS.get(role, "You are a helpful assistant.")
        parts = []

        # Context injection
        if data:
            context_str = self._inject_context(data, engine_name, step_name)
            if context_str:
                parts.append(f"## Context\n{context_str}")

        # Prior step outputs
        if prior_outputs:
            prior_str = self._format_prior_outputs(prior_outputs)
            if prior_str:
                parts.append(f"## Prior Analysis\n{prior_str}")

        # Few-shot examples
        if examples:
            example_str = self._format_examples(examples)
            if example_str:
                parts.append(f"## Examples\n{example_str}")

        # Chain-of-thought structure
        cot = self._add_chain_of_thought(role, step_name)
        if cot:
            parts.append(f"## Reasoning Steps\n{cot}")

        # User prompt
        parts.append(f"## Task\n{user_prompt}")

        # Output format
        format_spec = self._output_format(role, step_name)
        if format_spec:
            parts.append(f"## Required Output Format\n{format_spec}")

        full_prompt = "\n\n".join(parts)

        return {
            "system": system,
            "user": full_prompt,
            "full": f"[SYSTEM] {system}\n\n[USER] {full_prompt}",
        }

    def _inject_context(self, data: dict[str, Any], engine_name: str, step_name: str) -> str:
        """Extract relevant context from data for prompt injection."""
        context_parts = []

        # Pre-computed stats
        stats = data.get("_product_stats", {})
        if stats:
            context_parts.append(f"Product stats: {json.dumps(stats, default=str)}")

        quality = data.get("_data_quality", {})
        if quality:
            context_parts.append(f"Data quality: {quality.get('quality_tier', 'unknown')} ({quality.get('completeness', 0):.0%} complete)")

        pre_computed = data.get("_pre_computed", {})
        if pre_computed:
            context_parts.append(f"Pre-computed metrics: {json.dumps(pre_computed, default=str)}")

        # Pre-scored products
        scored = data.get("_pre_scored_products", [])
        if scored:
            summary = [{"name": p.get("name"), "score": p.get("total_score"), "viable": p.get("viable")} for p in scored[:5]]
            context_parts.append(f"Pre-scored products (top 5): {json.dumps(summary, default=str)}")

        return "\n".join(context_parts) if context_parts else ""

    @staticmethod
    def _format_prior_outputs(prior: dict[str, Any]) -> str:
        """Format prior step outputs for context."""
        parts = []
        for step, output in prior.items():
            if isinstance(output, dict):
                # Only include key fields, not raw data
                summary = {k: v for k, v in output.items() if not k.startswith("_") and k not in ("raw_prompt", "context_keys")}
                if summary:
                    parts.append(f"{step}: {json.dumps(summary, default=str)[:500]}")
        return "\n".join(parts)

    @staticmethod
    def _format_examples(examples: list[dict[str, Any]]) -> str:
        """Format few-shot examples."""
        parts = []
        for i, ex in enumerate(examples[:3]):
            inp = json.dumps(ex.get("input", {}), default=str)[:200]
            out = json.dumps(ex.get("output", {}), default=str)[:300]
            parts.append(f"Example {i+1}:\n  Input: {inp}\n  Output: {out}")
        return "\n\n".join(parts)

    @staticmethod
    def _add_chain_of_thought(role: str, step_name: str) -> str:
        """Add chain-of-thought reasoning structure."""
        if role == "analyzer":
            return (
                "Think step by step:\n"
                "1. Identify the key data points\n"
                "2. Evaluate each criterion\n"
                "3. Calculate scores with justification\n"
                "4. Make a decision based on evidence\n"
                "5. Provide clear reasoning"
            )
        if role == "worker" and step_name == "execute":
            return (
                "Think step by step:\n"
                "1. Review the analysis results\n"
                "2. Apply selection/generation criteria\n"
                "3. Rank results by score\n"
                "4. Generate actionable recommendations\n"
                "5. Structure output for downstream use"
            )
        if role == "validator":
            return (
                "Validation checklist:\n"
                "1. All required fields present?\n"
                "2. Scores in valid range (0-10)?\n"
                "3. No contradictions in data?\n"
                "4. Business logic valid (margins realistic, etc.)?\n"
                "5. Output usable by downstream systems?"
            )
        return ""

    @staticmethod
    def _output_format(role: str, step_name: str) -> str:
        """Specify required output format."""
        if role == "analyzer":
            return '{"score": float, "decision": "approve"|"reject", "reason": string, "breakdown": [...]}'
        if role == "worker":
            return '{"generated": true, "results": [...], "summary": {...}}'
        if role == "validator":
            return '{"valid": bool, "score": float, "issues": [...], "reason": string}'
        return ""
