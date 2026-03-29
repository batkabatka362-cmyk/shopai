"""Dashboard configuration and ASCII rendering for CLI monitoring."""

import time
import random
from typing import Optional


class DashboardBuilder:
    """Create, manage, and render monitoring dashboards."""

    def __init__(self):
        self._dashboards: dict[str, dict] = {}

    def create_dashboard(self, name: str, panels: list[dict]) -> dict:
        """Create a new dashboard with initial panels.

        Args:
            name: Unique dashboard name.
            panels: List of panel dicts, each with: title, metric, chart_type, width.

        Returns:
            The created dashboard dict.
        """
        dashboard = {
            "name": name,
            "panels": list(panels),
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        self._dashboards[name] = dashboard
        return dict(dashboard)

    def add_panel(self, dashboard_name: str, panel: dict) -> None:
        """Add a panel to an existing dashboard.

        Args:
            dashboard_name: Name of the target dashboard.
            panel: Panel dict with title, metric, chart_type, width.

        Raises:
            KeyError if dashboard does not exist.
        """
        if dashboard_name not in self._dashboards:
            raise KeyError(f"Dashboard '{dashboard_name}' not found")
        self._dashboards[dashboard_name]["panels"].append(panel)
        self._dashboards[dashboard_name]["updated_at"] = time.time()

    def remove_panel(self, dashboard_name: str, panel_title: str) -> bool:
        """Remove a panel by title. Returns True if found and removed."""
        if dashboard_name not in self._dashboards:
            return False
        panels = self._dashboards[dashboard_name]["panels"]
        original_len = len(panels)
        self._dashboards[dashboard_name]["panels"] = [p for p in panels if p.get("title") != panel_title]
        if len(self._dashboards[dashboard_name]["panels"]) < original_len:
            self._dashboards[dashboard_name]["updated_at"] = time.time()
            return True
        return False

    def get_dashboard(self, name: str) -> dict:
        """Get a dashboard by name."""
        if name not in self._dashboards:
            raise KeyError(f"Dashboard '{name}' not found")
        return dict(self._dashboards[name])

    def list_dashboards(self) -> list[str]:
        """List all dashboard names."""
        return sorted(self._dashboards.keys())

    def render_text(self, dashboard_name: str) -> str:
        """Render an ASCII text representation of the dashboard for CLI display."""
        if dashboard_name not in self._dashboards:
            raise KeyError(f"Dashboard '{dashboard_name}' not found")

        dashboard = self._dashboards[dashboard_name]
        panels = dashboard["panels"]
        total_width = 78

        lines = []
        border = "=" * total_width
        lines.append(border)
        title = f"  DASHBOARD: {dashboard['name']}  "
        lines.append(title.center(total_width))
        lines.append(border)

        if not panels:
            lines.append("  (no panels configured)".center(total_width))
            lines.append(border)
            return "\n".join(lines)

        for panel in panels:
            panel_title = panel.get("title", "Untitled")
            metric = panel.get("metric", "N/A")
            chart_type = panel.get("chart_type", "value")
            width = min(panel.get("width", total_width), total_width)

            lines.append("-" * width)
            lines.append(f"| {panel_title:<{width - 4}} |")
            lines.append(f"| Metric: {metric:<{width - 12}} |")
            lines.append(f"| Type: {chart_type:<{width - 10}} |")

            # Render a simple placeholder visualization
            if chart_type == "bar":
                bar_content = self._render_bar(width - 4)
                lines.append(f"| {bar_content} |")
            elif chart_type == "sparkline":
                spark = self._render_sparkline(width - 4)
                lines.append(f"| {spark} |")
            else:
                value_str = "[current value: --]"
                lines.append(f"| {value_str:<{width - 4}} |")

            lines.append("-" * width)

        lines.append(border)
        return "\n".join(lines)

    @staticmethod
    def _render_bar(width: int) -> str:
        """Render a placeholder bar chart line."""
        bar_chars = "\u2588\u2593\u2592\u2591"
        bar_len = max(1, width - 10)
        bar = bar_chars[0] * (bar_len // 2) + bar_chars[2] * (bar_len - bar_len // 2)
        return f"  {bar:<{width - 2}}"

    @staticmethod
    def _render_sparkline(width: int) -> str:
        """Render a placeholder sparkline."""
        spark_chars = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"
        line_len = max(1, width - 4)
        spark = "".join(random.choice(spark_chars) for _ in range(line_len))
        return f"  {spark:<{width - 2}}"
