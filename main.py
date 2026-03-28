"""ShopAI — main entry point."""

from core.orchestrator import MainOrchestrator
from utils.logger import get_logger

logger = get_logger("main")


def main() -> None:
    logger.info("Starting ShopAI...")

    orchestrator = MainOrchestrator()
    orchestrator.initialize()

    session_id = orchestrator.create_session()
    logger.info("Session created: %s", session_id)

    status = orchestrator.get_status()
    logger.info("System status: running=%s", status["running"])

    orchestrator.shutdown()
    logger.info("ShopAI stopped.")


if __name__ == "__main__":
    main()
