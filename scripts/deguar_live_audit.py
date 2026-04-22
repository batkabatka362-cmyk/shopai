"""Live audit of the Deguar Shopify store — images, duplicates, pricing.

Run this on your OWN machine (the sandbox blocks outbound DNS so
results from here are stale-cache only). Needs ``SHOPAI_SHOPIFY_URL``
and ``SHOPAI_SHOPIFY_KEY`` in ``.env`` or the shell env.

Usage:

    cd shopai
    PYTHONPATH=. python scripts/deguar_live_audit.py
    PYTHONPATH=. python scripts/deguar_live_audit.py --only drafts

Read-only — no writes, no risk. Can be re-run freely.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


def _api(path: str, *, url: str, token: str, retries: int = 4) -> dict:
    full = f"https://{url}/admin/api/2024-10/{path}"
    for i in range(retries):
        try:
            req = urllib.request.Request(full, headers={
                "X-Shopify-Access-Token": token,
                "Accept": "application/json",
                "User-Agent": "ShopAI/deguar-audit",
            })
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503) and i < retries - 1:
                wait = 2 ** (i + 1)
                print(f"  {e.code} — retry in {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("retries exhausted")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--only",
        choices=("images", "drafts", "duplicates", "pricing", "all"),
        default="all",
        help="Which check to run (default: all).",
    )
    args = ap.parse_args()

    url = os.environ.get("SHOPAI_SHOPIFY_URL") or ""
    token = (
        os.environ.get("SHOPAI_SHOPIFY_KEY")
        or os.environ.get("SHOPAI_SHOPIFY_TOKEN")
        or ""
    )
    if not url or not token:
        print(
            "ERR: set SHOPAI_SHOPIFY_URL and SHOPAI_SHOPIFY_KEY "
            "in your .env",
            file=sys.stderr,
        )
        return 2

    print(f"Store: {url}")
    try:
        count = _api("products/count.json", url=url, token=token)["count"]
    except Exception as exc:  # noqa: BLE001
        print(f"ERR: cannot reach Shopify: {exc}", file=sys.stderr)
        return 3
    print(f"Total products: {count}\n")

    products: list[dict] = []
    resp = _api(
        "products.json?limit=250&fields=id,title,status,handle,"
        "images,variants,tags",
        url=url, token=token,
    )
    products = resp.get("products", [])

    # ── Image coverage ─────────────────────────────────────
    if args.only in ("images", "all"):
        print("═══ Image coverage ═══")
        zero = [p for p in products if not p.get("images")]
        one = [p for p in products if len(p.get("images") or []) == 1]
        many = [p for p in products if len(p.get("images") or []) >= 2]
        print(f"  0 images (BLOCKING): {len(zero)}")
        print(f"  1 image  (weak):     {len(one)}")
        print(f"  2+ images (OK):      {len(many)}")
        if zero:
            print("\n  ── No images ──")
            for p in zero:
                print(f"    [{p['status']:7s}] {p['title'][:60]}")
        if one:
            print("\n  ── 1 image only (recommend 4-6 each) ──")
            for p in one:
                print(f"    [{p['status']:7s}] {p['title'][:60]}")
        print()

    # ── Status / drafts ────────────────────────────────────
    if args.only in ("drafts", "all"):
        print("═══ Draft / archived ═══")
        by_status: dict[str, list[str]] = {}
        for p in products:
            by_status.setdefault(p["status"], []).append(p["title"])
        for status, titles in sorted(by_status.items()):
            print(f"  {status}: {len(titles)}")
            for t in titles[:5]:
                print(f"    - {t[:70]}")
            if len(titles) > 5:
                print(f"    ... +{len(titles) - 5} more")
        print()

    # ── Duplicates ─────────────────────────────────────────
    if args.only in ("duplicates", "all"):
        print("═══ Possible duplicates (fuzzy title match) ═══")
        dups: list[tuple[str, str]] = []
        titles = [(p["id"], p["title"].lower()) for p in products]
        for i, (id_a, t_a) in enumerate(titles):
            for id_b, t_b in titles[i+1:]:
                # Share 3+ consecutive words?
                words_a = set(t_a.split())
                words_b = set(t_b.split())
                overlap = words_a & words_b
                if len(overlap) >= 2 and (
                    "phone" in overlap or "humidifier" in overlap
                    or "projector" in overlap or "diffuser" in overlap
                    or "charger" in overlap or "lamp" in overlap
                ):
                    dups.append((
                        f"{id_a}: {t_a[:50]}",
                        f"{id_b}: {t_b[:50]}",
                    ))
        if dups:
            for a, b in dups:
                print(f"    • {a}")
                print(f"      {b}")
                print()
        else:
            print("  (none detected)\n")

    # ── Pricing / margin ───────────────────────────────────
    if args.only in ("pricing", "all"):
        print("═══ Pricing + margin ═══")
        prices = []
        for p in products:
            for v in p.get("variants") or []:
                try:
                    price = float(v.get("price") or 0)
                    cost = float(
                        (v.get("inventory_item") or {}).get("cost")
                        or 0,
                    )
                except (TypeError, ValueError):
                    continue
                if price > 0:
                    margin = (price - cost) / price * 100 if cost else None
                    prices.append((price, cost, margin, p["title"]))
        prices.sort()
        print(f"  Range: ${prices[0][0]:.2f}–${prices[-1][0]:.2f}")
        med = prices[len(prices) // 2][0] if prices else 0
        print(f"  Median: ${med:.2f}")
        print(f"  Under $20: {sum(1 for p in prices if p[0] < 20)}")
        print(f"  $20-40: {sum(1 for p in prices if 20 <= p[0] < 40)}")
        print(f"  Over $40: {sum(1 for p in prices if p[0] >= 40)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
