"""A/B Testing -- variant builder.

Builds control and treatment variants with specific changes.
Each variant gets a unique ID, descriptive name, and a list of
changes relative to the control.

Model note: Would use Qwen for structured variant output.
"""
from __future__ import annotations

from typing import Any


def build_variants(
    control: dict[str, Any],
    treatment: dict[str, Any],
    test_type: str,
    test_id: str,
) -> dict[str, Any]:
    """Build control and treatment variant objects.

    Args:
        control: Control variant parameters.
        treatment: Treatment variant parameters.
        test_type: Category of test (pricing, content, ads, ux).
        test_id: Parent test identifier.

    Returns:
        Structured dict with list of variant objects.
    """
    try:
        control_variant = {
            "variant_id": f"{test_id}_control",
            "variant_name": "control",
            "is_control": True,
            "parameters": dict(control),
            "description": _describe(control, test_type, "control"),
            "changes_from_control": [],
        }

        changes = _compute_changes(control, treatment)

        treatment_variant = {
            "variant_id": f"{test_id}_treatment_a",
            "variant_name": "treatment_a",
            "is_control": False,
            "parameters": dict(treatment),
            "description": _describe(treatment, test_type, "treatment"),
            "changes_from_control": changes,
        }

        return {
            "status": "success",
            "variants": [control_variant, treatment_variant],
        }
    except Exception as exc:
        return {
            "status": "error",
            "variants": [],
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _describe(params: dict[str, Any], test_type: str, role: str) -> str:
    """Generate a human-readable description of a variant."""
    if not params:
        return f"{role.capitalize()} variant with default {test_type} parameters"

    parts = [f"{role.capitalize()} ({test_type}):"]
    for key, value in params.items():
        label = key.replace("_", " ").title()
        parts.append(f"{label}={value}")
    return " | ".join(parts)


def _compute_changes(
    control: dict[str, Any],
    treatment: dict[str, Any],
) -> list[str]:
    """Compute a list of human-readable changes from control to treatment."""
    changes: list[str] = []

    all_keys = set(list(control.keys()) + list(treatment.keys()))

    for key in sorted(all_keys):
        ctrl_val = control.get(key)
        treat_val = treatment.get(key)
        label = key.replace("_", " ").title()

        if key not in control:
            changes.append(f"Added {label}: {treat_val}")
        elif key not in treatment:
            changes.append(f"Removed {label} (was {ctrl_val})")
        elif ctrl_val != treat_val:
            # Compute percentage change for numeric values
            if isinstance(ctrl_val, (int, float)) and isinstance(treat_val, (int, float)):
                if ctrl_val != 0:
                    pct = ((treat_val - ctrl_val) / abs(ctrl_val)) * 100.0
                    direction = "increased" if pct > 0 else "decreased"
                    changes.append(
                        f"{label}: {ctrl_val} -> {treat_val} "
                        f"({direction} {abs(pct):.1f}%)"
                    )
                else:
                    changes.append(f"{label}: {ctrl_val} -> {treat_val}")
            else:
                changes.append(f"{label}: {ctrl_val!r} -> {treat_val!r}")

    if not changes:
        changes.append("No parameter differences detected")

    return changes
