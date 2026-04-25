"""Shopify webhook health check — verify the order learning loop.

Without the 5 reward-signal webhook subscriptions wired + their
callback URL publicly reachable, ShopAI's order-driven learning
never fires:

    orders/create     → first-order attribution
    orders/paid       → revenue signal for brain backfill
    orders/cancelled  → churn signal
    products/update   → catalog invalidation
    app/uninstalled   → self-delete token on disconnect

This script:

  1. Lists currently-registered webhooks via Shopify's
     /admin/api/2024-10/webhooks.json.
  2. Diffs against the canonical 5-topic "need" list below.
  3. Reports the callback URL each topic points at — and flags
     if it looks like localhost / tunneltrial-expired.
  4. Fetches Shopify's recent delivery attempts via the
     delivery API and shows the last N failures per topic.

Read-only. Safe to re-run. No writes, no token rotation.

Usage:
    PYTHONPATH=. python scripts/deguar_webhook_check.py
    PYTHONPATH=. python scripts/deguar_webhook_check.py --show-failures 20
"""
from __future__ import annotations

import argparse
import sys
import urllib.error

from scripts._shopify_client import (
    ShopifyClient, ShopifyClientMisconfigured,
)


# ── Canonical topic needs ────────────────────────────────

_NEEDS: list[dict[str, str]] = [
    {
        "topic": "orders/create",
        "why": "first-order attribution + channel tagging",
    },
    {
        "topic": "orders/paid",
        "why": "revenue signal for Deliberation back-fill",
    },
    {
        "topic": "orders/cancelled",
        "why": "churn signal / refund detection",
    },
    {
        "topic": "products/update",
        "why": "invalidate catalog cache on edits",
    },
    {
        "topic": "app/uninstalled",
        "why": "self-revoke token if owner disconnects app",
    },
]


# Heuristics for "does the callback URL look reachable from
# the public internet?" — can't truly verify without a real
# HEAD against the URL, but these catch the most common
# silent-failure modes.
_UNREACHABLE_PATTERNS = (
    "localhost", "127.0.0.1", ".local", "192.168.",
    "10.0.", "172.16.", "0.0.0.0",
)


def _flag_url(address: str) -> str:
    """Return a warning tag if the address looks unreachable,
    else empty string."""
    if not address:
        return "MISSING"
    low = address.lower()
    for bad in _UNREACHABLE_PATTERNS:
        if bad in low:
            return "UNREACHABLE (internal address)"
    if low.startswith("http://") and not low.startswith("http://localhost"):
        return "HTTP — Shopify requires HTTPS"
    if "trycloudflare.com" in low:
        return "CLOUDFLARE TRIAL — rotates on restart"
    if not low.startswith("https://"):
        return "NOT HTTPS"
    return ""


def fetch_webhooks(client: ShopifyClient) -> list[dict]:
    """Return the list of currently-registered webhooks."""
    payload = client.get("webhooks.json?limit=250")
    return payload.get("webhooks") or []


def diff(registered: list[dict]) -> dict[str, list[dict]]:
    """Return ``{'covered': [...], 'missing': [...],
    'extra': [...]}`` — each list sorted for determinism."""
    by_topic: dict[str, list[dict]] = {}
    for wh in registered:
        topic = wh.get("topic") or ""
        if not topic:
            continue
        by_topic.setdefault(topic, []).append(wh)

    covered: list[dict] = []
    missing: list[dict] = []
    for need in _NEEDS:
        t = need["topic"]
        hooks = by_topic.get(t) or []
        if hooks:
            # For each hit, attach URL + freshness flag
            for h in hooks:
                addr = h.get("address") or ""
                covered.append({
                    "topic": t,
                    "why": need["why"],
                    "id": h.get("id"),
                    "address": addr,
                    "format": h.get("format"),
                    "flag": _flag_url(addr),
                })
        else:
            missing.append(dict(need))

    needed_topics = {n["topic"] for n in _NEEDS}
    extra: list[dict] = []
    for t, hooks in by_topic.items():
        if t in needed_topics:
            continue
        for h in hooks:
            extra.append({
                "topic": t,
                "id": h.get("id"),
                "address": h.get("address") or "",
            })

    return {
        "covered": sorted(covered, key=lambda r: r["topic"]),
        "missing": sorted(missing, key=lambda r: r["topic"]),
        "extra": sorted(extra, key=lambda r: r["topic"]),
    }


