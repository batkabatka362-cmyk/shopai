"""Dashboard Builder — builds monitoring dashboards."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("monitoring.dashboards")


class DashboardBuilder:
    def __init__(self) -> None:
        self._panels: list[dict[str, Any]] = []

    def add_panel(self, title: str, metric_name: str, chart_type: str = "line") -> None:
        self._panels.append({"title": title, "metric": metric_name, "chart_type": chart_type})

    def build(self) -> dict[str, Any]:
        logger.info("Building dashboard with %d panels", len(self._panels))
        return {"panels": self._panels, "total": len(self._panels)}
