"""WorkflowBridge — connects workflow definitions to engine chains.

Workflows define business processes: "launch product", "run campaign", etc.
Each workflow maps to a sequence of agent+engine runs with data passing.
"""
from __future__ import annotations

import copy
import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id
from core.bridge import AgentEngineBridge

logger = get_logger("bridge.workflow")


class WorkflowStep:
    """A step in a workflow."""
    def __init__(self, agent: str, task: str, description: str = "", required: bool = True) -> None:
        self.agent = agent
        self.task = task
        self.description = description
        self.required = required


# Pre-built business workflows
WORKFLOWS = {
    "product_launch": {
        "description": "Full product launch: research → select → price → content → campaign",
        "steps": [
            WorkflowStep("product_agent", "product_selection", "Select best products"),
            WorkflowStep("product_agent", "pricing", "Set optimal pricing"),
            WorkflowStep("content_agent", "product_description", "Generate product copy"),
            WorkflowStep("content_agent", "seo", "Optimize for search"),
            WorkflowStep("marketing_agent", "email_marketing", "Create launch email"),
            WorkflowStep("marketing_agent", "social_media", "Plan social posts", required=False),
        ],
    },
    "customer_retention": {
        "description": "Retain at-risk customers: segment → predict churn → personalize → email",
        "steps": [
            WorkflowStep("customer_agent", "customer_segmentation", "Segment customers"),
            WorkflowStep("customer_agent", "churn_prediction", "Predict churn risk"),
            WorkflowStep("customer_agent", "personalization", "Personalize offers"),
            WorkflowStep("marketing_agent", "email_marketing", "Send retention emails"),
        ],
    },
    "inventory_restock": {
        "description": "Restock inventory: forecast → check stock → order → track",
        "steps": [
            WorkflowStep("analytics_agent", "demand_forecasting", "Forecast demand"),
            WorkflowStep("operations_agent", "inventory", "Check current stock"),
            WorkflowStep("operations_agent", "stock_prediction", "Predict needs"),
            WorkflowStep("operations_agent", "procurement", "Create purchase orders", required=False),
        ],
    },
    "marketing_campaign": {
        "description": "Full campaign: audience → content → ads → landing page → track",
        "steps": [
            WorkflowStep("customer_agent", "customer_segmentation", "Define audience"),
            WorkflowStep("marketing_agent", "audience_targeting", "Target segments"),
            WorkflowStep("content_agent", "content_generation", "Create content"),
            WorkflowStep("marketing_agent", "ad_copy", "Generate ad creative"),
            WorkflowStep("marketing_agent", "campaign", "Launch campaign"),
            WorkflowStep("analytics_agent", "conversion_tracking", "Track results", required=False),
        ],
    },
    "seo_optimization": {
        "description": "Full SEO: research → audit → optimize → content → links",
        "steps": [
            WorkflowStep("content_agent", "keyword_research", "Research keywords"),
            WorkflowStep("content_agent", "seo", "Audit current SEO"),
            WorkflowStep("content_agent", "content_optimization", "Optimize content"),
            WorkflowStep("content_agent", "blog_generation", "Create SEO content"),
            WorkflowStep("content_agent", "link_building", "Plan link building", required=False),
        ],
    },
    "pricing_optimization": {
        "description": "Optimize pricing: analyze → test → adjust → monitor",
        "steps": [
            WorkflowStep("product_agent", "pricing", "Analyze current pricing"),
            WorkflowStep("analytics_agent", "analytics", "Review performance"),
            WorkflowStep("product_agent", "dynamic_pricing", "Generate dynamic prices"),
            WorkflowStep("product_agent", "discount_strategy", "Plan discounts", required=False),
        ],
    },
}


class WorkflowBridge:
    """Executes business workflows through agent-engine coordination."""

    def __init__(self) -> None:
        self._agent_bridge = AgentEngineBridge()
        self._execution_log: list[dict[str, Any]] = []

    def run_workflow(self, workflow_name: str, data: dict[str, Any]) -> dict[str, Any]:
        """Run a named workflow with data."""
        workflow = WORKFLOWS.get(workflow_name)
        if workflow is None:
            return {"error": f"Unknown workflow: {workflow_name}", "available": list(WORKFLOWS.keys())}

        wf_id = generate_id("wf")
        start = time.monotonic()
        context = copy.deepcopy(data)
        step_results = []

        logger.info("Workflow '%s' started (id=%s, steps=%d)", workflow_name, wf_id, len(workflow["steps"]))

        for i, step in enumerate(workflow["steps"]):
            step_start = time.monotonic()
            result = self._agent_bridge.agent_run(step.agent, step.task, context)
            step_elapsed = time.monotonic() - step_start

            step_entry = {
                "step": i,
                "agent": step.agent,
                "engine": result.get("engine", step.task),
                "status": result.get("status", "unknown"),
                "elapsed": round(step_elapsed, 3),
                "description": step.description,
            }
            step_results.append(step_entry)

            # Accumulate results for next step
            engine_result = result.get("result", {})
            if isinstance(engine_result, dict):
                for k, v in engine_result.items():
                    if not k.startswith("_"):
                        context[k] = v

            # Stop on required step failure
            if result.get("status") != "completed" and step.required:
                logger.warning("Workflow '%s' stopped at step %d: %s", workflow_name, i, step.task)
                break

        elapsed = time.monotonic() - start
        completed = sum(1 for s in step_results if s["status"] == "completed")

        wf_result = {
            "workflow_id": wf_id,
            "workflow": workflow_name,
            "description": workflow["description"],
            "status": "completed" if completed == len(step_results) else "partial",
            "completed_steps": completed,
            "total_steps": len(workflow["steps"]),
            "elapsed_seconds": round(elapsed, 3),
            "steps": step_results,
            "final_data_keys": [k for k in context if not k.startswith("_")],
        }

        self._execution_log.append(wf_result)
        logger.info("Workflow '%s' finished: %s (%d/%d steps, %.3fs)",
                     workflow_name, wf_result["status"], completed, len(step_results), elapsed)
        return wf_result

    def list_workflows(self) -> list[dict[str, Any]]:
        return [
            {"name": name, "description": wf["description"], "steps": len(wf["steps"])}
            for name, wf in WORKFLOWS.items()
        ]

    def get_workflow_detail(self, name: str) -> dict[str, Any] | None:
        wf = WORKFLOWS.get(name)
        if wf is None:
            return None
        return {
            "name": name,
            "description": wf["description"],
            "steps": [{"agent": s.agent, "task": s.task, "description": s.description, "required": s.required}
                      for s in wf["steps"]],
        }

    def get_execution_log(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(self._execution_log[-limit:])
