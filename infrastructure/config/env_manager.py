"""Environment Manager — manages environment configurations."""
from __future__ import annotations
import os
from typing import Any
from utils.logger import get_logger

logger = get_logger("infra.env")


class EnvManager:
    def __init__(self, env: str = "development") -> None:
        self._env = env
        self._vars: dict[str, str] = {}

    def get(self, key: str, default: str = "") -> str:
        return self._vars.get(key, os.environ.get(key, default))

    def set(self, key: str, value: str) -> None:
        self._vars[key] = value

    def is_production(self) -> bool:
        return self._env == "production"

    def get_env(self) -> str:
        return self._env
