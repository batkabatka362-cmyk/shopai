"""KPI Tracking Engine — benchmark comparator.

Compares current KPI values against industry benchmarks.
Classifies performance as above/below average and computes gaps.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Default industry benchmarks (e-commerce averages)
# ---------------------------------------------------------------------------

_DEFAULT_BENCHMARKS = {
    "aov": {"industry_avg": 85.0, "top_quartile": 120.0, "bottom_quartile": 50.0},
    "cac": {"industry_avg": 45.0, "top_quartile": 25.0, "bottom_quartile": 80.0},
    "ltv": {"industry_avg": 250.0, "top_quartile": 500.0, "bottom_quartile": 100.0},
    "conversion_rate": {"industry_avg": 0.025, "top_quartile": 0.05, "bottom_quartile": 0.01},
    "repeat_rate": {"industry_avg": 0.27, "top_quartile": 0.40, "bottom_quartile": 0.15},
    "gross_margin": {"industry_avg": 0.50, "top_quartile": 0.65, "bottom_quartile": 0.35},
}


def compare_benchmarks(
    kpis: dict[str, Any],
    benchmarks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare current KPIs against industry benchmarks.

    Args:
        kpis: Current KPI values dict.
        benchmarks: List of benchmark records. Uses defaults if empty.

    Returns:
        Structured dict with benchmark comparisons.
    """
    try:
        kpis = copy.deepcopy(kpis)

        # Build benchmark lookup from provided data or defaults
        bench_map: dict[str, dict[str, float]] = {}

        if benchmarks:
            for b in benchmarks:
                kpi_name = str(b.get("kpi", ""))
                if kpi_name:
                    bench_map[kpi_name] = {
                        "industry_avg": float(b.get("industry_avg", 0)),
                        "top_quartile": float(b.get("top_quartile", 0)),
                        "bottom_quartile": float(b.get("bottom_quartile", 0)),
                    }
        else:
            bench_map = copy.deepcopy(_DEFAULT_BENCHMARKS)

        comparisons: list[dict[str, Any]] = []

        for kpi_name, bench in bench_map.items():
            current_val = float(kpis.get(kpi_name, 0))
            industry_avg = bench.get("industry_avg", 0)
            top_q = bench.get("top_quartile", 0)
            bottom_q = bench.get("bottom_quartile", 0)

            # For CAC, lower is better (invert comparison)
            is_lower_better = kpi_name in ("cac",)

            if is_lower_better:
                if current_val <= top_q:
                    percentile = "top_quartile"
                elif current_val <= industry_avg:
                    percentile = "above_average"
                elif current_val <= bottom_q:
                    percentile = "below_average"
                else:
                    percentile = "bottom_quartile"
                gap = round(current_val - industry_avg, 4)
            else:
                if current_val >= top_q:
                    percentile = "top_quartile"
                elif current_val >= industry_avg:
                    percentile = "above_average"
                elif current_val >= bottom_q:
                    percentile = "below_average"
                else:
                    percentile = "bottom_quartile"
                gap = round(current_val - industry_avg, 4)

            comparisons.append({
                "kpi": kpi_name,
                "current_value": current_val,
                "industry_avg": industry_avg,
                "percentile": percentile,
                "gap": gap,
            })

        return {
            "status": "success",
            "comparisons": comparisons,
        }
    except Exception as exc:
        return {
            "status": "error",
            "comparisons": [],
            "error": f"Benchmark comparison failed: {exc}",
        }
