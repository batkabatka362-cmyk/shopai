"""PostProcessor — processes model output into structured, usable results.

Model returns raw text/dict. PostProcessor converts it to clean, structured,
validated data that downstream steps and engines can use.

When model returns placeholder data, SmartExecutor fills in REAL computed results.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from utils.logger import get_logger
from .smart_executor import SmartExecutor

logger = get_logger("step_logic.post")

_smart = SmartExecutor()


class PostProcessor:
    """Processes model output into structured results."""

    def __init__(self) -> None:
        self._context_cache: dict[str, dict[str, Any]] = {}

    def set_step_context(self, task_id: str, data: dict[str, Any]) -> None:
        """Cache step input data for smart execution."""
        self._context_cache[task_id] = data

    def process(self, model_output: dict[str, Any], step_name: str, engine_name: str) -> dict[str, Any]:
        """Post-process model output. Returns clean structured dict."""
        result = copy.deepcopy(model_output)

        # Get cached context for smart execution
        context = {}
        for key in list(self._context_cache.keys()):
            context = self._context_cache.get(key, {})
            break  # Use most recent

        # Smart execution: enhance model output with real computation
        is_placeholder = self._is_placeholder(result)
        if is_placeholder or context:
            if step_name == "analyze":
                result = _smart.execute_analyze(context, result)
            elif step_name == "execute":
                result = _smart.execute_work(context, result)
            elif step_name == "enhance":
                result = _smart.execute_enhance(context, result)
            elif step_name == "validate":
                result = _smart.execute_validate(context, result)

        # Extract structured data from text responses
        text = result.get("text", result.get("content", ""))
        if isinstance(text, str) and text:
            extracted = self._extract_structured(text)
            if extracted:
                result["_extracted"] = extracted

        # Validate and clean output
        result = self._clean_output(result)

        # Step-specific processing
        if step_name == "analyze":
            result = self._post_analyze(result)
        elif step_name == "execute":
            result = self._post_execute(result)
        elif step_name == "validate":
            result = self._post_validate(result)

        # Ensure required fields exist
        result["_processed"] = True
        result["_step"] = step_name
        result["_engine"] = engine_name

        return result

    def _post_analyze(self, data: dict[str, Any]) -> dict[str, Any]:
        """Ensure analysis output has score and decision."""
        if "score" not in data:
            # Try to derive score from other fields
            data["score"] = self._derive_score(data)
        if "decision" not in data:
            score = data.get("score", 0)
            data["decision"] = "approve" if score >= 5.0 else "reject"
        if "reason" not in data:
            data["reason"] = data.get("message", "Auto-derived from model output")
        return data

    def _post_execute(self, data: dict[str, Any]) -> dict[str, Any]:
        """Ensure execution output is structured."""
        if "generated" not in data:
            data["generated"] = bool(data.get("content") or data.get("_extracted"))
        return data

    def _post_validate(self, data: dict[str, Any]) -> dict[str, Any]:
        """Ensure validation output has pass/fail."""
        if "valid" not in data:
            score = data.get("score", 5)
            data["valid"] = score >= 5.0
        if "issues" not in data:
            data["issues"] = []
        return data

    def _extract_structured(self, text: str) -> dict[str, Any] | None:
        """Try to extract JSON or structured data from text."""
        # Try JSON extraction
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # Try key-value extraction
        kv_pattern = re.findall(r'(\w+):\s*(.+?)(?:\n|$)', text)
        if kv_pattern:
            extracted = {}
            for key, value in kv_pattern:
                value = value.strip()
                # Try to parse numbers
                try:
                    if "." in value:
                        extracted[key.lower()] = float(value)
                    else:
                        extracted[key.lower()] = int(value)
                except ValueError:
                    extracted[key.lower()] = value
            if extracted:
                return extracted

        return None

    @staticmethod
    def _clean_output(data: dict[str, Any]) -> dict[str, Any]:
        """Remove internal/debug fields, ensure clean output."""
        cleaned = {}
        for key, value in data.items():
            # Keep internal tracking fields
            if key.startswith("_"):
                cleaned[key] = value
                continue
            # Remove raw prompts (don't leak to output)
            if key in ("raw_prompt", "raw_input"):
                continue
            # Clean nested dicts
            if isinstance(value, dict):
                value = {k: v for k, v in value.items() if k != "raw_prompt"}
            cleaned[key] = value
        return cleaned

    @staticmethod
    def _is_placeholder(result: dict[str, Any]) -> bool:
        """Detect if model returned a placeholder (no real inference)."""
        if result.get("decision") == "pending":
            return True
        if result.get("reason") == "Model inference not yet connected":
            return True
        if result.get("score") == 0.0 and result.get("decision") == "pending":
            return True
        return False

    @staticmethod
    def _derive_score(data: dict[str, Any]) -> float:
        """Try to derive a score from available data."""
        # Check common score field names
        for key in ("quality_score", "confidence", "rating", "relevance"):
            if key in data:
                val = data[key]
                if isinstance(val, (int, float)):
                    return float(val)

        # If there's extracted data with a score
        extracted = data.get("_extracted", {})
        if isinstance(extracted, dict):
            for key in ("score", "quality", "rating"):
                if key in extracted:
                    try:
                        return float(extracted[key])
                    except (ValueError, TypeError):
                        pass

        return 5.0  # Default neutral score
