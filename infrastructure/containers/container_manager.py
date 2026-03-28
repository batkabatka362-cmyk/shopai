"""Container Manager — container orchestration."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("infra.containers")


class ContainerManager:
    def __init__(self) -> None:
        self._containers: dict[str, dict[str, Any]] = {}

    def start(self, name: str, image: str, config: dict[str, Any] | None = None) -> str:
        self._containers[name] = {"image": image, "status": "running", "config": config or {}}
        logger.info("Started container: %s (%s)", name, image)
        return name

    def stop(self, name: str) -> None:
        if name in self._containers:
            self._containers[name]["status"] = "stopped"

    def list_running(self) -> list[str]:
        return [n for n, c in self._containers.items() if c["status"] == "running"]
