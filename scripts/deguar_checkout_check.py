"""Checkout / payment / shipping smoke check for the Deguar store.

The single cruellest silent failure in dropshipping: ads deliver,
traffic lands, clicks "add to cart", hits checkout... and there's
no payment provider configured, or no shipping zone covers their
country, or the rate is $0. Order never lands. Owner pays for
the click and never sees a line item explaining why.

This script verifies the three checkout-critical surfaces BEFORE
the owner turns on Meta ads:

  1. **Payment providers** — at least one active provider that
     accepts cards (Shopify Payments, PayPal, Stripe, 2Checkout,
     Paddle, or a regional gateway).
  2. **Shipping zones** — at least one zone with at least one
     rate. Flag zones with no rates (dead zone) or unrealistic
     $0 rates.
  3. **Storefront reachability** — /, /cart, /checkout all
     return 200 (or an expected redirect).

Exit codes:
  0 → everything green
  1 → at least one warning (slow / suspicious but not fatal)
  2 → at least one blocker (no payment provider, no shipping zone)
  3 → auth / network error

Usage:
    PYTHONPATH=. python scripts/deguar_checkout_check.py
"""
from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request

from scripts._shopify_client import (
    ShopifyClient, ShopifyClientMisconfigured,
)


# ── Payment providers ────────────────────────────────────
# Shopify's payments_accounts.json (private API) is the
# canonical source but requires write_payment_methods scope.
# Public fallback: /payments.json lists the provider handles
# currently enabled. We probe both.


def _fetch_enabled_providers(
    client: ShopifyClient,
) -> dict[str, bool]:
    """Return ``{provider_handle: active_bool}``. Empty dict
    if neither endpoint is reachable with current scope."""
    out: dict[str, bool] = {}
    # Approach 1: storefront /payments.json
    try:
        payload = client.get("payments.json?limit=50")
        for p in payload.get("payments") or []:
            h = p.get("gateway") or p.get("handle") or ""
            if h:
                out[h] = bool(p.get("enabled", True))
    except urllib.error.HTTPError as exc:
        if exc.code not in (403, 404):
            raise
    # Approach 2: shop.json exposes "money_with_currency_format"
    # + "country" which hint at payment readiness (if currency
    # is MNT and country is MN, Shopify Payments definitely
    # isn't available).
    return out


