"""Email Marketing Engine — campaign assembler.

Assembles all pipeline outputs into the final campaign object ready
for execution.  Validates completeness and produces the canonical
output shape.

Model note: Uses Qwen for structured campaign assembly.
"""
from __future__ import annotations

import copy
from typing import Any


def assemble_campaign(
    audience_selection: dict[str, Any],
    subject_lines: dict[str, Any],
    body: dict[str, Any],
    send_time: dict[str, Any],
    ab_variants: dict[str, Any],
    prediction: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the final campaign from all pipeline components.

    Args:
        audience_selection: AudienceSelection from audience_selector.
        subject_lines: SubjectLineSet from subject_line_generator.
        body: EmailBody from body_composer.
        send_time: SendTimeRecommendation from send_time_optimizer.
        ab_variants: ABVariantSet from ab_variant_builder.
        prediction: PerformancePrediction from performance_predictor.

    Returns:
        Structured dict with AssembledCampaign data.
    """
    try:
        aud = copy.deepcopy(audience_selection)
        subj = copy.deepcopy(subject_lines)
        bod = copy.deepcopy(body)
        st = copy.deepcopy(send_time)
        ab = copy.deepcopy(ab_variants)
        pred = copy.deepcopy(prediction)

        # Extract subject line texts
        subject_line_texts: list[str] = []
        for sl in subj.get("subject_lines", []):
            text = sl.get("text", "")
            if text:
                subject_line_texts.append(text)

        # Extract HTML template
        html_template = bod.get("html_template", "")

        # Extract audience size
        audience_size = aud.get("audience_size", 0)

        # Extract send time ISO string
        iso_send_time = st.get("iso_send_time", "")

        # Extract A/B variants
        variants = ab.get("variants", [])

        # Extract predicted performance
        predicted_performance: dict[str, float] = {
            "open_rate": pred.get("open_rate", 0.0),
            "click_rate": pred.get("click_rate", 0.0),
            "conversion_rate": pred.get("conversion_rate", 0.0),
            "unsubscribe_rate": pred.get("unsubscribe_rate", 0.0),
        }

        # Validate completeness
        issues: list[str] = []
        if not subject_line_texts:
            issues.append("No subject lines generated")
        if not html_template:
            issues.append("No HTML body template")
        if audience_size == 0:
            issues.append("Audience size is zero")
        if not iso_send_time:
            issues.append("No send time determined")

        if issues:
            return {
                "status": "error",
                "campaign": {},
                "error": f"Assembly incomplete: {'; '.join(issues)}",
            }

        campaign: dict[str, Any] = {
            "subject_lines": subject_line_texts,
            "body_html_template": html_template,
            "audience_size": audience_size,
            "send_time": iso_send_time,
            "ab_variants": variants,
            "predicted_performance": predicted_performance,
            "model_note": "Qwen: structured campaign assembly and validation",
        }

        # Compute overall confidence from prediction
        confidence = pred.get("confidence", 0.0)

        return {
            "status": "success",
            "campaign": campaign,
            "confidence": confidence,
        }
    except Exception as exc:
        return {
            "status": "error",
            "campaign": {},
            "error": f"Campaign assembly failed: {exc}",
        }
