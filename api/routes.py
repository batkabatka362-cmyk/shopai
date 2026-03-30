"""Routes — API route documentation and registration."""
from __future__ import annotations


ROUTES = {
    "GET /api/health": "System health check — modules, engines, models, memory",
    "GET /api/status": "Orchestrator status — running state, routes, handlers, metrics",
    "GET /api/engines": "List all registered engines (2270+)",
    "GET /api/engine/{name}": "Engine details — class, inputs, outputs",
    "GET /api/chains": "List registered engine chains",
    "POST /api/task": "Submit a task: {task_type, params} → engine result",
    "POST /api/chain": "Run an engine chain: {chain, data} → chain result",
    "POST /api/batch": "Batch process: {engine, items} → parallel results",
    "POST /api/analyze": "Analyze engine/system: {engine?} → learning insights",
    "POST /api/webhook/shopify": "Receive Shopify webhook: auto-routes to engines by event type",
    "POST /api/agent": "Run via agent: {agent, task, data} → agent selects engine",
    "POST /api/workflow": "Run workflow: {workflow, data} → multi-agent multi-engine",
}


def register_routes() -> dict[str, str]:
    """Return API route documentation."""
    return dict(ROUTES)
