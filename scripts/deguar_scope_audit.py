"""Shopify OAuth scope audit — compare granted scopes to ShopAI's needs.

Deguar's tracker (CLAUDE.md §8) flagged 5 missing scopes blocking
revenue-path features: discounts, policies, menus, theme
customisation. This script reads the store's currently-granted
scopes from the ``/admin/oauth/access_scopes.json`` endpoint and
diffs against the canonical list below.

Usage:

    PYTHONPATH=. python scripts/deguar_scope_audit.py

Output:
    ✓ granted (N)
    ✗ missing (M)  ← each with the feature it unblocks

No writes, read-only. Safe to re-run.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request


# ── Canonical scope needs ────────────────────────────────
# One entry per scope. Each "why" is owner-facing copy.

_NEEDS: list[dict[str, str]] = [
    # Reads — core observability
    {"scope": "read_products", "why": "catalog fetch + analytics"},
    {"scope": "read_orders", "why": "order webhook → learning loop"},
    {"scope": "read_customers", "why": "segmentation + retention"},
    {"scope": "read_inventory", "why": "stock signal for sourcing"},
    {"scope": "read_content", "why": "About/FAQ/blog introspection"},
    {"scope": "read_themes", "why": "theme state for customisation"},
    {"scope": "read_price_rules", "why": "discount audit"},
    {"scope": "read_analytics", "why": "dashboard + forecasting"},
    # Writes — revenue path
    {"scope": "write_products", "why": "product CRUD + image upload"},
    {"scope": "write_inventory", "why": "stock updates from supplier sync"},
    {"scope": "write_content", "why": "blog posts, pages (About/FAQ)"},
    {"scope": "write_themes", "why": "theme customisation + settings_data"},
    {"scope": "write_price_rules", "why": "auto-create discount codes"},
    {"scope": "write_discounts", "why": "new-format discount codes (2024+)"},
    {"scope": "write_shop_policies", "why": "auto-publish privacy/ToS/refund"},
    {"scope": "write_online_store_navigation", "why": "menu updates (header/footer)"},
    # Optional but useful
    {"scope": "write_script_tags", "why": "tracking pixels (Meta/TikTok/GA)"},
    {"scope": "write_marketing_events", "why": "campaign attribution"},
]


def _api(path: str, *, url: str, token: str, retries: int = 4) -> dict:
    full = f"https://{url}/admin/{path}"
    for i in range(retries):
        try:
            req = urllib.request.Request(full, headers={
                "X-Shopify-Access-Token": token,
                "Accept": "application/json",
                "User-Agent": "ShopAI/scope-audit",
            })
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503) and i < retries - 1:
                wait = 2 ** (i + 1)
                print(f"  {e.code} — retry in {wait}s",
                      file=sys.stderr)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("retries exhausted")


def fetch_granted(*, url: str, token: str) -> list[str]:
    """Return the list of scope handles currently granted by
    the target store to ShopAI's custom/private app token."""
    payload = _api(
        "oauth/access_scopes.json", url=url, token=token,
    )
    scopes = payload.get("access_scopes") or []
    return sorted(
        {s.get("handle", "") for s in scopes if s.get("handle")}
    )


def diff(granted: list[str]) -> dict[str, list[dict]]:
    """Return {'granted': [...], 'missing': [...]} by scope handle.

    ``missing`` preserves the ``why`` metadata from _NEEDS so
    the operator sees what each missing scope unblocks."""
    have = set(granted)
    granted_out: list[dict[str, str]] = []
    missing_out: list[dict[str, str]] = []
    for need in _NEEDS:
        row = dict(need)
        if need["scope"] in have:
            granted_out.append(row)
        else:
            missing_out.append(row)
    # Also surface any granted scopes ShopAI doesn't claim to
    # need — useful for spotting over-granted perms.
    needed = {n["scope"] for n in _NEEDS}
    extra = sorted(have - needed)
    return {
        "granted": granted_out,
        "missing": missing_out,
        "extra": [{"scope": s} for s in extra],
    }


def print_report(d: dict[str, list[dict]]) -> None:
    print(f"═══ Granted ({len(d['granted'])}) ═══")
    for row in d["granted"]:
        print(f"  ✓ {row['scope']:35s} — {row['why']}")
    print()
    if d["extra"]:
        print(f"═══ Granted but not claimed by ShopAI "
              f"({len(d['extra'])}) ═══")
        for row in d["extra"]:
            print(f"  ~ {row['scope']}")
        print()
    if d["missing"]:
        print(f"═══ MISSING ({len(d['missing'])}) — blocks "
              f"these features ═══")
        for row in d["missing"]:
            print(f"  ✗ {row['scope']:35s} — {row['why']}")
        print()
        print("How to fix (custom/private app):")
        print("  1. Shopify Admin → Settings → Apps → "
              "Develop apps")
        print("  2. Open your ShopAI app → Configuration → "
              "Admin API integration")
        print("  3. Tick each missing scope above → Save → "
              "Reinstall app")
        print("  4. Copy the new Admin API access token → "
              "SHOPAI_SHOPIFY_KEY in .env")
        print("  5. Re-run this script to confirm")
    else:
        print("✓ All required scopes granted — no action needed")


def main(argv: list[str] | None = None) -> int:
    url = os.environ.get("SHOPAI_SHOPIFY_URL") or ""
    token = (
        os.environ.get("SHOPAI_SHOPIFY_KEY")
        or os.environ.get("SHOPAI_SHOPIFY_TOKEN")
        or ""
    )
    if not url or not token:
        print(
            "ERR: set SHOPAI_SHOPIFY_URL + SHOPAI_SHOPIFY_KEY",
            file=sys.stderr,
        )
        return 2

    print(f"Store: {url}\n")
    try:
        granted = fetch_granted(url=url, token=token)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            print("ERR: token rejected — is SHOPAI_SHOPIFY_KEY "
                  "correct + unexpired?", file=sys.stderr)
            return 3
        if exc.code == 403:
            print("ERR: 403 on /oauth/access_scopes.json — "
                  "token may lack introspection scope. For "
                  "custom apps this should still work; for "
                  "public apps you may need 'read_all_orders' "
                  "or a fresh install.", file=sys.stderr)
            return 3
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"ERR: cannot reach Shopify: {exc}",
              file=sys.stderr)
        return 3

    d = diff(granted)
    print_report(d)
    return 0 if not d["missing"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
