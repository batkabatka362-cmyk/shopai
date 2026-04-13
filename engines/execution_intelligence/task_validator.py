"""Execution Intelligence — task validator.

Validates each parsed task: required fields present, data types correct,
action is supported, no conflicts between tasks.

Model note: Would use Mistral for validation and execution readiness checks.
"""
from __future__ import annotations

import copy
from typing import Any


# Supported action types and their required parameter fields
_SUPPORTED_ACTIONS: dict[str, list[str]] = {
    "create_product": ["title"],
    "update_product": ["product_id"],
    "delete_product": ["product_id"],
    "launch_ad": ["platform", "budget"],
    "update_ad": ["ad_id"],
    "stop_ad": ["ad_id"],
    "update_inventory": ["product_id", "quantity"],
    "set_price": ["product_id", "price"],
    "send_email": ["recipient"],
    "generate_content": ["content_type"],
    "create_discount": ["code"],
    "update_shipping": ["method"],
    "create_collection": ["title"],
    "analyze_performance": [],
}

# Parameter type constraints: param_name -> expected type name
_PARAM_TYPE_RULES: dict[str, str] = {
    "price": "number",
    "budget": "number",
    "quantity": "integer",
    "percentage": "number",
    "title": "string",
    "product_id": "string",
    "ad_id": "string",
    "platform": "string",
    "recipient": "string",
    "code": "string",
    "method": "string",
    "content_type": "string",
}

# Conflicting action pairs — cannot both run in the same batch
_CONFLICT_PAIRS: list[tuple[str, str]] = [
    ("create_product", "delete_product"),
    ("launch_ad", "stop_ad"),
]


