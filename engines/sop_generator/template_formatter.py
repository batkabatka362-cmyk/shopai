"""SOP Generator Engine — template formatter.

Formats SOPs into readable templates.
All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def format_templates(
    sops: list[dict[str, Any]],
) -> dict[str, Any]:
    """Format SOPs into readable, structured templates.

    Args:
        sops: Raw SOPs from procedure_builder.

    Returns:
        Structured dict with formatted SOPs.
    """
    try:
        formatted = copy.deepcopy(sops)

        for sop in formatted:
            total_time = sum(s.get("estimated_time_minutes", 0) for s in sop.get("steps", []))
            sop["total_estimated_minutes"] = total_time
            sop["step_count"] = len(sop.get("steps", []))

            # Add complexity rating
            step_count = len(sop.get("steps", []))
            if step_count <= 3:
                sop["complexity"] = "simple"
            elif step_count <= 7:
                sop["complexity"] = "moderate"
            else:
                sop["complexity"] = "complex"

        return {"status": "success", "formatted_sops": formatted}
    except Exception as exc:
        return {"status": "error", "formatted_sops": [], "error": f"Template formatting failed: {exc}"}
