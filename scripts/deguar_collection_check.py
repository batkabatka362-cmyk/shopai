"""Verify the 5 Calm & Cozy smart collections actually have products.

The previous session created 5 smart collections on the Deguar
store:

    best-sellers
    cozy-bedroom
    aromatherapy
    magic-home
    under-25-gift

Each uses a tag-based rule (e.g. ``tag == "cozy"``). But the
rules only work if the PRODUCTS have the matching tags — which
they might not if tags drifted or were never added. An empty
collection is worse than no collection: nav shows the link,
click lands on a dead page, bounce rate spikes, "store feels
broken" impression on first visit.

This script:

  1. Lists every smart + custom collection via
     /smart_collections.json and /custom_collections.json
  2. For each, fetches /collections/<handle>/products.json
     to count actual members
  3. Surfaces collections that are empty OR have fewer than
     ``--min-products`` items
  4. Shows the tag rules so owner can see what needs to match

Read-only. No writes. Safe to re-run.

Usage:
    PYTHONPATH=. python scripts/deguar_collection_check.py
    PYTHONPATH=. python scripts/deguar_collection_check.py --min-products 3
"""
from __future__ import annotations

import argparse
import sys
import urllib.error

from scripts._shopify_client import (
    ShopifyClient, ShopifyClientMisconfigured,
)


# Collections the Calm & Cozy niche work must end up with.
# Each entry is handle → owner-facing explanation.
_EXPECTED: dict[str, str] = {
    "best-sellers": "Social-proof anchor (top of nav)",
    "cozy-bedroom": "Primary Calm & Cozy hero — ambient lighting + humidifiers",
    "aromatherapy": "Wellness / self-care cluster",
    "magic-home": "Wow-factor / gift angle",
    "under-25-gift": "Price-anchor impulse tier",
}


def fetch_all_collections(client: ShopifyClient) -> list[dict]:
    """Return every collection — both smart + custom — as a
    unified list with a ``kind`` field."""
    out: list[dict] = []
    smart = client.get(
        "smart_collections.json?limit=250",
    ).get("smart_collections") or []
    for c in smart:
        c["kind"] = "smart"
        out.append(c)
    custom = client.get(
        "custom_collections.json?limit=250",
    ).get("custom_collections") or []
    for c in custom:
        c["kind"] = "custom"
        out.append(c)
    return out


def product_count(
    client: ShopifyClient, collection_id: str,
) -> int:
    """Count products in a collection. Shopify's collection
    products endpoint paginates — we only want the count, so
    the ``/collects/count.json?collection_id=X`` helper would
    be faster, but it only works for manual collections. For
    smart collections we fetch-and-count."""
    try:
        payload = client.get(
            f"collections/{collection_id}/products.json"
            f"?limit=250&fields=id",
        )
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return 0
        raise
    return len(payload.get("products") or [])


def _summarise_rules(coll: dict) -> str:
    """Render the tag-rule list in owner-friendly form."""
    rules = coll.get("rules") or []
    if not rules:
        return "(no rules — manual collection)"
    parts: list[str] = []
    for r in rules:
        col = r.get("column") or "?"
        rel = r.get("relation") or "="
        cond = r.get("condition") or ""
        parts.append(f"{col} {rel} {cond!r}")
    match = coll.get("disjunctive")
    joiner = " OR " if match else " AND "
    return joiner.join(parts)


def audit(
    client: ShopifyClient, min_products: int,
) -> dict[str, list[dict]]:
    collections = fetch_all_collections(client)
    by_handle = {c.get("handle"): c for c in collections}

    healthy: list[dict] = []
    thin: list[dict] = []
    empty: list[dict] = []
    missing: list[dict] = []
    extra: list[dict] = []

    for handle, purpose in _EXPECTED.items():
        coll = by_handle.get(handle)
        if coll is None:
            missing.append({"handle": handle, "purpose": purpose})
            continue
        count = product_count(client, coll["id"])
        row = {
            "handle": handle,
            "purpose": purpose,
            "id": coll["id"],
            "kind": coll.get("kind"),
            "count": count,
            "rules": _summarise_rules(coll),
            "published": bool(coll.get("published_at")),
        }
        if count == 0:
            empty.append(row)
        elif count < min_products:
            thin.append(row)
        else:
            healthy.append(row)

    expected_handles = set(_EXPECTED)
    for handle, coll in by_handle.items():
        if handle not in expected_handles and handle not in (
            # Shopify auto-generates this for every store
            "all", "frontpage",
        ):
            extra.append({
                "handle": handle,
                "kind": coll.get("kind"),
                "id": coll.get("id"),
            })

    return {
        "healthy": healthy,
        "thin": thin,
        "empty": empty,
        "missing": missing,
        "extra": extra,
    }


def print_report(
    result: dict[str, list[dict]], min_products: int,
) -> None:
    if result["healthy"]:
        print(f"═══ Healthy ({len(result['healthy'])}) ═══")
        for row in result["healthy"]:
            pub = "published" if row["published"] else "UNPUBLISHED"
            print(f"  ✓ {row['handle']:20s} "
                  f"{row['count']:>3d} products [{pub}]")
            print(f"     {row['purpose']}")
            print(f"     rules: {row['rules']}")
        print()
    if result["thin"]:
        print(f"═══ Thin (< {min_products} products) "
              f"({len(result['thin'])}) ═══")
        for row in result["thin"]:
            print(f"  ⚠ {row['handle']:20s} "
                  f"{row['count']:>3d} products")
            print(f"     rules: {row['rules']}")
            print(f"     → add more products matching these "
                  f"rules, or loosen the tag filter")
        print()
    if result["empty"]:
        print(f"═══ EMPTY ({len(result['empty'])}) "
              f"— these are dead-end nav links ═══")
        for row in result["empty"]:
            print(f"  ✗ {row['handle']:20s} ({row['purpose']})")
            print(f"     rules: {row['rules']}")
            print(f"     → either (a) fix the rules, (b) add "
                  f"matching tags to products, or (c) delete "
                  f"the collection")
        print()
    if result["missing"]:
        print(f"═══ MISSING ({len(result['missing'])}) "
              f"— expected but not created ═══")
        for row in result["missing"]:
            print(f"  ✗ {row['handle']:20s} "
                  f"({row['purpose']})")
        print()
    if result["extra"]:
        print(f"═══ Extra collections (not in Calm & Cozy set) "
              f"({len(result['extra'])}) ═══")
        for row in result["extra"]:
            print(f"  ~ {row['handle']:20s} [{row['kind']}]")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--min-products", type=int, default=3,
        help=(
            "Collections with fewer products are flagged 'thin'. "
            "Default 3 — below this, collection page feels empty."
        ),
    )
    args = ap.parse_args(argv)

    try:
        client = ShopifyClient.from_env()
    except ShopifyClientMisconfigured as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        return 2

    print(f"Store: {client.url}\n")
    try:
        result = audit(client, args.min_products)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            print("ERR: token rejected", file=sys.stderr)
            return 3
        if exc.code == 403:
            print("ERR: 403 — check read_products + "
                  "read_product_listings scopes",
                  file=sys.stderr)
            return 3
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"ERR: {exc}", file=sys.stderr)
        return 3

    print_report(result, args.min_products)

    # Exit code semantics:
    #   0 all 5 expected collections healthy
    #   1 some thin
    #   2 some empty or missing (blocking — nav broken)
    if result["empty"] or result["missing"]:
        return 2
    if result["thin"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