def print_report(d: dict[str, list[dict]]) -> None:
    print(f"═══ Covered topics ({len(d['covered'])}) ═══")
    if not d["covered"]:
        print("  (none — the learning loop is entirely silent)")
    for row in d["covered"]:
        flag = row["flag"]
        tag = f"  ⚠ {flag}" if flag else ""
        print(f"  ✓ {row['topic']:22s} → {row['address'][:60]}{tag}")
        print(f"      ({row['why']})")
    print()
    if d["missing"]:
        print(f"═══ MISSING ({len(d['missing'])}) ═══")
        for row in d["missing"]:
            print(f"  ✗ {row['topic']:22s} — {row['why']}")
        print()
        print("How to fix:")
        print("  PYTHONPATH=. python -c 'from core.webhooks.register"
              " import register_all; print(register_all())'")
        print("  or set SHOPAI_WEBHOOK_CALLBACK_URL in .env + run "
              "`shopai webhooks register`.")
        print()
    if d["extra"]:
        print(f"═══ Extra (not claimed by ShopAI) "
              f"({len(d['extra'])}) ═══")
        for row in d["extra"]:
            print(f"  ~ {row['topic']:22s} → {row['address'][:60]}")
        print()


def print_recent_deliveries(
    client: ShopifyClient, limit: int,
) -> None:
    """Best-effort — Shopify's webhook delivery API varies by
    plan tier. If it 404s or the store is on a tier that
    doesn't expose it, skip quietly."""
    print(f"═══ Recent deliveries (last {limit}) ═══")
    try:
        # The dedicated delivery-attempts endpoint is only on
        # app-bridge plans; fall back to listing webhook events.
        events = client.get(
            f"events.json?limit={limit}&filter=Webhook"
        ).get("events") or []
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 403):
            print("  (delivery-attempt API not available on "
                  "this plan tier — skip)")
            return
        raise
    if not events:
        print("  (no recent webhook events in the audit log)")
        return
    for ev in events[:limit]:
        print(f"  {ev.get('created_at', '?'):24s} "
              f"{ev.get('subject_type', ''):12s} "
              f"{ev.get('verb', '')}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--show-failures", type=int, default=0,
        help=(
            "Also fetch + display the last N webhook events "
            "from Shopify's audit log (0 = skip; default 0). "
            "Only some plan tiers expose this."
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
        registered = fetch_webhooks(client)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            print(
                "ERR: token rejected — SHOPAI_SHOPIFY_KEY "
                "correct + unexpired?",
                file=sys.stderr,
            )
            return 3
        if exc.code == 403:
            print(
                "ERR: 403 on webhooks.json — token likely "
                "missing the read_webhooks/write_webhooks "
                "scope. Run scripts/deguar_scope_audit.py to "
                "confirm + grant it in the app config.",
                file=sys.stderr,
            )
            return 3
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"ERR: cannot reach Shopify: {exc}", file=sys.stderr)
        return 3

    d = diff(registered)
    print_report(d)

    if args.show_failures > 0:
        print_recent_deliveries(client, args.show_failures)

    # Exit code semantics:
    #   0 → all 5 topics covered + every URL looks reachable
    #   1 → covered but some URLs flagged unreachable
    #   2 → missing some topics
    if d["missing"]:
        return 2
    any_bad = any(row["flag"] for row in d["covered"])
    return 1 if any_bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
