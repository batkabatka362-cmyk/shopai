"""Email Marketing Engine — orchestrates the full campaign pipeline.

This is the FLOW file.  It ONLY orchestrates — no business logic here.
Every step delegates to a dedicated module; this file wires them together.

Pipeline:
  Campaign Goal -> Audience Selector -> Content Planner ->
  Subject Line Generator -> Body Composer -> Send Time Optimizer ->
  A/B Variant Builder -> Performance Predictor -> Campaign Assembler -> Output

Engine contract:
  Input:  {status, data: CampaignInput, meta, error}
  Output: {status, data: {campaign, confidence}, meta, error}

Model usage summary:
  - Audience Selector:      Mistral (analytical audience selection)
  - Subject Line Generator: LLaMA   (creative subject lines)
  - Body Composer:          LLaMA   (creative body composition)
  - Performance Predictor:  Mistral (analytical prediction)
  - Campaign Assembler:     Qwen    (structured assembly)
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .audience_selector import select_audience
from .content_planner import plan_content
from .subject_line_generator import generate_subject_lines
from .body_composer import compose_body
from .send_time_optimizer import optimize_send_time
from .ab_variant_builder import build_ab_variants
from .performance_predictor import predict_performance
from .campaign_assembler import assemble_campaign
from .memory_writer import write_to_memory
from .memory_reader import find_past_campaigns


class EmailMarketingEngine:
    """Email Marketing Engine — orchestrator only, no logic."""

    ENGINE_NAME = "email_marketing"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full email marketing pipeline.

        Accepts a raw dict (will be validated and deep-copied).
        Returns an EmailMarketingOutput-shaped dict — always structured,
        never raises.
        """
        start = time.monotonic()

        try:
            return self._execute_pipeline(input_payload, start)
        except Exception as exc:
            return self._error_output(
                reason=f"Unexpected pipeline error: {exc}",
                elapsed=time.monotonic() - start,
            )

    # ------------------------------------------------------------------
    # Private pipeline
    # ------------------------------------------------------------------

    def _execute_pipeline(
        self,
        input_payload: dict[str, Any],
        start: float,
    ) -> dict[str, Any]:
        """Run each pipeline stage in sequence, short-circuiting on failure."""

        # Stage 0: Input validation and deep copy
        parsed = self._validate_input(input_payload)
        if parsed is None:
            return self._error_output(
                reason=(
                    "Invalid input: requires 'goal' (non-empty string) "
                    "and 'audience_segments' (non-empty list)."
                ),
                elapsed=time.monotonic() - start,
            )

        goal: str = parsed["goal"]
        products: list[dict[str, Any]] = parsed["products"]
        audience_segments: list[str] = parsed["audience_segments"]
        store_name: str = parsed["store_name"]
        discount: dict[str, Any] = parsed["discount"]

        # Stage 0.5: Check memory for past campaigns
        prior = find_past_campaigns(goal, min_confidence=0.3, max_results=3)

        # Stage 1: Audience Selector  (model: Mistral)
        audience_result = select_audience(goal, audience_segments)
        if audience_result.get("status") != "success":
            return self._error_output(
                reason=audience_result.get("error", "Audience selection failed."),
                elapsed=time.monotonic() - start,
            )
        audience_selection = audience_result["selection"]

        # Stage 2: Content Planner  (no model — deterministic)
        plan_result = plan_content(goal, products, store_name, discount)
        if plan_result.get("status") != "success":
            return self._error_output(
                reason=plan_result.get("error", "Content planning failed."),
                elapsed=time.monotonic() - start,
            )
        content_plan = plan_result["plan"]

        # Stage 3: Subject Line Generator  (model: LLaMA)
        subject_result = generate_subject_lines(goal, store_name, discount, products)
        if subject_result.get("status") != "success":
            return self._error_output(
                reason=subject_result.get("error", "Subject line generation failed."),
                elapsed=time.monotonic() - start,
            )
        subject_lines_data = subject_result["subject_lines"]

        # Stage 4: Body Composer  (model: LLaMA)
        body_result = compose_body(goal, products, store_name, discount, content_plan)
        if body_result.get("status") != "success":
            return self._error_output(
                reason=body_result.get("error", "Body composition failed."),
                elapsed=time.monotonic() - start,
            )
        body_data = body_result["body"]

        # Stage 5: Send Time Optimizer  (no model — deterministic)
        send_result = optimize_send_time(goal, audience_selection.get("selected_segments", []))
        if send_result.get("status") != "success":
            return self._error_output(
                reason=send_result.get("error", "Send time optimization failed."),
                elapsed=time.monotonic() - start,
            )
        send_time_data = send_result["send_time"]

        # Stage 6: A/B Variant Builder  (no model — deterministic)
        ab_result = build_ab_variants(
            goal,
            subject_lines_data.get("subject_lines", []),
            body_data,
            audience_selection.get("audience_size", 0),
        )
        if ab_result.get("status") != "success":
            return self._error_output(
                reason=ab_result.get("error", "A/B variant building failed."),
                elapsed=time.monotonic() - start,
            )
        ab_data = ab_result["ab_variants"]

        # Stage 7: Performance Predictor  (model: Mistral)
        perf_result = predict_performance(
            goal,
            audience_selection,
            subject_lines_data,
            body_data,
            discount,
        )
        if perf_result.get("status") != "success":
            return self._error_output(
                reason=perf_result.get("error", "Performance prediction failed."),
                elapsed=time.monotonic() - start,
            )
        prediction_data = perf_result["prediction"]

        # Stage 8: Campaign Assembler  (model: Qwen)
        assembly_result = assemble_campaign(
            audience_selection,
            subject_lines_data,
            body_data,
            send_time_data,
            ab_data,
            prediction_data,
        )
        if assembly_result.get("status") != "success":
            return self._error_output(
                reason=assembly_result.get("error", "Campaign assembly failed."),
                elapsed=time.monotonic() - start,
            )

        # Stage 9: Build final output
        elapsed = time.monotonic() - start

        output: dict[str, Any] = {
            "status": "success",
            "data": {
                "campaign": assembly_result["campaign"],
                "confidence": assembly_result.get("confidence", 0.0),
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": _now(),
                "elapsed_seconds": round(elapsed, 3),
                "models": {
                    "audience_selector": "mistral",
                    "subject_line_generator": "llama",
                    "body_composer": "llama",
                    "performance_predictor": "mistral",
                    "campaign_assembler": "qwen",
                },
                "pipeline_stats": {
                    "audience_size": audience_selection.get("audience_size", 0),
                    "suppressed_count": audience_selection.get("suppressed_count", 0),
                    "segments_selected": len(audience_selection.get("selected_segments", [])),
                    "subject_lines_generated": len(subject_lines_data.get("subject_lines", [])),
                    "ab_variants": len(ab_data.get("variants", [])),
                    "content_sections": len(content_plan.get("sections", [])),
                },
                "prior_campaigns_found": len(prior),
            },
            "error": None,
        }

        # Stage 10: Persist to memory
        write_to_memory(output)

        return output

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    def _validate_input(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Validate and normalise the input into a usable dict.

        Returns ``None`` if the input is unusable.
        Never mutates *payload*.
        """
        if not isinstance(payload, dict):
            return None

        safe = copy.deepcopy(payload)

        # Engine contract: payload is {status, data, meta, error}
        data = safe.get("data", safe)  # fallback to raw dict
        if not isinstance(data, dict):
            return None

        goal = data.get("goal", "")
        if not isinstance(goal, str) or not goal.strip():
            return None

        audience_segments = data.get("audience_segments", [])
        if not isinstance(audience_segments, list) or not audience_segments:
            return None

        products = data.get("products", [])
        if not isinstance(products, list):
            products = []

        store_name = str(data.get("store_name", "Store")).strip() or "Store"

        discount = data.get("discount", {})
        if not isinstance(discount, dict):
            discount = {}

        return {
            "goal": goal.strip().lower(),
            "products": products,
            "audience_segments": audience_segments,
            "store_name": store_name,
            "discount": discount,
        }

    # ------------------------------------------------------------------
    # Error output helper
    # ------------------------------------------------------------------

    def _error_output(self, *, reason: str, elapsed: float) -> dict[str, Any]:
        """Build a well-formed error response."""
        return {
            "status": "fail",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": _now(),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
