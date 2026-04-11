"""Cycle Reporter — generates human-readable cycle summaries."""
from __future__ import annotations
import time
from typing import Any


class CycleReporter:
    """Generates readable summaries of autonomous cycles."""

    def report(self, cycle_result: dict) -> str:
        """Generate a human-readable cycle report."""
        phases = cycle_result.get("phases", {})
        lines = []
        lines.append("=" * 50)
        lines.append("SHOPAI CYCLE REPORT")
        lines.append("=" * 50)
        lines.append("Duration: {}s | Cycle #{}".format(
            cycle_result.get("duration_s", 0),
            cycle_result.get("cycle_number", 0)))
        lines.append("")

        # Store data
        d = phases.get("data", {})
        lines.append("STORE: {} products, {} orders, {} customers".format(
            d.get("products", 0), d.get("orders", 0), d.get("customers", 0)))

        # Quality
        dq = phases.get("data_quality", {})
        lines.append("QUALITY: {}/100".format(dq.get("score", "?")))

        # Brain
        brain = phases.get("brain", {})
        lines.append("HEALTH: {}/100 | {} problems, {} opportunities".format(
            brain.get("health_score", "?"),
            brain.get("problems", 0),
            brain.get("opportunities", 0)))

        # Intelligence
        layers = phases.get("layers", {})
        lines.append("INTELLIGENCE: {}/12 layers, {} insights".format(
            layers.get("layers_run", 0), layers.get("total_insights", 0)))

        # Cognitive
        cog = phases.get("cognitive", {})
        if cog:
            lines.append("THINKING: {} hypotheses, {} clusters".format(
                cog.get("hypotheses", 0), cog.get("clusters", 0)))
            for q in cog.get("questions", [])[:2]:
                lines.append("  Q: {}".format(q))

        # Actions
        dec = phases.get("decisions", {})
        se = phases.get("smart_execution", {})
        lines.append("ACTIONS: {} proposed, {} executed (score {})".format(
            dec.get("proposed", 0), se.get("total", 0), se.get("avg_score", 0)))

        # Learning
        learn = phases.get("learning", {})
        lines.append("LEARNING: {} outcomes, {} patterns, {} weight updates".format(
            learn.get("outcomes_recorded", 0),
            learn.get("patterns_found", 0),
            learn.get("weight_updates", 0)))

        # Strategy
        strat = phases.get("strategy", {})
        if strat:
            lines.append("STRATEGY: {} active, top = {}".format(
                strat.get("strategies", 0),
                strat.get("priority", ["?"])[0] if strat.get("priority") else "?"))

        # Self-improvement
        si = phases.get("self_improvement", {})
        if si.get("improvements"):
            lines.append("IMPROVEMENTS:")
            for imp in si["improvements"][:3]:
                lines.append("  + {}".format(imp))

        # Rule health
        rh = phases.get("rule_health", {})
        if rh:
            lines.append("RULES: {}/{} healthy ({}%)".format(
                rh.get("healthy", 0), rh.get("total_rules", 0),
                rh.get("health_score", 0)))

        lines.append("")
        lines.append("=" * 50)
        return "\n".join(lines)


_instance = None
def get_cycle_reporter():
    global _instance
    if _instance is None:
        _instance = CycleReporter()
    return _instance
