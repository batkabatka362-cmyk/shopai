"""Selection Reasoning Engine — evidence compiler.

Compiles and organizes evidence supporting each product decision,
assessing evidence strength and identifying gaps.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


_EXPECTED_SOURCES = ["profitability", "risk", "market", "lifecycle", "optimization"]


def compile_evidence(
    decisions: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compile evidence for each decision.

    Args:
        decisions: List of decision record dicts.
        evidence: List of evidence item dicts.

    Returns:
        Structured dict with per-product evidence compilations.
    """
    try:
        evidence_map: dict[str, list[dict[str, Any]]] = {}
        for e in evidence:
            pid = str(e.get("product_id", ""))
            if pid:
                evidence_map.setdefault(pid, []).append(e)

        compilations: list[dict[str, Any]] = []

        for decision in decisions:
            pid = str(decision.get("product_id", "unknown"))
            prod_evidence = evidence_map.get(pid, [])

            # Organize evidence
            supporting: list[dict[str, Any]] = []
            sources_present: set[str] = set()

            for ev in prod_evidence:
                source = str(ev.get("source", "unknown"))
                sources_present.add(source)
                supporting.append({
                    "source": source,
                    "metric": str(ev.get("metric", "")),
                    "value": ev.get("value"),
                    "interpretation": str(ev.get("interpretation", "")),
                })

            # Assess evidence strength
            source_coverage = len(sources_present) / len(_EXPECTED_SOURCES) if _EXPECTED_SOURCES else 0.0
            evidence_count_score = min(len(supporting) / 5.0, 1.0)
            evidence_strength = round(source_coverage * 0.6 + evidence_count_score * 0.4, 3)

            # Identify gaps
            gaps = [s for s in _EXPECTED_SOURCES if s not in sources_present]

            compilations.append({
                "product_id": pid,
                "supporting_evidence": supporting,
                "evidence_strength": evidence_strength,
                "gaps": gaps,
            })

        return {"status": "success", "compilations": compilations}
    except Exception as exc:
        return {"status": "error", "compilations": [], "error": f"Evidence compilation failed: {exc}"}
