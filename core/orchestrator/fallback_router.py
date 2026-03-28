from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("orchestrator.fallback_router")


class FallbackRouter:
    """Provides fallback routing when primary routing fails."""

    def __init__(self, max_depth: int = 3) -> None:
        self._fallback_chains: dict[str, list[str]] = {}
        self._max_depth = max_depth
        self._default_fallback: str | None = None

    def set_default_fallback(self, engine_name: str) -> None:
        self._default_fallback = engine_name

    def register_chain(self, engine_name: str, fallbacks: list[str]) -> None:
        self._fallback_chains[engine_name] = fallbacks[:self._max_depth]
        logger.info(
            "Registered fallback chain for %s: %s",
            engine_name,
            " -> ".join(fallbacks[:self._max_depth]),
        )

    def get_fallback(self, engine_name: str, attempt: int = 0) -> str | None:
        chain = self._fallback_chains.get(engine_name, [])
        if attempt < len(chain):
            fallback = chain[attempt]
            logger.info(
                "Fallback for %s (attempt %d): %s",
                engine_name, attempt, fallback,
            )
            return fallback
        if self._default_fallback:
            logger.info("Using default fallback: %s", self._default_fallback)
            return self._default_fallback
        logger.warning("No fallback available for %s (attempt %d)", engine_name, attempt)
        return None

    def get_chain(self, engine_name: str) -> list[str]:
        return list(self._fallback_chains.get(engine_name, []))

    def list_chains(self) -> dict[str, list[str]]:
        return dict(self._fallback_chains)
