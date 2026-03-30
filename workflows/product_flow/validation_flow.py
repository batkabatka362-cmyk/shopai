"""Product Validation Flow

Chains: product_validation → risk → compliance

Input:  Product data to validate
Output: Validated product with risk and compliance checks
"""

from __future__ import annotations

from typing import Any

from engines.registry import get_engine
from engines.base import EngineInput, EngineStatus
from utils.helpers import generate_id
from utils.logger import get_logger

logger = get_logger("workflow.product_validation")


class ProductValidationFlow:
    """Multi-engine product validation workflow."""

    def __init__(self) -> None:
        self._validation = get_engine("product_validation")
        self._risk = get_engine("risk")
        self._compliance = get_engine("compliance")

    def run(self, product_data: dict[str, Any], market_data: dict[str, Any]) -> dict[str, Any]:
        flow_id = generate_id("flow")
        logger.info("[%s] Starting product validation flow", flow_id)

        # Step 1: Validate product
        val_output = self._validation.run(EngineInput(
            task_id=generate_id("task"),
            engine_name="product_validation",
            data={"product_data": product_data, "market_data": market_data},
        ))

        # Step 2: Risk assessment
        risk_output = self._risk.run(EngineInput(
            task_id=generate_id("task"),
            engine_name="risk",
            data={"risk_data": product_data, "risk_factors": market_data},
        ))

        # Step 3: Compliance check
        comp_output = self._compliance.run(EngineInput(
            task_id=generate_id("task"),
            engine_name="compliance",
            data={"compliance_data": product_data, "regulations": {}},
        ))

        all_passed = all(
            o.status == EngineStatus.COMPLETED
            for o in [val_output, risk_output, comp_output]
        )

        return {
            "flow_id": flow_id,
            "flow": "product_validation",
            "status": "completed" if all_passed else "failed",
            "result": {
                "validation": val_output.to_dict(),
                "risk": risk_output.to_dict(),
                "compliance": comp_output.to_dict(),
            },
        }
