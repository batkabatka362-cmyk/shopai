"""Autonomy smoke test (W289): runtime end-to-end exerciser.

autonomy-doctor (W235) runs STATIC AST audits. autonomy-smoke
adds the RUNTIME dimension: actually imports each domain's 5
template modules + calls the canonical entry points with safe
synthetic input.

Distinct from the integration test (W239-244) in two ways:
  - it's an OPERATOR command, not a pytest target -- usable
    pre-deploy on a fresh checkout without running the full
    test suite
  - it skips test-pollution mocking; the Pattern J guard
    inside each persistent store handles the rest

Per domain, the smoke exercises:
  - applier with empty payload -> empty list (no fires, no
    Shopify writes, no log entries)
  - state.is_paused() -> bool
  - health.analyze_X_health() -> verdict object
  - status.get_X_status() -> report object
  - log.recent_X_events() -> list

Per-domain result classes:
  - ok      every call succeeded
  - error   one or more calls raised (the substrate is broken
            in a way AST audits can't detect)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from typing import Any


# Per-domain (display name, package, file prefix, status fn name).
# Status fn name is read directly from Pattern AI's catalog.
_DOMAINS = [
    (
        "customer_support_refund",
        "returns_management",
        "refund",
        "get_refund_status",
    ),
    (
        "marketing_budget",
        "roas_guardrails",
        "budget",
        "get_marketing_status",
    ),
    (
        "fulfillment",
        "fulfillment_autonomy",
        "fulfillment",
        "get_fulfillment_status",
    ),
    (
        "inventory",
        "inventory_autonomy",
        "inventory",
        "get_inventory_status",
    ),
    (
        "discount_cleanup",
        "discount_cleanup_autonomy",
        "cleanup",
        "get_cleanup_status",
    ),
    (
        "order_followup",
        "order_followup_autonomy",
        "followup",
        "get_followup_status",
    ),
    (
        "product_seo",
        "product_seo_autonomy",
        "seo",
        "get_seo_status",
    ),
    (
        "customer_outreach",
        "customer_outreach_autonomy",
        "outreach",
        "get_customer_outreach_status",
    ),
]


# Per-domain (apply fn name, log status filename prefix in W269).
_APPLY_NAMES: dict[str, str] = {
    "refund": "apply_refunds",
    "budget": "apply_budget_changes",
    "fulfillment": "apply_fulfillment_routes",
    "inventory": "apply_inventory_reorders",
    "cleanup": "apply_discount_cleanup",
    "followup": "apply_order_followups",
    "seo": "apply_seo_updates",
    "outreach": "apply_customer_outreach",
}


# apply_refunds takes (processed, fraud_flags) -- 2 positional
# args. Every other domain's apply_X takes (rows). The smoke
# test calls each with the empty form per this map.
_APPLY_EMPTY_PAYLOAD: dict[str, tuple] = {
    "refund": ([], []),
    "budget": ([],),
    "fulfillment": ([],),
    "inventory": ([],),
    "cleanup": ([],),
    "followup": ([],),
    "seo": ([],),
    "outreach": ([],),
}


# Per-domain log module name (marketing_budget uses ad_spend_log).
_LOG_MODULE_NAMES: dict[str, str] = {
    "refund": "refund_log",
    "budget": "ad_spend_log",
    "fulfillment": "fulfillment_log",
    "inventory": "inventory_log",
    "cleanup": "cleanup_log",
    "followup": "followup_log",
    "seo": "seo_log",
    "outreach": "outreach_log",
}


# Per-domain status module name (roas_guardrails uses
# marketing_status).
_STATUS_MODULE_NAMES: dict[str, str] = {
    "refund": "refund_status",
    "budget": "marketing_status",
    "fulfillment": "fulfillment_status",
    "inventory": "inventory_status",
    "cleanup": "cleanup_status",
    "followup": "followup_status",
    "seo": "seo_status",
    "outreach": "outreach_status",
}


# Per-domain health analyze fn name.
_ANALYZE_NAMES: dict[str, str] = {
    "refund": "analyze_refund_health",
    "budget": "analyze_budget_health",
    "fulfillment": "analyze_fulfillment_health",
    "inventory": "analyze_inventory_health",
    "cleanup": "analyze_cleanup_health",
    "followup": "analyze_followup_health",
    "seo": "analyze_seo_health",
    "outreach": "analyze_customer_outreach_health",
}


@dataclass
class SmokeStep:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class SmokeDomainResult:
    domain: str
    cls: str = "ok"  # ok / error
    steps: list[SmokeStep] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for s in self.steps if not s.ok)


@dataclass
class SmokeReport:
    domains: list[SmokeDomainResult] = field(
        default_factory=list,
    )
    overall_cls: str = "ok"

    @property
    def ok_count(self) -> int:
        return sum(1 for d in self.domains if d.cls == "ok")

    @property
    def error_count(self) -> int:
        return sum(1 for d in self.domains if d.cls == "error")


def _safe_call(
    fn: Any, *args, **kwargs,
) -> tuple[bool, str, Any]:
    """Call fn safely; return (ok, detail, result)."""
    try:
        result = fn(*args, **kwargs)
        return (True, type(result).__name__, result)
    except Exception as exc:  # noqa: BLE001
        return (False, str(exc)[:80], None)


def _smoke_one_domain(
    domain: str, pkg: str, prefix: str, status_fn_name: str,
) -> SmokeDomainResult:
    """Exercise one domain's 5-piece template at runtime."""
    result = SmokeDomainResult(domain=domain)

    # Step 1: applier (empty payload)
    try:
        apl = import_module(f"engines.{pkg}.{prefix}_applier")
        apply_fn = getattr(
            apl, _APPLY_NAMES[prefix], None,
        )
        if apply_fn is None:
            result.steps.append(SmokeStep(
                name="applier",
                ok=False,
                detail=f"{_APPLY_NAMES[prefix]!r} not found",
            ))
        else:
            args = _APPLY_EMPTY_PAYLOAD.get(prefix, ([],))
            ok, detail, out = _safe_call(apply_fn, *args)
            result.steps.append(SmokeStep(
                name="applier", ok=ok,
                detail=(
                    f"empty payload -> {detail}"
                    if ok else detail
                ),
            ))
    except Exception as exc:  # noqa: BLE001
        result.steps.append(SmokeStep(
            name="applier", ok=False,
            detail=f"import failed: {exc!s:.80}",
        ))

    # Step 2: state.is_paused()
    try:
        st = import_module(f"engines.{pkg}.{prefix}_state")
        is_paused = getattr(st, "is_paused", None)
        if is_paused is None:
            result.steps.append(SmokeStep(
                name="state.is_paused",
                ok=False, detail="symbol not found",
            ))
        else:
            ok, detail, out = _safe_call(is_paused)
            result.steps.append(SmokeStep(
                name="state.is_paused", ok=ok,
                detail=f"-> {out!r}" if ok else detail,
            ))
    except Exception as exc:  # noqa: BLE001
        result.steps.append(SmokeStep(
            name="state.is_paused", ok=False,
            detail=f"import failed: {exc!s:.80}",
        ))

    # Step 3: health.analyze_X_health()
    try:
        hl = import_module(f"engines.{pkg}.{prefix}_health")
        analyze = getattr(
            hl, _ANALYZE_NAMES[prefix], None,
        )
        if analyze is None:
            result.steps.append(SmokeStep(
                name="health.analyze",
                ok=False,
                detail=(
                    f"{_ANALYZE_NAMES[prefix]!r} not found"
                ),
            ))
        else:
            ok, detail, _ = _safe_call(analyze)
            result.steps.append(SmokeStep(
                name="health.analyze", ok=ok,
                detail=f"-> {detail}" if ok else detail,
            ))
    except Exception as exc:  # noqa: BLE001
        result.steps.append(SmokeStep(
            name="health.analyze", ok=False,
            detail=f"import failed: {exc!s:.80}",
        ))

    # Step 4: status.get_X_status()
    try:
        status_modname = _STATUS_MODULE_NAMES[prefix]
        sm = import_module(f"engines.{pkg}.{status_modname}")
        getter = getattr(sm, status_fn_name, None)
        if getter is None:
            result.steps.append(SmokeStep(
                name="status.get",
                ok=False,
                detail=f"{status_fn_name!r} not found",
            ))
        else:
            ok, detail, _ = _safe_call(getter)
            result.steps.append(SmokeStep(
                name="status.get", ok=ok,
                detail=f"-> {detail}" if ok else detail,
            ))
    except Exception as exc:  # noqa: BLE001
        result.steps.append(SmokeStep(
            name="status.get", ok=False,
            detail=f"import failed: {exc!s:.80}",
        ))

    # Step 5: log size readback (Pattern AF universal export)
    try:
        log_modname = _LOG_MODULE_NAMES[prefix]
        lg = import_module(f"engines.{pkg}.{log_modname}")
        log_size = getattr(lg, "log_size", None)
        if log_size is None:
            result.steps.append(SmokeStep(
                name="log.size",
                ok=False, detail="log_size not found",
            ))
        else:
            ok, detail, out = _safe_call(log_size)
            result.steps.append(SmokeStep(
                name="log.size", ok=ok,
                detail=f"-> {out!r}" if ok else detail,
            ))
    except Exception as exc:  # noqa: BLE001
        result.steps.append(SmokeStep(
            name="log.size", ok=False,
            detail=f"import failed: {exc!s:.80}",
        ))

    if result.error_count > 0:
        result.cls = "error"
    return result


def run_autonomy_smoke() -> SmokeReport:
    """Exercise every autonomy domain's 5-piece template
    via real imports + synthetic call."""
    report = SmokeReport()
    for domain, pkg, prefix, status_fn in _DOMAINS:
        report.domains.append(
            _smoke_one_domain(domain, pkg, prefix, status_fn),
        )
    if any(d.cls == "error" for d in report.domains):
        report.overall_cls = "error"
    return report
