"""Auto Test Generator — generates test cases for engines."""
from __future__ import annotations
from typing import Any
from engines.base import EngineInput
from utils.helpers import generate_id
from utils.logger import get_logger

logger = get_logger("testing.auto_gen")


class AutoTestGenerator:
    def generate_test_input(self, engine_name: str, required_fields: list[str]) -> EngineInput:
        data = {field: f"test_{field}" for field in required_fields}
        return EngineInput(task_id=generate_id("test"), engine_name=engine_name, data=data)

    def generate_batch(self, engine_name: str, required_fields: list[str], count: int = 5) -> list[EngineInput]:
        return [self.generate_test_input(engine_name, required_fields) for _ in range(count)]
