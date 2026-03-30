"""CronParser — simple cron expression parser."""
from __future__ import annotations
import time
from datetime import datetime


class CronParser:
    """Parse simple cron expressions: minute hour day_of_month month day_of_week."""

    PRESETS = {
        "@hourly": "0 * * * *",
        "@daily": "0 0 * * *",
        "@weekly": "0 0 * * 0",
        "@monthly": "0 0 1 * *",
        "@every_5m": "*/5 * * * *",
        "@every_15m": "*/15 * * * *",
        "@every_30m": "*/30 * * * *",
    }

    @classmethod
    def should_run(cls, expression: str, now: datetime | None = None) -> bool:
        """Check if a cron expression matches the current time."""
        expression = cls.PRESETS.get(expression, expression)
        now = now or datetime.now()
        parts = expression.split()
        if len(parts) != 5:
            return False

        checks = [
            (parts[0], now.minute, 0, 59),
            (parts[1], now.hour, 0, 23),
            (parts[2], now.day, 1, 31),
            (parts[3], now.month, 1, 12),
            (parts[4], now.weekday(), 0, 6),  # 0=Monday in Python
        ]

        return all(cls._matches(expr, value, lo, hi) for expr, value, lo, hi in checks)

    @classmethod
    def _matches(cls, expr: str, value: int, lo: int, hi: int) -> bool:
        if expr == "*":
            return True
        if "/" in expr:
            base, step = expr.split("/", 1)
            step = int(step)
            start = lo if base == "*" else int(base)
            return (value - start) % step == 0 and value >= start
        if "," in expr:
            return value in [int(x) for x in expr.split(",")]
        if "-" in expr:
            a, b = expr.split("-", 1)
            return int(a) <= value <= int(b)
        return value == int(expr)

    @classmethod
    def next_run_description(cls, expression: str) -> str:
        """Human-readable description of cron schedule."""
        expression = cls.PRESETS.get(expression, expression)
        parts = expression.split()
        if len(parts) != 5:
            return "invalid cron"
        m, h, dom, mon, dow = parts
        if expression == "0 * * * *": return "Every hour"
        if expression == "0 0 * * *": return "Every day at midnight"
        if expression == "0 0 * * 0": return "Every Sunday at midnight"
        if expression == "0 0 1 * *": return "First day of every month"
        if m.startswith("*/"):
            return f"Every {m[2:]} minutes"
        return f"Cron: {expression}"
