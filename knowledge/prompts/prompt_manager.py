"""Prompt Manager — manages prompt templates per engine and task."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("knowledge.prompts")


class PromptManager:
    def __init__(self) -> None:
        self._templates: dict[str, str] = {}

    def register(self, name: str, template: str) -> None:
        self._templates[name] = template

    def get(self, name: str, **kwargs: Any) -> str:
        template = self._templates.get(name, "")
        if not template:
            logger.warning("Prompt template '%s' not found", name)
            return ""
        try:
            return template.format(**kwargs)
        except KeyError as e:
            logger.error("Missing key in template '%s': %s", name, e)
            return template

    def list_templates(self) -> list[str]:
        return list(self._templates.keys())
