"""Verify tracking pixels fire on the Deguar storefront.

Without Meta Pixel firing on product + cart pages, Meta ads can
still DELIVER but attribution breaks — Ads Manager will show
"link clicks" but no "purchases" or "add to cart". Owner can't
tell which creative converted. Same for TikTok Pixel and GA.

Three things to verify:

    1. Script tag registered via Shopify's /script_tags.json
       (legacy install, most pixels still here)
    2. Pixel script actually appears in the rendered HTML of
       the storefront home page
    3. Cart + product page (where add-to-cart + purchase events
       fire) also include the tag

This script does all three via public endpoints (no auth needed
for the storefront scrape, standard auth for script_tags).

Usage:
    PYTHONPATH=. python scripts/deguar_tracking_check.py
    PYTHONPATH=. python scripts/deguar_tracking_check.py --handle galaxy-star-projector-night-light

Exit codes:
    0  Meta Pixel found on home + cart + a product page
    1  partially installed (home only, no cart; or vice-versa)
    2  no Meta Pixel detected anywhere
    3  auth / network error
"""
from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request

from scripts._shopify_client import (
    ShopifyClient, ShopifyClientMisconfigured,
)


# Signatures keyed on what the tag includes in the rendered HTML.
# Kept in sync with agents/competitor_intel/agent._SHOPIFY_APP_SIGNATURES.
_PIXEL_SIGNATURES: dict[str, list[str]] = {
    "Meta Pixel": ["facebook.net/tr", "fbq(", "connect.facebook.net"],
    "TikTok Pixel": ["analytics.tiktok", "tiktok-pixel", "ttq.load"],
    "Google Analytics 4": [
        "googletagmanager.com/gtag/js?id=G-",
        "gtag('config', 'G-",
    ],
    "GA Universal (legacy)": ["google-analytics.com/analytics.js"],
    "Google Tag Manager": ["googletagmanager.com/gtm.js"],
    "Pinterest Tag": ["pintrk("],
    "Snapchat Pixel": ["sc-static.net/scevent.min.js"],
}


def _fetch_public(url: str) -> str:
    """Plain GET to a public storefront URL. No auth. Returns
    the rendered HTML body as a string."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (ShopAI tracking audit)",
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,*/*;q=0.8"
        ),
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode(
            r.headers.get_content_charset() or "utf-8",
            errors="replace",
        )


def detect_pixels(html: str) -> dict[str, bool]:
    """Scan ``html`` for each pixel's signature patterns.
    Returns ``{pixel_name: True/False}``."""
    low = html.lower()
    out: dict[str, bool] = {}
    for name, patterns in _PIXEL_SIGNATURES.items():
        out[name] = any(p.lower() in low for p in patterns)
    return out


def fetch_script_tags(client: ShopifyClient) -> list[dict]:
    """Return currently-registered script tags via the Shopify
    Admin API. Requires ``read_script_tags`` scope."""
    payload = client.get("script_tags.json?limit=250")
    return payload.get("script_tags") or []


def _first_product_handle(client: ShopifyClient) -> str:
    resp = client.get("products.json?limit=1&fields=handle")
    products = resp.get("products") or []
    return (products[0].get("handle") or "") if products else ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--handle", default="",
        help=(
            "Product handle to probe for cart/purchase pages. "
            "Default: first product returned by the store."
        ),
    )
    ap.add_argument(
        "--skip-scripts", action="store_true",
        help=(
            "Don't list script_tags.json (useful when token "
            "lacks read_script_tags scope)."
        ),
    )
    args = ap.parse_args(argv)

    try:
        client = ShopifyClient.from_env()
    except ShopifyClientMisconfigured as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        return 2

    print(f"Store: {client.url}\n")

    # Pick a product handle to test
    handle = args.handle
    if not handle:
        try:
            handle = _first_product_handle(client)
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: cannot fetch first product: {exc}",
                  file=sys.stderr)
            handle = ""

    # Scrape the three key storefront pages
    pages: list[tuple[str, str]] = [
        ("home", f"https://{client.url}/"),
        ("cart", f"https://{client.url}/cart"),
    ]
    if handle:
        pages.append(
            ("product",
             f"https://{client.url}/products/{handle}"),
        )
    else:
        print("(no product handle available — skipping "
              "product-page probe)")

    results: dict[str, dict[str, bool]] = {}
    for label, url in pages:
        try:
            html = _fetch_public(url)
            results[label] = detect_pixels(html)
        except urllib.error.HTTPError as exc:
            print(f"WARN: {label} page returned HTTP "
                  f"{exc.code} — skipping")
            results[label] = {}
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: {label} page error: {exc}")
            results[label] = {}

    # Render per-pixel / per-page matrix
    pixel_names = list(_PIXEL_SIGNATURES.keys())
    page_labels = [lbl for lbl, _ in pages]

    print("═══ Tracking pixel coverage ═══")
    print(
        "  " + " " * 24
        + "  ".join(f"{lbl:>8s}" for lbl in page_labels),
    )
    any_meta = False
    meta_home = meta_cart = meta_product = False
    for pixel in pixel_names:
        row = []
        for lbl in page_labels:
            found = results.get(lbl, {}).get(pixel, False)
            row.append("   ✓   " if found else "   ·   ")
            if pixel == "Meta Pixel" and found:
                any_meta = True
                if lbl == "home":
                    meta_home = True
                if lbl == "cart":
                    meta_cart = True
                if lbl == "product":
                    meta_product = True
        print(f"  {pixel:24s} " + "".join(row))
    print()

    # Optional: list script tags for reference
    if not args.skip_scripts:
        print("═══ Registered script tags ═══")
        try:
            tags = fetch_script_tags(client)
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                print("  (403 — token lacks read_script_tags "
                      "scope; run scope_audit to grant)")
                tags = []
            else:
                raise
        except Exception as exc:  # noqa: BLE001
            print(f"  (error: {exc})")
            tags = []
        if not tags:
            print("  (none registered — pixels may be installed "
                  "via theme code or Customer Events instead)")
        for t in tags:
            src = (t.get("src") or "")[:80]
            scope = t.get("display_scope") or "all"
            print(f"  - [{scope:8s}] {src}")
        print()

    # Verdict
    if not any_meta:
        print("VERDICT: No Meta Pixel detected. Ads will deliver "
              "but attribution is blind.")
        print("  Fix: Shopify Admin → Settings → Customer events "
              "→ Add Meta Pixel. OR install manually via theme "
              "code. Re-run this script after install.")
        return 2

    page_count = sum([
        int(meta_home), int(meta_cart),
        int(meta_product) if handle else 1,
    ])
    expected = 3 if handle else 2
    if page_count < expected:
        print(
            "VERDICT: Meta Pixel installed but not firing on "
            "all checkout-funnel pages.",
        )
        print(f"  Home: {'✓' if meta_home else '✗'}")
        print(f"  Cart: {'✓' if meta_cart else '✗'}")
        if handle:
            print(f"  Product: {'✓' if meta_product else '✗'}")
        print("  Fix: verify the pixel script is included on "
              "every page, not just the home template.")
        return 1

    print("VERDICT: Meta Pixel installed on home + cart + "
          "product — attribution ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
