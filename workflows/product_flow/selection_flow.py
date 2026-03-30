"""Product Selection Flow

Chains: product_selection → product_scoring → product_validation

Input:  Raw product candidates
Output: Validated, scored, and ranked product list
"""

from __future__ import annotations

from typing import Any

from engines.registry import get_engine
from engines.base import EngineInput, EngineOutput, EngineStatus
from utils.helpers import generate_id
from utils.logger import get_logger

logger = get_logger("workflow.product_selection")


class ProductSelectionFlow:
    """End-to-end product selection workflow."""

    def __init__(self) -> None:
        self._selection = get_engine("product_selection")
        self._scoring = get_engine("product_scoring")
        self._validation = get_engine("product_validation")

    def run(self, products: list[dict[str, Any]], criteria: dict[str, Any]) -> dict[str, Any]:
        flow_id = generate_id("flow")
        logger.info("[%s] Starting product selection flow (%d candidates)", flow_id, len(products))

        # Step 1: Select
        select_input = EngineInput(
            task_id=generate_id("task"),
            engine_name="product_selection",
            data={"products": products, "criteria": criteria},
        )
        select_output = self._selection.run(select_input)
        if select_output.status != EngineStatus.COMPLETED:
            return self._make_result(flow_id, "failed", step="selection", error=select_output.error)

        # Step 2: Score
        score_input = EngineInput(
            task_id=generate_id("task"),
            engine_name="product_scoring",
            data={"product_data": select_output.result, "scoring_criteria": criteria},
        )
        score_output = self._scoring.run(score_input)
        if score_output.status != EngineStatus.COMPLETED:
            return self._make_result(flow_id, "failed", step="scoring", error=score_output.error)

        # Step 3: Validate
        validate_input = EngineInput(
            task_id=generate_id("task"),
            engine_name="product_validation",
            data={"product_data": score_output.result, "market_data": criteria},
        )
        validate_output = self._validation.run(validate_input)

        return self._make_result(
            flow_id,
            validate_output.status.value,
            result={
                "selection": select_output.to_dict(),
                "scoring": score_output.to_dict(),
                "validation": validate_output.to_dict(),
            },
        )

    @staticmethod
    def _make_result(flow_id: str, status: str, step: str = "", result: Any = None, error: str | None = None) -> dict[str, Any]:
        return {
            "flow_id": flow_id,
            "flow": "product_selection",
            "status": status,
            "failed_step": step,
            "result": result,
            "error": error,
        }
