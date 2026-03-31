"""ShopAI — main entry point.

Initialises the full 14-layer system:
  Core Orchestrator → Engines (111) → Models → Data Pipeline
  → Execution → Agents → Knowledge → Memory
  → Workflows → Testing → Monitoring → Infrastructure
"""

from core.orchestrator import MainOrchestrator
from engines.registry import engine_count, list_engines
from utils.logger import get_logger

logger = get_logger("main")


def _verify_modules() -> dict:
    """Import-check every top-level module and return status."""
    modules = {
        "engines": "engines.registry",
        "data_pipeline": "data_pipeline",
        "execution": "execution",
        "agents": "agents",
        "knowledge": "knowledge",
        "memory": "memory",
        "testing": "testing",
        "monitoring": "monitoring",
        "infrastructure": "infrastructure",
        "workflows": "workflows",
        "models": "models.routing.model_router",
        "core": "core.orchestrator",
    }
    status: dict[str, bool] = {}
    import importlib
    for name, path in modules.items():
        try:
            importlib.import_module(path)
            status[name] = True
        except Exception as exc:
            logger.warning("Module %s failed to load: %s", name, exc)
            status[name] = False
    return status


def main() -> None:
    logger.info("Starting ShopAI...")

    # Verify all modules
    module_status = _verify_modules()
    loaded = sum(1 for v in module_status.values() if v)
    total = len(module_status)
    logger.info("Modules loaded: %d/%d", loaded, total)

    # Initialize orchestrator
    orchestrator = MainOrchestrator()
    orchestrator.initialize()

    session_id = orchestrator.create_session()
    logger.info("Session created: %s", session_id)

    # Report system status
    status = orchestrator.get_status()
    logger.info("System status: running=%s", status["running"])
    logger.info("Registered engines: %d", engine_count())

    # Report new module status
    logger.info("Agent manager: %s", "active" if orchestrator.agent_manager else "N/A")
    logger.info("Vector DB: %s", "active" if orchestrator.vector_db else "N/A")
    logger.info("Rule engine: %s", "active" if orchestrator.rule_engine else "N/A")
    logger.info("Data pipelines: %s", "active" if orchestrator._product_pipeline else "N/A")

    orchestrator.shutdown()
    logger.info("ShopAI stopped.")


if __name__ == "__main__":
    main()
