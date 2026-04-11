"""Learning Loop — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Execution Result -> Result Collector -> Evaluator -> Error Detector ->
  Pattern Analyzer -> Insight Generator -> Improvement Engine ->
  Memory Writer -> Feedback Injector -> Output

Engine contract:
  Input:  {status, data: {task, decision, execution, result}, meta, error}
  Output: {status, data: {performance, errors, patterns, insights, improvements, feedback, confidence}, meta, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .result_collector import collect_results
from .evaluator import evaluate_performance
from .error_detector import detect_errors
from .pattern_analyzer import analyze_patterns
from .insight_generator import generate_insights
from .improvement_engine import generate_improvements
from .memory_writer import write_learning_result
from .memory_reader import read_past_records
from .feedback_injector import inject_feedback


class LearningLoopEngine:
    """Learning Loop Engine — orchestrator only, no logic."""

    ENGINE_NAME = "learning_loop"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full learning loop pipeline.

        Args:
            input_payload: LearningLoopInput dict.

        Returns:
            LearningLoopOutput dict.
        """
        start = time.monotonic()

        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)

        if payload.get("status") == "fail":
            return self._fail(
                payload.get("error", "Upstream failure"), 0.0,
            )

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        task = str(data.get("task", ""))
        decision = str(data.get("decision", ""))
        execution = str(data.get("execution", ""))
        result = data.get("result", {})

        if not task:
            return self._fail("'task' is required in data", 0.0)
        if not isinstance(result, dict):
            return self._fail("'result' must be a dict", 0.0)

        past_result = read_past_records(task=task, limit=20)
        past_records = past_result.get("records", [])

        collector_result = collect_results(
            task=task,
            decision=decision,
            execution=execution,
            result=result,
        )
        if collector_result.get("status") == "error":
            return self._fail(
                f"Result collection failed: {collector_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        raw_metrics = collector_result.get("raw_metrics", {})
        derived_metrics = collector_result.get("derived_metrics", {})
        summary = collector_result.get("summary", {})

        eval_result = evaluate_performance(
            task=task,
            raw_metrics=raw_metrics,
            derived_metrics=derived_metrics,
            summary=summary,
            past_records=past_records,
        )
        performance = eval_result.get("performance", "unknown")

        error_result = detect_errors(
            raw_metrics=raw_metrics,
            derived_metrics=derived_metrics,
            evaluation=eval_result,
            past_records=past_records,
        )
        errors = error_result.get("errors", [])

        pattern_result = analyze_patterns(
            task=task,
            decision=decision,
            raw_metrics=raw_metrics,
            derived_metrics=derived_metrics,
            evaluation=eval_result,
            errors=errors,
            past_records=past_records,
        )
        patterns = pattern_result.get("patterns", [])

        insight_result = generate_insights(
            task=task,
            decision=decision,
            evaluation=eval_result,
            errors=errors,
            patterns=patterns,
            raw_metrics=raw_metrics,
            derived_metrics=derived_metrics,
        )
        insights = insight_result.get("insights", [])

        improvement_result = generate_improvements(
            task=task,
            decision=decision,
            evaluation=eval_result,
            errors=errors,
            patterns=patterns,
            insights=insights,
            derived_metrics=derived_metrics,
        )
        improvements = improvement_result.get("improvements", [])

        _write_result = write_learning_result(
            task=task,
            decision=decision,
            execution=execution,
            result=result,
            performance=performance,
            score=eval_result.get("score", 0.0),
            errors=errors,
            patterns=patterns,
            insights=insights,
            improvements=improvements,
            confidence=self._compute_confidence(eval_result, patterns, improvements),
        )

        feedback_result = inject_feedback(
            task=task,
            decision=decision,
            evaluation=eval_result,
            errors=errors,
            improvements=improvements,
            insights=insights,
            patterns=patterns,
        )
        feedback = feedback_result.get("feedback", {})

        elapsed = time.monotonic() - start
        confidence = self._compute_confidence(eval_result, patterns, improvements)

        return {
            "status": "success",
            "data": {
                "performance": performance,
                "errors": errors,
                "patterns": patterns,
                "insights": [i.get("insight", "") for i in insights if i.get("insight")],
                "improvements": [
                    {
                        "action": imp.get("action", ""),
                        "expected_impact": imp.get("expected_impact", ""),
                    }
                    for imp in improvements
                ],
                "feedback": feedback,
                "confidence": round(confidence, 4),
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    def _compute_confidence(
        self,
        evaluation: dict[str, Any],
        patterns: list[dict[str, Any]],
        improvements: list[dict[str, Any]],
    ) -> float:
        """Compute overall pipeline confidence score."""
        base = 0.5

        eval_score = evaluation.get("score", 0.0)
        if eval_score > 0:
            base += 0.1

        if patterns:
            pattern_confs = [p.get("confidence", 0.5) for p in patterns]
            avg_conf = sum(pattern_confs) / len(pattern_confs)
            base += avg_conf * 0.2

        if improvements:
            base += min(0.1, len(improvements) * 0.02)

        return max(0.1, min(0.95, base))

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        """Return a standardized failure output."""
        return {
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
