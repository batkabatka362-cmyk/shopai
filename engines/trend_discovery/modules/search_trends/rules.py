"""Search trends rules — constraints on keyword targeting."""
from __future__ import annotations
from typing import Any

RULES = [
    {"id": "min_volume", "name": "Minimum search volume", "description": "Keyword must have >200 monthly searches", "check": lambda kw: kw.get("volume", 0) >= 200, "severity": "warning", "action": "Volume too low — may not generate meaningful traffic"},
    {"id": "not_declining", "name": "Not declining", "description": "Don't target keywords with >20% decline", "check": lambda kw: kw.get("growth_pct", 0) >= -20, "severity": "blocker", "action": "Keyword declining — invest elsewhere"},
    {"id": "intent_commercial", "name": "Commercial intent preferred", "description": "Prioritize transactional/commercial keywords", "check": lambda kw: kw.get("intent", "") in ("transactional", "commercial", ""), "severity": "info", "action": "Informational keyword — better for content, not direct product targeting"},
    {"id": "cpc_sanity", "name": "CPC not excessive", "description": "CPC under $8 for viable ad economics", "check": lambda kw: kw.get("cpc", 0) <= 8.0, "severity": "warning", "action": "CPC too high — organic/content strategy only"},
    {"id": "not_branded", "name": "Not a branded term", "description": "Avoid targeting competitor brand names", "check": lambda kw: not _is_branded(kw.get("keyword", "")), "severity": "warning", "action": "Branded keyword — cannot rank organically, expensive ads"},
]

def evaluate_rules(keyword_data: dict[str, Any]) -> dict[str, Any]:
    blockers, warnings, info = [], [], []
    for rule in RULES:
        try:
            passed = rule["check"](keyword_data)
        except Exception:
            passed = True
        if not passed:
            entry = {"rule_id": rule["id"], "name": rule["name"], "action": rule["action"]}
            if rule["severity"] == "blocker": blockers.append(entry)
            elif rule["severity"] == "warning": warnings.append(entry)
            else: info.append(entry)
    return {"passed": len(blockers) == 0, "blockers": blockers, "warnings": warnings, "info": info, "rules_evaluated": len(RULES)}

KNOWN_BRANDS = ["amazon", "walmart", "target", "nike", "adidas", "apple", "samsung", "google", "shopify", "etsy"]
def _is_branded(keyword: str) -> bool:
    kw = keyword.lower()
    return any(brand in kw for brand in KNOWN_BRANDS)
