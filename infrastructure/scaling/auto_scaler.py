"""Auto Scaler — automatic scaling logic."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("infra.scaler")


class AutoScaler:
    def __init__(self, min_instances: int = 1, max_instances: int = 10) -> None:
        self._min = min_instances
        self._max = max_instances
        self._current = min_instances

    def evaluate(self, load: float) -> dict[str, Any]:
        if load > 0.8 and self._current < self._max:
            self._current += 1
            action = "scale_up"
        elif load < 0.2 and self._current > self._min:
            self._current -= 1
            action = "scale_down"
        else:
            action = "no_change"
        logger.info("Scaling: %s (instances=%d, load=%.2f)", action, self._current, load)
        return {"action": action, "instances": self._current, "load": load}
