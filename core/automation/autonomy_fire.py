"""Direct autonomy-applier invocation (Wave 816).

Phase 37 surfaced the firing-mode split: 2 of 10 autonomy
domains have engine wrappers + fire automatically; 8 are
pure substrate appliers without engine wrappers and the
cycle does NOT fire them.

This module is the bridge: operators can directly invoke any
substrate-only domain's applier with a curated payload to
exercise the autonomy substrate before Phase 40's cycle-side
discoverer + payload-generator lands.

Default mode is DRY-RUN -- the applier import + signature
inspection runs, but the actual call short-circuits. ``--yes``
opt-in actually invokes.

Each autonomy domain's applier accepts ``apply_<X>(payload)``
where payload is a ``list[dict]``. Per Pattern AH the function
is guaranteed to exist with that signature.
"""
from __future__ import annotations

import importlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# Map domain -> (module path, applier function name). Mirrors the
# canonical Pattern AH exports.
_DOMAIN_APPLIERS: dict[str, tuple[str, str]] = {
    "customer_support": (
        "engines.returns_management.refund_applier",
        "apply_refunds",
    ),
    "marketing": (
        "engines.roas_guardrails.budget_applier",
        "apply_budget_changes",
    ),
    "fulfillment": (
        "engines.fulfillment_autonomy.fulfillment_applier",
        "apply_fulfillment_routes",
    ),
    "inventory": (
        "engines.inventory_autonomy.inventory_applier",
        "apply_inventory_reorders",
    ),
    "discount_cleanup": (
        "engines.discount_cleanup_autonomy.cleanup_applier",
        "apply_discount_cleanup",
    ),
    "order_followup": (
        "engines.order_followup_autonomy.followup_applier",
        "apply_order_followups",
    ),
    "product_seo": (
        "engines.product_seo_autonomy.seo_applier",
        "apply_seo_updates",
    ),
    "customer_outreach": (
        "engines.customer_outreach_autonomy.outreach_applier",
        "apply_customer_outreach",
    ),
    "catalog_quality": (
        "engines.catalog_quality_autonomy.quality_applier",
        "apply_catalog_quality",
    ),
    "shipping_alert": (
        "engines.shipping_alert_autonomy.shipping_applier",
        "apply_shipping_alert",
    ),
}


@dataclass
class FireResult:
    domain: str
    dry_run: bool
    payload_size: int
    invoked: bool = False
    events: list[Any] = field(default_factory=list)
    duration_ms: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def known_domains() -> list[str]:
    return sorted(_DOMAIN_APPLIERS)


def fire(
    domain: str,
    payload: list[dict],
    *,
    dry_run: bool = True,
) -> FireResult:
    """Invoke the autonomy domain's applier with a curated
    payload. dry_run=True (default) short-circuits the actual
    call after import + signature inspection."""
    res = FireResult(
        domain=domain,
        dry_run=dry_run,
        payload_size=len(payload) if payload else 0,
    )
    if domain not in _DOMAIN_APPLIERS:
        res.error = (
            f"unknown domain {domain!r}; "
            f"known: {', '.join(known_domains())}"
        )
        return res
    mod_path, fn_name = _DOMAIN_APPLIERS[domain]
    try:
        mod = importlib.import_module(mod_path)
    except Exception as exc:  # noqa: BLE001
        res.error = f"import {mod_path} failed: {exc!s:.200}"
        return res
    fn = getattr(mod, fn_name, None)
    if fn is None or not callable(fn):
        res.error = (
            f"{mod_path} has no callable {fn_name!r}"
        )
        return res
    if dry_run:
        # Pre-flight succeeded; do not invoke
        return res
    t0 = time.perf_counter()

    # W963-158: Pattern CD wrap. Group payload rows by their
    # `store_id` field + invoke the applier once per group
    # inside `active_store(sid)`. Without this every applier
    # call resolved credentials via the env-default chain --
    # the W963-156 live stress test caught the failure mode
    # (`applied: false` for every catalog_quality row even
    # though the writer was invoked). Same money-class symptom
    # the cycle / webhook / approval-executor wraps closed.
    try:
        from core.context import active_store
    except Exception as exc:  # noqa: BLE001
        active_store = None  # type: ignore[assignment]

    grouped: dict[str, list[dict]] = {}
    for row in payload or []:
        if not isinstance(row, dict):
            grouped.setdefault("", []).append(row)
            continue
        sid = str(row.get("store_id") or "")
        grouped.setdefault(sid, []).append(row)

    collected: list = []
    try:
        for sid, rows in grouped.items():
            def _invoke(_rows: list[dict] = rows) -> list:
                try:
                    out = fn(_rows)
                except TypeError as exc:
                    try:
                        out = fn(payload=_rows)
                    except Exception as exc2:  # noqa: BLE001
                        raise RuntimeError(
                            f"{exc!s:.150} / "
                            f"retry: {exc2!s:.100}",
                        ) from exc2
                return out if isinstance(out, list) else [out]

            if sid and active_store is not None:
                with active_store(sid):
                    collected.extend(_invoke())
            else:
                collected.extend(_invoke())
    except Exception as exc:  # noqa: BLE001
        res.error = f"{fn_name} raised: {exc!s:.200}"
        res.duration_ms = (
            time.perf_counter() - t0
        ) * 1000.0
        return res

    res.invoked = True
    res.duration_ms = (time.perf_counter() - t0) * 1000.0
    res.events = collected
    return res
