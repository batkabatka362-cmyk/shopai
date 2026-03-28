"""BaseModel — abstract interface for all model wrappers.

Models are tools, not decision-makers.
Each model wrapper:
  - receives structured input
  - returns structured output
  - has a single role (analyzer / worker / creative)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from utils.logger import get_logger


class BaseModel(ABC):
    """Abstract base for model wrappers."""

    model_name: str = "base"
    model_role: str = "unknown"  # "analyzer", "worker", "creative"

    def __init__(self) -> None:
        self.logger = get_logger(f"model.{self.model_name}")

    @abstractmethod
    def execute(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send structured prompt to model, return structured output."""

    def format_prompt(self, template: str, data: dict[str, Any]) -> str:
        """Format a prompt template with data values."""
        try:
            return template.format(**data)
        except KeyError as exc:
            self.logger.warning("Missing key in prompt template: %s", exc)
            return template