def validate_tasks(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate a list of parsed tasks for execution readiness.

    Args:
        tasks: List of ParsedTask dicts.

    Returns:
        Structured dict with validated tasks and validation summary.
    """
    try:
        if not isinstance(tasks, list):
            return {
                "status": "error",
                "valid_tasks": [],
                "invalid_tasks": [],
                "error": "Tasks must be a list",
            }

        safe_tasks = copy.deepcopy(tasks)
        valid_tasks: list[dict[str, Any]] = []
        invalid_tasks: list[dict[str, Any]] = []
        logs: list[str] = []

        # Detect batch-level conflicts
        action_types_in_batch = [t.get("action_type", "") for t in safe_tasks]
        batch_conflicts = _detect_conflicts(action_types_in_batch)

        for task in safe_tasks:
            task_id = task.get("task_id", "unknown")
            action_type = task.get("action_type", "")
            parameters = task.get("parameters", {})

            checks_passed: list[str] = []
            checks_failed: list[str] = []
            warnings: list[str] = []

            # Check 1: Required task fields
            _check_task_structure(task, checks_passed, checks_failed)

            # Check 2: Action type is supported
            _check_action_supported(action_type, checks_passed, checks_failed)

            # Check 3: Required parameters present
            _check_required_params(action_type, parameters, checks_passed, checks_failed)

            # Check 4: Parameter types correct
            _check_param_types(parameters, checks_passed, checks_failed, warnings)

            # Check 5: Business rule validation
            _check_business_rules(action_type, parameters, checks_passed, checks_failed, warnings)

            # Check 6: Batch conflict check
            conflict_msg = batch_conflicts.get(action_type)
            if conflict_msg:
                warnings.append(conflict_msg)

            is_valid = len(checks_failed) == 0

            validated_task: dict[str, Any] = {
                "task_id": task_id,
                "action_type": action_type,
                "parameters": parameters,
                "priority": task.get("priority", 3),
                "dependencies": task.get("dependencies", []),
                "source_index": task.get("source_index", 0),
                "validation": {
                    "is_valid": is_valid,
                    "checks_passed": checks_passed,
                    "checks_failed": checks_failed,
                    "warnings": warnings,
                },
            }

            if is_valid:
                valid_tasks.append(validated_task)
                logs.append(
                    f"Task {task_id} ({action_type}): VALID "
                    f"({len(checks_passed)} checks passed"
                    f"{', ' + str(len(warnings)) + ' warnings' if warnings else ''})"
                )
            else:
                invalid_tasks.append(validated_task)
                logs.append(
                    f"Task {task_id} ({action_type}): INVALID "
                    f"({len(checks_failed)} checks failed: "
                    f"{'; '.join(checks_failed)})"
                )

        return {
            "status": "success",
            "valid_tasks": valid_tasks,
            "invalid_tasks": invalid_tasks,
            "valid_count": len(valid_tasks),
            "invalid_count": len(invalid_tasks),
            "logs": logs,
        }
    except Exception as exc:
        return {
            "status": "error",
            "valid_tasks": [],
            "invalid_tasks": [],
            "valid_count": 0,
            "invalid_count": 0,
            "logs": [],
            "error": f"Task validation failed: {exc}",
        }


def _check_task_structure(
    task: dict[str, Any],
    passed: list[str],
    failed: list[str],
) -> None:
    """Verify required fields exist on the task dict."""
    required_fields = ["task_id", "action_type", "parameters"]
    for field in required_fields:
        if field in task and task[field] is not None:
            passed.append(f"has_{field}")
        else:
            failed.append(f"missing_{field}")

    if "parameters" in task and not isinstance(task["parameters"], dict):
        failed.append("parameters_not_dict")
    elif "parameters" in task:
        passed.append("parameters_is_dict")


def _check_action_supported(
    action_type: str,
    passed: list[str],
    failed: list[str],
) -> None:
    """Check if the action type is recognized."""
    if action_type in _SUPPORTED_ACTIONS:
        passed.append("action_type_supported")
    else:
        failed.append(f"unsupported_action_type: {action_type}")


def _check_required_params(
    action_type: str,
    parameters: dict[str, Any],
    passed: list[str],
    failed: list[str],
) -> None:
    """Check required parameters for the given action type.

    Model note: Mistral would validate parameter completeness contextually.
    """
    required = _SUPPORTED_ACTIONS.get(action_type, [])
    for param_name in required:
        if param_name in parameters and parameters[param_name] is not None:
            value = parameters[param_name]
            # Check non-empty for strings
            if isinstance(value, str) and not value.strip():
                failed.append(f"required_param_empty: {param_name}")
            else:
                passed.append(f"has_required_param: {param_name}")
        else:
            failed.append(f"missing_required_param: {param_name}")


def _check_param_types(
    parameters: dict[str, Any],
    passed: list[str],
    failed: list[str],
    warnings: list[str],
) -> None:
    """Validate parameter value types.

    Model note: Mistral would detect type mismatches and suggest corrections.
    """
    for param_name, value in parameters.items():
        expected_type = _PARAM_TYPE_RULES.get(param_name)
        if expected_type is None:
            continue

        if expected_type == "number":
            if isinstance(value, (int, float)):
                passed.append(f"type_ok: {param_name}")
            else:
                try:
                    float(value)
                    warnings.append(f"type_coerced: {param_name} (str->number)")
                except (ValueError, TypeError):
                    failed.append(f"type_error: {param_name} expected number")

        elif expected_type == "integer":
            if isinstance(value, int) and not isinstance(value, bool):
                passed.append(f"type_ok: {param_name}")
            elif isinstance(value, float) and value == int(value):
                warnings.append(f"type_coerced: {param_name} (float->int)")
            else:
                try:
                    int(value)
                    warnings.append(f"type_coerced: {param_name} (str->int)")
                except (ValueError, TypeError):
                    failed.append(f"type_error: {param_name} expected integer")

        elif expected_type == "string":
            if isinstance(value, str):
                passed.append(f"type_ok: {param_name}")
            else:
                warnings.append(f"type_coerced: {param_name} (non-str->str)")


def _check_business_rules(
    action_type: str,
    parameters: dict[str, Any],
    passed: list[str],
    failed: list[str],
    warnings: list[str],
) -> None:
    """Apply business-specific validation rules.

    Model note: Mistral would check for semantic validity and business constraints.
    """
    if action_type == "create_product":
        price = parameters.get("price")
        if price is not None:
            try:
                price_val = float(price)
                if price_val < 0:
                    failed.append("business_rule: price cannot be negative")
                elif price_val == 0:
                    warnings.append("business_rule: price is zero (free product)")
                else:
                    passed.append("business_rule: price is positive")
            except (ValueError, TypeError):
                pass

    elif action_type == "launch_ad":
        budget = parameters.get("budget")
        if budget is not None:
            try:
                budget_val = float(budget)
                if budget_val <= 0:
                    failed.append("business_rule: ad budget must be positive")
                elif budget_val < 5:
                    warnings.append("business_rule: ad budget very low (< $5)")
                else:
                    passed.append("business_rule: ad budget is valid")
            except (ValueError, TypeError):
                pass

        platform = parameters.get("platform", "")
        supported_platforms = {"facebook", "google", "instagram", "tiktok", "pinterest"}
        if platform and platform.lower() in supported_platforms:
            passed.append("business_rule: ad platform supported")
        elif platform:
            warnings.append(f"business_rule: ad platform '{platform}' may not be supported")

    elif action_type == "update_inventory":
        quantity = parameters.get("quantity")
        if quantity is not None:
            try:
                qty_val = int(quantity)
                if qty_val < 0:
                    warnings.append("business_rule: negative inventory quantity")
                else:
                    passed.append("business_rule: inventory quantity valid")
            except (ValueError, TypeError):
                pass

    elif action_type == "create_discount":
        percentage = parameters.get("percentage")
        if percentage is not None:
            try:
                pct_val = float(percentage)
                if pct_val <= 0 or pct_val > 100:
                    failed.append("business_rule: discount percentage must be 1-100")
                elif pct_val > 50:
                    warnings.append("business_rule: large discount (> 50%)")
                else:
                    passed.append("business_rule: discount percentage valid")
            except (ValueError, TypeError):
                pass

    elif action_type == "send_email":
        recipient = parameters.get("recipient", "")
        if isinstance(recipient, str) and "@" in recipient:
            passed.append("business_rule: email format looks valid")
        elif isinstance(recipient, str) and recipient:
            warnings.append("business_rule: recipient may not be a valid email")


def _detect_conflicts(
    action_types: list[str],
) -> dict[str, str]:
    """Detect conflicting action pairs in the batch.

    Returns:
        Map of action_type -> conflict warning message.
    """
    conflicts: dict[str, str] = {}
    type_set = set(action_types)

    for type_a, type_b in _CONFLICT_PAIRS:
        if type_a in type_set and type_b in type_set:
            conflicts[type_a] = f"conflict: '{type_a}' conflicts with '{type_b}' in same batch"
            conflicts[type_b] = f"conflict: '{type_b}' conflicts with '{type_a}' in same batch"

    return conflicts
