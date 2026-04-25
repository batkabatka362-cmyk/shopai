"""Backup the Deguar store to local JSON for disaster recovery.

Dumps every owner-touched surface of the live store into a
date-stamped folder. Useful before:
  * any bulk operation (bulk-image upload, mass tag rewrite)
  * Shopify app reinstall (token rotates, things may break)
  * theme switch (settings_data risk)

Output layout:

    backups/<YYYY-MM-DD-HHMMSS>/
        manifest.json        — what's in this snapshot + counts
        shop.json            — store metadata
        products.json        — full catalog with variants
        product-metafields/  — one file per product (slow but
                               where Schema.org JSON-LD lives)
        smart_collections.json
        custom_collections.json
        pages.json
        blogs.json + articles/<blog_id>.json
        script_tags.json
        webhooks.json
        redirects.json
        shipping_zones.json
        policies.json
        themes.json          — main theme list (NOT theme assets)

Read-only on Shopify side. Writes only to local backups/ dir.

Restore flow is intentionally NOT included — restoring product
state via the API is destructive and risks duplicating data.
The JSON dump is a reference for owner to manually rebuild,
not a one-click restore.

Usage:
    PYTHONPATH=. python scripts/deguar_backup.py
    PYTHONPATH=. python scripts/deguar_backup.py --skip-metafields
    PYTHONPATH=. python scripts/deguar_backup.py --out custom_dir/
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error

from scripts._shopify_client import (
    ShopifyClient, ShopifyClientMisconfigured,
)


def _safe_get(
    client: ShopifyClient, path: str, label: str,
) -> dict | None:
    """GET with 403/404 → None (skip the resource cleanly).
    Other errors propagate so the operator sees them."""
    try:
        return client.get(path)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404):
            print(f"  ⚠ {label}: HTTP {exc.code} — skipped "
                  f"(scope or feature unavailable)")
            return None
        raise


def _write_json(path: str, payload: object) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)


def _backup_resource(
    client: ShopifyClient, out_dir: str,
    path: str, filename: str, label: str,
) -> int:
    """Return count of items written, or -1 if skipped."""
    payload = _safe_get(client, path, label)
    if payload is None:
        return -1
    _write_json(os.path.join(out_dir, filename), payload)
    # Find the list inside the payload so manifest can record count
    for v in payload.values():
        if isinstance(v, list):
            print(f"  ✓ {label}: {len(v)} items → {filename}")
            return len(v)
    print(f"  ✓ {label}: {filename}")
    return 1


def _backup_product_metafields(
    client: ShopifyClient, out_dir: str,
    product_ids: list[str],
) -> int:
    """One file per product. Slow (1 call per product, throttled
    to 2 cps via the shared client). Where the Schema.org
    JSON-LD metafields actually live."""
    sub_dir = os.path.join(out_dir, "product-metafields")
    os.makedirs(sub_dir, exist_ok=True)
    written = 0
    for pid in product_ids:
        path = f"products/{pid}/metafields.json"
        try:
            payload = client.get(path)
        except urllib.error.HTTPError as exc:
            print(f"    ⚠ pid {pid}: HTTP {exc.code}")
            continue
        _write_json(
            os.path.join(sub_dir, f"{pid}.json"),
            payload,
        )
        written += 1
    return written


def _backup_blog_articles(
    client: ShopifyClient, out_dir: str,
    blogs: list[dict],
) -> int:
    sub_dir = os.path.join(out_dir, "articles")
    os.makedirs(sub_dir, exist_ok=True)
    total = 0
    for b in blogs:
        bid = b.get("id")
        if not bid:
            continue
        try:
            payload = client.get(
                f"blogs/{bid}/articles.json?limit=250",
            )
        except urllib.error.HTTPError as exc:
            print(f"    ⚠ blog {bid}: HTTP {exc.code}")
            continue
        articles = payload.get("articles") or []
        _write_json(
            os.path.join(sub_dir, f"{bid}.json"),
            payload,
        )
        total += len(articles)
    return total


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out", default="backups/",
        help=(
            "Parent directory for the snapshot folder. "
            "Default: backups/."
        ),
    )
    ap.add_argument(
        "--skip-metafields", action="store_true",
        help=(
            "Skip the per-product metafield dump (slow — 1 API "
            "call per product). Use for a fast core-snapshot."
        ),
    )
    args = ap.parse_args(argv)

    try:
        client = ShopifyClient.from_env(throttle_s=0.5)
    except ShopifyClientMisconfigured as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        return 2

    timestamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    out_dir = os.path.join(args.out, timestamp)
    os.makedirs(out_dir, exist_ok=True)
    print(f"Store: {client.url}")
    print(f"Output: {out_dir}\n")

    manifest: dict[str, object] = {
        "generated_at": timestamp,
        "store": client.url,
        "shopify_api_version": client.api_version,
        "counts": {},
    }

    # Resources we always back up — order kept stable so manifest
    # diffs are clean across snapshots.
    plan: list[tuple[str, str, str]] = [
        ("shop.json",                 "shop.json",                 "Shop metadata"),
        ("products.json?limit=250",   "products.json",             "Products + variants"),
        ("smart_collections.json?limit=250",
            "smart_collections.json",  "Smart collections"),
        ("custom_collections.json?limit=250",
            "custom_collections.json", "Custom collections"),
        ("pages.json?limit=250",      "pages.json",                "Pages (About/FAQ/etc)"),
        ("blogs.json?limit=250",      "blogs.json",                "Blogs"),
        ("script_tags.json?limit=250","script_tags.json",          "Script tags (pixels)"),
        ("webhooks.json?limit=250",   "webhooks.json",             "Webhook subscriptions"),
        ("redirects.json?limit=250",  "redirects.json",            "URL redirects"),
        ("shipping_zones.json",       "shipping_zones.json",       "Shipping zones"),
        ("policies.json",             "policies.json",             "Shop policies"),
        ("themes.json",               "themes.json",               "Theme list"),
    ]

    counts: dict[str, int] = {}
    for path, filename, label in plan:
        try:
            n = _backup_resource(
                client, out_dir, path, filename, label,
            )
            counts[label] = n
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {label}: {exc}")
            counts[label] = -2  # error marker
    manifest["counts"] = counts

    # ── Per-product metafields (slow path) ─────────────
    if not args.skip_metafields:
        print("\n  Per-product metafields (slow — 1 API call "
              "per product, ~0.5s each)")
        products_path = os.path.join(out_dir, "products.json")
        product_ids: list[str] = []
        if os.path.exists(products_path):
            with open(products_path, encoding="utf-8") as fh:
                payload = json.load(fh)
                for p in payload.get("products") or []:
                    if p.get("id"):
                        product_ids.append(str(p["id"]))
        if product_ids:
            n = _backup_product_metafields(
                client, out_dir, product_ids,
            )
            counts["Product metafields"] = n
            print(f"  ✓ {n}/{len(product_ids)} product metafield "
                  f"sets backed up")

    # ── Blog articles (depends on blog list) ───────────
    blogs_path = os.path.join(out_dir, "blogs.json")
    if os.path.exists(blogs_path):
        with open(blogs_path, encoding="utf-8") as fh:
            blogs_payload = json.load(fh)
        blogs = blogs_payload.get("blogs") or []
        if blogs:
            n = _backup_blog_articles(client, out_dir, blogs)
            counts["Articles"] = n
            print(f"  ✓ {n} articles across {len(blogs)} blog(s)")

    # Manifest is the last thing written so callers can use its
    # presence as the "snapshot complete" signal.
    _write_json(
        os.path.join(out_dir, "manifest.json"), manifest,
    )
    print(f"\n✓ Snapshot complete: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
