"""Engine output evaluation framework."""

import time
from typing import Any


class Evaluator:
    """Evaluates AI engine outputs for correctness, completeness, consistency, and quality."""

    def evaluate_engine_output(self, engine_name: str, output: dict, expected_schema: dict) -> dict:
        """Evaluate engine output against an expected schema.

        Args:
            engine_name: Name of the engine that produced the output.
            output: The output dict to evaluate.
            expected_schema: Dict mapping field names to expected types (e.g. {"name": "str", "score": "float"}).

        Returns:
            Dict with schema_valid, field_errors, and score.
        """
        field_errors = []
        type_map = {
            "str": str, "string": str,
            "int": int, "integer": int,
            "float": float, "number": (int, float),
            "bool": bool, "boolean": bool,
            "list": list, "array": list,
            "dict": dict, "object": dict,
        }

        for field, expected_type_name in expected_schema.items():
            if field not in output:
                field_errors.append({"field": field, "error": "missing"})
                continue
            expected_type = type_map.get(str(expected_type_name).lower())
            if expected_type and not isinstance(output[field], expected_type):
                field_errors.append({
                    "field": field,
                    "error": f"type_mismatch: expected {expected_type_name}, got {type(output[field]).__name__}"
                })

        total_fields = len(expected_schema) if expected_schema else 1
        score = max(0.0, 1.0 - len(field_errors) / total_fields)

        return {
            "engine_name": engine_name,
            "schema_valid": len(field_errors) == 0,
            "field_errors": field_errors,
            "score": round(score, 4),
            "timestamp": time.time(),
        }

    def evaluate_completeness(self, output: dict, required_fields: list) -> dict:
        """Check whether output contains all required fields.

        Returns:
            Dict with score (0-1) and missing_fields list.
        """
        missing_fields = [f for f in required_fields if f not in output]
        total = len(required_fields) if required_fields else 1
        score = 1.0 - len(missing_fields) / total
        return {
            "score": round(score, 4),
            "missing_fields": missing_fields,
            "present_count": total - len(missing_fields),
            "total_required": total,
        }

    def evaluate_consistency(self, outputs: list) -> dict:
        """Check whether multiple runs produce consistent results.

        Compares key sets and value types across outputs.

        Returns:
            Dict with score and inconsistencies list.
        """
        if not outputs:
            return {"score": 0.0, "inconsistencies": [], "note": "no outputs provided"}
        if len(outputs) == 1:
            return {"score": 1.0, "inconsistencies": [], "note": "single output, trivially consistent"}

        reference = outputs[0]
        ref_keys = set(reference.keys())
        inconsistencies = []

        for idx, output in enumerate(outputs[1:], start=1):
            current_keys = set(output.keys())
            missing = ref_keys - current_keys
            extra = current_keys - ref_keys
            if missing:
                inconsistencies.append({"run": idx, "issue": "missing_keys", "keys": sorted(missing)})
            if extra:
                inconsistencies.append({"run": idx, "issue": "extra_keys", "keys": sorted(extra)})

            for key in ref_keys & current_keys:
                ref_type = type(reference[key]).__name__
                cur_type = type(output[key]).__name__
                if ref_type != cur_type:
                    inconsistencies.append({
                        "run": idx,
                        "issue": "type_mismatch",
                        "key": key,
                        "expected": ref_type,
                        "got": cur_type,
                    })

        max_issues = max(1, (len(outputs) - 1) * len(ref_keys))
        score = max(0.0, 1.0 - len(inconsistencies) / max_issues)
        return {
            "score": round(score, 4),
            "inconsistencies": inconsistencies,
            "runs_compared": len(outputs),
        }

    def evaluate_quality(self, output: dict, rubric: dict) -> dict:
        """Score output on each quality dimension defined in rubric.

        Args:
            rubric: Dict mapping dimension names to dicts with 'weight' (float) and
                    'check' which is one of: 'non_empty', 'min_length:<n>', 'in_range:<lo>:<hi>',
                    'type:<typename>'. If 'check' is absent the dimension gets full marks
                    if the field exists.

        Returns:
            Dict with per-dimension scores (0-10) and weighted_average.
        """
        dimension_scores = {}
        total_weight = 0.0
        weighted_sum = 0.0

        for dimension, spec in rubric.items():
            weight = spec.get("weight", 1.0)
            check = spec.get("check", "exists")
            field = spec.get("field", dimension)
            value = output.get(field)
            score = 0.0

            if value is None:
                score = 0.0
            elif check == "exists":
                score = 10.0
            elif check == "non_empty":
                if isinstance(value, (str, list, dict)):
                    score = 10.0 if len(value) > 0 else 0.0
                else:
                    score = 10.0
            elif check.startswith("min_length:"):
                min_len = int(check.split(":")[1])
                actual_len = len(value) if hasattr(value, "__len__") else 0
                score = min(10.0, 10.0 * actual_len / max(min_len, 1))
            elif check.startswith("in_range:"):
                parts = check.split(":")
                lo, hi = float(parts[1]), float(parts[2])
                if isinstance(value, (int, float)) and lo <= value <= hi:
                    score = 10.0
                else:
                    score = 0.0
            elif check.startswith("type:"):
                expected = check.split(":")[1]
                score = 10.0 if type(value).__name__ == expected else 0.0
            else:
                score = 10.0 if value is not None else 0.0

            score = round(score, 2)
            dimension_scores[dimension] = {"score": score, "weight": weight}
            total_weight += weight
            weighted_sum += score * weight

        weighted_avg = round(weighted_sum / total_weight, 4) if total_weight > 0 else 0.0
        return {
            "dimensions": dimension_scores,
            "weighted_average": weighted_avg,
        }

    def run_evaluation_suite(self, engine_name: str, test_cases: list) -> dict:
        """Run all evaluations across a list of test cases.

        Each test case should have: output, expected_schema, required_fields, rubric.

        Returns:
            Aggregated evaluation results.
        """
        results = []
        all_scores = {"schema": [], "completeness": [], "quality": []}

        for i, tc in enumerate(test_cases):
            output = tc.get("output", {})
            case_result = {"case_index": i}

            if "expected_schema" in tc:
                schema_eval = self.evaluate_engine_output(engine_name, output, tc["expected_schema"])
                case_result["schema"] = schema_eval
                all_scores["schema"].append(schema_eval["score"])

            if "required_fields" in tc:
                comp_eval = self.evaluate_completeness(output, tc["required_fields"])
                case_result["completeness"] = comp_eval
                all_scores["completeness"].append(comp_eval["score"])

            if "rubric" in tc:
                quality_eval = self.evaluate_quality(output, tc["rubric"])
                case_result["quality"] = quality_eval
                all_scores["quality"].append(quality_eval["weighted_average"])

            results.append(case_result)

        # Consistency across all outputs
        all_outputs = [tc.get("output", {}) for tc in test_cases]
        consistency = self.evaluate_consistency(all_outputs)

        scores_summary = {}
        for key, vals in all_scores.items():
            if vals:
                scores_summary[key] = round(sum(vals) / len(vals), 4)
        scores_summary["consistency"] = consistency["score"]

        return {
            "engine_name": engine_name,
            "total_cases": len(test_cases),
            "results": results,
            "consistency": consistency,
            "scores_summary": scores_summary,
            "overall_score": self._calculate_overall_score(scores_summary),
        }

    def _calculate_overall_score(self, scores: dict) -> float:
        """Calculate a single overall score from multiple dimension scores."""
        if not scores:
            return 0.0
        return round(sum(scores.values()) / len(scores), 4)
