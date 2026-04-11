"""Profitability Calculator — output formatting."""
from __future__ import annotations
import time
from typing import Any

def format_output(engine_name: str, results: dict[str, Any], data: dict[str, Any], elapsed: float) -> dict[str, Any]:
    margins = results.get("margins", {}).get("data") or {}
    be = results.get("break_even", {}).get("data") or {}
    roi = results.get("roi", {}).get("data", {})

    verdict = "profitable" if margins.get("net_margin_pct", 0) > 15 else "marginal" if margins.get("net_margin_pct", 0) > 0 else "unprofitable"

    summary_parts = [f"Product: ${data.get('price', 0):.2f} price, ${data.get('cost', 0):.2f} cost"]
    if margins.get("contribution_margin_pct"):
        summary_parts.append(f"Contribution margin: {margins['contribution_margin_pct']}%")
    if be.get("break_even_units"):
        summary_parts.append(f"Break-even: {be['break_even_units']} units")
    summary_parts.append(f"Verdict: {verdict}")

    return {
        "status": "success",
        "data": {
            "verdict": verdict,
            "summary": ". ".join(summary_parts),
            "cost_breakdown": results.get("cost_breakdown", {}),
            "margins": results.get("margins", {}),
            "break_even": results.get("break_even", {}),
            "roi": results.get("roi", {}),
            "scenarios": results.get("scenarios", {}),
        },
        "meta": {"engine": engine_name, "confidence": 0.80, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
        "error": None,
    }
