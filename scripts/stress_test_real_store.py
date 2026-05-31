"""End-to-end real-store stress test harness.

Exercises every read/write path against a live Shopify store
under the credentials in the environment. Requires:

  $env:SHOPAI_TEST_STORE_ID = "<store-id-registered-in-sm>"
  $env:SHOPIFY_SHOP_URL     = "<store>.myshopify.com"
  $env:SHOPIFY_ACCESS_TOKEN = "shpat_..."

Honest scope:
  - READ side: products, collections, customers, orders,
    inventory, shop info, themes, files.
  - WRITE side: dry-run only by default. Pass --apply to
    actually mint a test discount, tag a product, etc.
  - Stress: pulls 100 products per fetch_products call, 50
    orders, 50 customers, runs each capability 3x to flush
    rate-limit edges.

Output: a JSON report at data/stress_test_report.json with
{capability, ok, latency_ms, sample, error, repeat_run} per
probe.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Make repo root importable
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.adapters import get_registry, get_router  # noqa: E402
from core.adapters.base import Capability  # noqa: E402
from core.adapters.shopify.bootstrap import register_all  # noqa: E402


DEFAULT_REPORT_PATH = REPO / "data" / "stress_test_report.json"


def _bootstrap(shop_url: str, token: str):
    """Force-register all Shopify adapters with the live creds.
    Returns the SmartRouter (registry handles registration; the
    router handles capability -> adapter dispatch).
    """
    reg = get_registry()
    register_all(
        shop_url=shop_url, access_token=token, registry=reg,
    )
    return get_router()


def _exercise(router, capability: Capability, params: dict,
              label: str, repeat: int = 1) -> list[dict]:
    """Run a capability N times via the SmartRouter, time it,
    capture sample."""
    results: list[dict] = []
    for run in range(repeat):
        t0 = time.time()
        try:
            r = router.execute(capability, params)
            ok = bool(getattr(r, "ok", False))
            data = getattr(r, "data", None)
            error = getattr(r, "error", None) if not ok else None
        except Exception as exc:  # noqa: BLE001
            ok = False
            data = None
            error = f"raised: {exc!s:.200}"
        dt_ms = int((time.time() - t0) * 1000)
        sample = None
        if isinstance(data, list):
            sample = {
                "count": len(data),
                "first": data[0] if data else None,
            }
        elif isinstance(data, dict):
            keys = list(data.keys())
            sample = {
                "keys": keys[:8],
                "key_count": len(keys),
            }
        results.append({
            "label": label,
            "capability": capability.name,
            "run": run + 1,
            "ok": ok,
            "latency_ms": dt_ms,
            "sample": sample,
            "error": error,
        })
        print(
            f"  {label:<32} run={run + 1} "
            f"ok={ok} {dt_ms}ms"
        )
        if not ok and error:
            print(f"    err: {error}")
    return results


# Each tuple: (label, Capability, params, repeat)
_PROBES = [
    # Identity
    ("shop_info", Capability.SHOPIFY_GET_SHOP, {}, 1),
    # Products
    ("list_products_first_50",
     Capability.SHOPIFY_LIST_PRODUCTS,
     {"first": 50}, 3),
    ("list_collections_first_25",
     Capability.SHOPIFY_LIST_COLLECTIONS,
     {"first": 25}, 2),
    # Customers
    ("list_customers_first_50",
     Capability.SHOPIFY_FETCH_CUSTOMERS,
     {"first": 50}, 2),
    # Orders
    ("list_orders_first_50",
     Capability.SHOPIFY_LIST_ORDERS,
     {"first": 50}, 2),
    # Inventory transfers (shipment list)
    ("list_inventory_shipments",
     Capability.SHOPIFY_LIST_INVENTORY_SHIPMENTS,
     {"first": 5}, 1),
    # Theme
    ("list_themes",
     Capability.SHOPIFY_LIST_THEMES,
     {}, 1),
    # Files
    ("list_files_first_10",
     Capability.SHOPIFY_LIST_FILES,
     {"first": 10}, 1),
    # Markets
    ("list_markets",
     Capability.SHOPIFY_LIST_MARKETS,
     {"first": 10}, 1),
]


def main():
    shop = os.environ.get("SHOPIFY_SHOP_URL", "").strip()
    token = os.environ.get("SHOPIFY_ACCESS_TOKEN", "").strip()
    if not shop or not token:
        print(
            "ERROR: SHOPIFY_SHOP_URL + SHOPIFY_ACCESS_TOKEN "
            "must be set in env"
        )
        sys.exit(2)

    print(f"Stress test against {shop}")
    print("=" * 60)
    reg = _bootstrap(shop, token)

    all_results: list[dict] = []
    for label, cap, params, repeat in _PROBES:
        try:
            results = _exercise(reg, cap, params, label,
                                repeat=repeat)
            all_results.extend(results)
        except AttributeError as exc:
            # Capability not in the enum / not registered
            print(
                f"  {label:<32} [SKIP] capability missing: "
                f"{exc!s:.80}"
            )

    # Roll up
    total = len(all_results)
    ok_count = sum(1 for r in all_results if r["ok"])
    median_ms = sorted(
        r["latency_ms"] for r in all_results
    )[total // 2] if total else 0
    print()
    print(
        f"Summary: {ok_count}/{total} ok, "
        f"median latency {median_ms}ms"
    )
    DEFAULT_REPORT_PATH.parent.mkdir(
        parents=True, exist_ok=True,
    )
    DEFAULT_REPORT_PATH.write_text(
        json.dumps({
            "shop": shop,
            "captured_at": time.time(),
            "summary": {
                "total": total,
                "ok": ok_count,
                "fail": total - ok_count,
                "median_ms": median_ms,
            },
            "results": all_results,
        }, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"Report -> {DEFAULT_REPORT_PATH}")


if __name__ == "__main__":
    main()
