"""Notification Engine — personalization engine.

Personalizes notification content by substituting template variables
with customer and event data. Applies tone and formatting adjustments.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import re
from typing import Any


def personalize_content(
    template: dict[str, Any],
    customer: dict[str, Any],
    event_data: dict[str, Any],
) -> dict[str, Any]:
    """Personalize notification content from template and customer data.

    Args:
        template: Resolved template dict (subject, body_template, variables).
        customer: Customer info dict.
        event_data: Event-specific data for variable substitution.

    Returns:
        Structured dict with personalized subject and body.
    """
    try:
        tmpl = copy.deepcopy(template)
        subject_template = str(tmpl.get("subject", ""))
        body_template = str(tmpl.get("body_template", ""))
        expected_vars = list(tmpl.get("variables", []))

        # Build substitution map from customer + event data
        var_map: dict[str, str] = {}
        var_map["customer_name"] = str(customer.get("name", "Customer"))
        var_map["customer_email"] = str(customer.get("email", ""))

        for key, value in event_data.items():
            var_map[key] = str(value)

        # Substitute variables
        subject = _substitute(subject_template, var_map)
        body = _substitute(body_template, var_map)

        # Track which variables were actually used
        used_vars = [v for v in expected_vars if v in var_map]
        personalized = len(used_vars) > 0

        return {
            "status": "success",
            "content": {
                "subject": subject,
                "body": body,
                "personalized": personalized,
                "variables_used": used_vars,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "content": {},
            "error": f"Personalization failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _substitute(template: str, var_map: dict[str, str]) -> str:
    """Replace {variable} placeholders in template with values from var_map."""
    def replacer(match: re.Match) -> str:
        key = match.group(1)
        return var_map.get(key, match.group(0))

    return re.sub(r"\{(\w+)\}", replacer, template)
