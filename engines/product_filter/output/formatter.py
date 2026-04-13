"""Product Filter Engine — output formatting."""
from __future__ import annotations
import time
from typing import Any

def format_output(engine_name: str, results: dict[str, Any], input_count: int, final_products: list, elapsed: float) -> dict[str, Any]:
    pass_rate = round(len(final_products) / max(input_count, 1) * 100, 1)
    return {
        "status": "success",
        "data": {
            "input_count": input_count,
            "output_count": len(final_products),
            "pass_rate": pass_rate,
            "final_products": final_products,
            "gate_results": results,
            "summary": f"Filtered {input_count} products → {len(final_products)} passed ({pass_rate}%). Gates: criteria→blacklist→shipping→legal→brand.",
        },
        "meta": {
            "engine": engine_name,
            "confidence": min(0.90, 0.5 + len(final_products) / max(input_count, 1) * 0.4),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_seconds": round(elapsed, 3),
        },
        "error": None,
    }