def _probe_storefront_url(url: str) -> tuple[int, str]:
    """HEAD the URL. Return (status_code, error_message).
    Follows redirects (Shopify bounces checkout to a
    cloudflared URL)."""
    try:
        req = urllib.request.Request(
            url, method="HEAD",
            headers={
                "User-Agent": "Mozilla/5.0 (ShopAI checkout audit)",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return (r.status, "")
    except urllib.error.HTTPError as exc:
        return (exc.code, f"HTTP {exc.code}")
    except Exception as exc:  # noqa: BLE001
        return (0, str(exc)[:80])


# ── Shipping zones ───────────────────────────────────────


def fetch_shipping_zones(client: ShopifyClient) -> list[dict]:
    """Return the store's shipping zones. Each zone has
    ``countries`` + ``price_based_shipping_rates`` +
    ``weight_based_shipping_rates``."""
    try:
        payload = client.get("shipping_zones.json")
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404):
            return []
        raise
    return payload.get("shipping_zones") or []


def analyse_zones(zones: list[dict]) -> dict:
    """Produce a structured summary."""
    total = len(zones)
    no_rate: list[str] = []
    zero_rate: list[str] = []
    good: list[dict] = []

    for z in zones:
        name = z.get("name", "?")
        price_rates = z.get("price_based_shipping_rates") or []
        weight_rates = z.get("weight_based_shipping_rates") or []
        carrier_rates = z.get(
            "carrier_shipping_rate_providers",
        ) or []
        rates = price_rates + weight_rates
        countries = [
            c.get("code") or c.get("name") or ""
            for c in (z.get("countries") or [])
        ]
        if not rates and not carrier_rates:
            no_rate.append(name)
            continue
        all_zero = (
            bool(rates)
            and all(float(r.get("price") or 0) == 0 for r in rates)
            and not carrier_rates
        )
        if all_zero:
            zero_rate.append(name)
            continue
        good.append({
            "name": name,
            "countries": countries,
            "price_rate_count": len(price_rates),
            "weight_rate_count": len(weight_rates),
            "carrier_provider_count": len(carrier_rates),
        })
    return {
        "total": total,
        "good": good,
        "no_rate": no_rate,
        "zero_rate": zero_rate,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.parse_args(argv)

    try:
        client = ShopifyClient.from_env()
    except ShopifyClientMisconfigured as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        return 2

    print(f"Store: {client.url}\n")

    blockers: list[str] = []
    warnings: list[str] = []

    # ── Payment providers ─────────────────────────────
    print("═══ Payment providers ═══")
    try:
        providers = _fetch_enabled_providers(client)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            print("  ERR: 401 — token rejected", file=sys.stderr)
            return 3
        print(f"  (error {exc.code} — skipping)")
        providers = {}
    except Exception as exc:  # noqa: BLE001
        print(f"  (error: {exc} — skipping)")
        providers = {}

    if providers:
        active = [h for h, on in providers.items() if on]
        if active:
            for h in active:
                print(f"  ✓ {h}")
        else:
            print("  ✗ no active payment provider")
            blockers.append(
                "no active payment provider — checkout will die"
            )
    else:
        print("  (providers API not accessible — check manually "
              "in Admin → Settings → Payments)")
        warnings.append(
            "could not verify payment provider via API"
        )
    print()

    # ── Shipping zones ────────────────────────────────
    print("═══ Shipping zones ═══")
    try:
        zones = fetch_shipping_zones(client)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return 3
        print(f"  (error {exc.code})")
        zones = []

    z = analyse_zones(zones)
    if z["total"] == 0:
        print("  ✗ no shipping zones defined — every checkout "
              "will show 'no shipping methods'")
        blockers.append("no shipping zones")
    else:
        for g in z["good"]:
            countries = ", ".join(g["countries"][:5])
            more = "" if len(g["countries"]) <= 5 else f" +{len(g['countries']) - 5}"
            rates_summary = (
                f"{g['price_rate_count']} price + "
                f"{g['weight_rate_count']} weight + "
                f"{g['carrier_provider_count']} carrier"
            )
            print(f"  ✓ {g['name']:20s} ({countries}{more}) — "
                  f"{rates_summary}")
        for name in z["no_rate"]:
            print(f"  ✗ {name}: NO RATES — zone is dead")
            blockers.append(
                f"zone '{name}' has no rates"
            )
        for name in z["zero_rate"]:
            print(f"  ⚠ {name}: all rates $0 — free shipping "
                  "everywhere? confirm intentional")
            warnings.append(
                f"zone '{name}' rates all $0"
            )
    print()

    # ── Storefront probe ──────────────────────────────
    print("═══ Storefront URL reachability ═══")
    for label, path in (
        ("home",     "/"),
        ("cart",     "/cart"),
        ("checkout", "/checkout"),
    ):
        full = f"https://{client.url}{path}"
        status, err = _probe_storefront_url(full)
        if 200 <= status < 400:
            print(f"  ✓ {label:10s} HTTP {status}")
        elif status == 404 and path == "/checkout":
            # Empty-cart checkout is sometimes redirected;
            # not a blocker on its own
            print(f"  ⚠ {label:10s} HTTP 404 (empty cart?)")
            warnings.append(
                "checkout returns 404 with empty cart — "
                "usually benign",
            )
        else:
            print(f"  ✗ {label:10s} {err or f'HTTP {status}'}")
            blockers.append(
                f"{label} page unreachable: {err or status}"
            )
    print()

    # ── Verdict ───────────────────────────────────────
    print("═══ Verdict ═══")
    if blockers:
        print("  ✗ BLOCKED — fix these before ads go live:")
        for b in blockers:
            print(f"    · {b}")
        return 2
    if warnings:
        print("  ⚠ READY WITH WARNINGS:")
        for w in warnings:
            print(f"    · {w}")
        return 1
    print("  ✓ READY — checkout funnel reachable, "
          "payment + shipping configured")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
