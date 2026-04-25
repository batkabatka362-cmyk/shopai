"""Shopify OAuth scope audit — compare granted scopes to ShopAI's needs.

Source of truth: ``core.auth.shopify_scopes``. Every wave 1-5
resource contributes to the canonical list there; this script
fetches the store's currently-granted scopes from
``/admin/oauth/access_scopes.json`` and diffs.

Usage:

    PYTHONPATH=. python scripts/deguar_scope_audit.py
    PYTHONPATH=. python scripts/deguar_scope_audit.py --plus

Output:
    ✓ granted (N)
    ✗ missing (M)  ← each with the feature it unblocks, plus
                     wave tags so owner can tie a missing scope
                     to the code that needs it

No writes, read-only. Safe to re-run.
"""
from __future__ import annotations

import argparse
import sys
import urllib.error

from core.auth.shopify_scopes import (
    Scope,
    diff_granted,
    plus_scopes,
    recommended_scopes,
    required_scopes,
)
from scripts._shopify_client import (
    ShopifyClient, ShopifyClientMisconfigured,
)


def fetch_granted(*, url: str, token: str) -> list[str]:
    """Return the list of scope handles currently granted by
    the target store to ShopAI's custom/private app token."""
    client = ShopifyClient(url=url, token=token)
    payload = client.oauth_get("oauth/access_scopes.json")
    scopes = payload.get("access_scopes") or []
    return sorted(
        {s.get("handle", "") for s in scopes if s.get("handle")}
    )


def _fmt_scope(s: Scope, *, show_waves: bool = True) -> str:
    tag = f" [{s.tier}]"
    waves = (
        f"  (waves: {', '.join(s.waves)})"
        if show_waves and s.waves else ""
    )
    return f"{s.handle:40s}{tag:16s} — {s.why}{waves}"


def print_report(d: dict[str, list[Scope]]) -> int:
    granted = d["granted"]
    missing = d["missing"]
    extra = d["extra"]

    # Separate missing required vs missing recommended vs
    # missing plus — owner sees severity immediately.
    missing_req = [s for s in missing if s.tier == "required"]
    missing_rec = [s for s in missing if s.tier == "recommended"]
    missing_plus = [s for s in missing if s.tier == "plus_only"]

    print(f"═══ Granted ({len(granted)}) ═══")
    for s in granted:
        print(f"  ✓ {_fmt_scope(s, show_waves=False)}")
    print()

    if extra:
        print(
            f"═══ Granted but not claimed by ShopAI "
            f"({len(extra)}) ═══"
        )
        for s in extra:
            print(f"  ~ {s.handle}")
        print()

    if missing_req:
        print(
            f"═══ MISSING REQUIRED ({len(missing_req)}) "
            "— these block revenue features ═══"
        )
        for s in missing_req:
            print(f"  ✗ {_fmt_scope(s)}")
        print()

    if missing_rec:
        print(
            f"═══ Missing recommended ({len(missing_rec)}) "
            "— enable to unlock optional features ═══"
        )
        for s in missing_rec:
            print(f"  • {_fmt_scope(s)}")
        print()

    if missing_plus:
        print(
            f"═══ Missing Plus-only ({len(missing_plus)}) "
            "— ignore unless on Shopify Plus ═══"
        )
        for s in missing_plus:
            print(f"  ~ {_fmt_scope(s)}")
        print()

    if not missing_req and not missing_rec:
        print("✓ All required + recommended scopes granted — "
              "no action needed")
        return 0

    print("How to fix (custom / private app):")
    print("  1. Shopify Admin → Settings → Apps → "
          "Develop apps")
    print("  2. Open your ShopAI app → Configuration → "
          "Admin API integration")
    print("  3. Tick each missing scope above → Save → "
          "Reinstall app")
    print("  4. Copy the new Admin API access token → "
          "SHOPAI_SHOPIFY_KEY in .env")
    print("  5. Re-run this script to confirm")
    print()
    print("How to fix (public / OAuth app):")
    print("  The OAuth redirect already requests the full "
          "canonical set via core.auth.shopify_scopes."
          "scope_string(). Re-trigger the install flow "
          "and approve the new scope list.")
    return 1 if missing_req else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--list-only", action="store_true",
        help="Print canonical scope list without hitting Shopify",
    )
    ap.add_argument(
        "--plus", action="store_true",
        help="Include Plus-only scopes in the required set",
    )
    args = ap.parse_args(argv)

    if args.list_only:
        print(f"Required ({len(required_scopes())}):")
        for s in required_scopes():
            print(f"  {_fmt_scope(s)}")
        print()
        print(f"Recommended ({len(recommended_scopes())}):")
        for s in recommended_scopes():
            print(f"  {_fmt_scope(s)}")
        print()
        print(f"Plus-only ({len(plus_scopes())}):")
        for s in plus_scopes():
            print(f"  {_fmt_scope(s)}")
        return 0

    try:
        client = ShopifyClient.from_env()
    except ShopifyClientMisconfigured as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        return 2

    print(f"Store: {client.url}\n")
    try:
        granted = fetch_granted(
            url=client.url, token=client.token,
        )
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            print(
                "ERR: token rejected — is SHOPAI_SHOPIFY_KEY "
                "correct + unexpired?",
                file=sys.stderr,
            )
            return 3
        if exc.code == 403:
            print(
                "ERR: 403 on /oauth/access_scopes.json — "
                "token may lack introspection scope. For "
                "custom apps this should still work; for "
                "public apps you may need 'read_all_orders' "
                "or a fresh install.",
                file=sys.stderr,
            )
            return 3
        raise
    except Exception as exc:  # noqa: BLE001
        print(
            f"ERR: cannot reach Shopify: {exc}",
            file=sys.stderr,
        )
        return 3

    d = diff_granted(granted)
    return print_report(d)


if __name__ == "__main__":
    raise SystemExit(main())
