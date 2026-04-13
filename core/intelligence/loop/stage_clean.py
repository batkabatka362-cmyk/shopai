"""Stage 1: CLEAN — validate, fix, score data quality."""
from __future__ import annotations

import copy
from typing import Any

from utils.helpers import safe_float


def stage_clean(raw: dict[str, Any]) -> dict[str, Any]:
    data = copy.deepcopy(raw)
    fixes = []
    issues = []

    for key in list(data.keys()):
        if key.startswith("_"):
            continue
        val = data[key]

        if isinstance(val, str) and key.lower() in ("price", "cost", "revenue", "spend", "budget"):
            converted = safe_float(val, default=None)
            if converted is not None:
                data[key] = converted
                fixes.append(f"{key}: string→float")
            else:
                issues.append(f"{key}: invalid number '{val}'")

        if isinstance(val, list):
            cleaned = []
            is_product_list = key in ("products", "product_data")
            for item in val:
                if isinstance(item, dict):
                    for k in ("price", "cost", "total", "spend"):
                        if k in item and isinstance(item[k], str):
                            converted = safe_float(item[k], default=None)
                            if converted is not None:
                                item[k] = converted
                                fixes.append(f"{key}[].{k}: string→float")
                    # Only require name/id for product lists, not orders/customers
                    if is_product_list:
                        if item.get("name") or item.get("id") or item.get("title"):
                            cleaned.append(item)
                        else:
                            issues.append(f"{key}: item without name/id removed")
                    else:
                        cleaned.append(item)
                elif item is not None:
                    cleaned.append(item)
            data[key] = cleaned

        if val is None or val == "" or val == []:
            del data[key]
            fixes.append(f"{key}: removed empty")

    # Business logic validation
    biz_issues = []
    for key in ("products", "product_data"):
        items = data.get(key, [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            item_price = safe_float(item.get("price"))
            item_cost = safe_float(item.get("cost"))
            item_name = item.get("name", item.get("title", "?"))

            if item_price < 0:
                biz_issues.append(f"{item_name}: negative price ({item_price})")
                issues.append(f"Negative price: {item_price}")
            if item_cost < 0:
                biz_issues.append(f"{item_name}: negative cost ({item_cost})")
                issues.append(f"Negative cost: {item_cost}")
            if item_cost > 0 and item_price > 0 and item_cost > item_price:
                biz_issues.append(f"{item_name}: cost > price")
                issues.append(f"Cost exceeds price: {item_cost} > {item_price}")

    # Quality score
    total_fields = len([k for k in data if not k.startswith("_")])
    non_empty = sum(1 for k, v in data.items() if not k.startswith("_") and v)
    has_products = bool(data.get("products") or data.get("product_data"))
    has_numbers = any(isinstance(v, (int, float)) for v in data.values())

    quality = 0
    if total_fields > 0:
        quality += min(40, non_empty / total_fields * 40)
    if has_products:
        quality += 30
    if has_numbers:
        quality += 15
    if not issues:
        quality += 15

    if biz_issues:
        penalty = min(50, len(biz_issues) * 25)
        quality = max(0, quality - penalty)

    return {
        "data": data,
        "quality_score": round(quality),
        "quality_grade": "A" if quality >= 80 else "B" if quality >= 60 else "C" if quality >= 40 else "F",
        "fixes": fixes,
        "issues": issues,
        "fields": total_fields,
    }
