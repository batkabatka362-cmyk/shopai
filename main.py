"""ShopAI — main entry point.

Uses CoreOrchestrator as the single brain coordinating all 22+ intelligence
modules, thinking layers, and expert knowledge systems.

Architecture:
  CoreOrchestrator (central brain, 14 phases)
    ├── MainOrchestrator (engine routing, sessions, state)
    ├── 22 Intelligence Modules
    ├── Thinking Layers (GoalManager, JudgmentAdvisor, EpisodicMemory)
    ├── Expert Knowledge (FinancialDepth, MarketingTactics, CustomerJourney, SupplyChain)
    └── Coordination (StoreSnapshot, PriorityEngine, ActionCoordinator, CycleJournal)
"""

from core.core_orchestrator import CoreOrchestrator
from engines.registry import engine_count
from utils.logger import get_logger

logger = get_logger("main")


def main() -> None:
    logger.info("Starting ShopAI...")

    # Initialize the central brain
    orchestrator = CoreOrchestrator()
    status = orchestrator.status()
    logger.info(
        "CoreOrchestrator initialized: %d modules, %d engines registered",
        status["modules_count"], engine_count(),
    )

    # Run one intelligence cycle
    result = orchestrator.run_cycle()
    summary = result.get("summary", {})
    logger.info("Cycle complete: decision=%s, confidence=%s/%s",
                summary.get("decision", "none"),
                summary.get("confidence", "?"),
                summary.get("confidence_score", 0))

    # Report situation
    situation = orchestrator.get_situation()
    alerts = situation.get("alerts", [])
    if alerts:
        for alert in alerts:
            logger.warning("Alert [%s]: %s", alert.get("severity"), alert.get("message"))
    else:
        logger.info("No alerts — store operating normally")

    # Report narrative
    narrative = result.get("narrative", "")
    if narrative:
        logger.info("Narrative:\n%s", narrative)

    logger.info("ShopAI cycle complete.")


if __name__ == "__main__":
    main()
