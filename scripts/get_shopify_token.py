#!/usr/bin/env python3
"""One-shot Shopify token fetcher.

Usage:
    python scripts/get_shopify_token.py \
        --shop my-store.myshopify.com \
        --client-id  <client-id> \
        --client-secret <client-secret>

What it does:
    1. POSTs ``grant_type=client_credentials`` to Shopify's token
       endpoint (form-encoded, per the 2026 Dev Dashboard flow).
    2. Prints the resulting access token + expiry to stdout.
    3. Optionally writes/updates ``.env`` with
       ``SHOPAI_SHOPIFY_URL``, ``SHOPAI_SHOPIFY_CLIENT_ID``,
       ``SHOPAI_SHOPIFY_CLIENT_SECRET`` so the runtime can refresh
       on its own going forward.

Notes:
    * The app must already be installed on the store (Dev Dashboard →
      Distribution → Custom distribution → Generate install link).
      Without an install record Shopify rejects client_credentials
      with HTTP 400 and ``invalid_request``.
    * Tokens expire in ~24h. Long-running processes should hold onto
      the client_id + client_secret (not the token) and let
      ``core.auth.shopify_auth.ShopifyAuth`` refresh in-place.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _normalize_shop(raw: str) -> str:
    s = raw.strip().rstrip("/")
    if s.startswith("https://"):
        s = s[len("https://"):]
    elif s.startswith("http://"):
        s = s[len("http://"):]
    return s


def fetch_token(shop: str, client_id: str, client_secret: str) -> dict:
    url = f"https://{shop}/admin/oauth/access_token"
    body = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(
            f"Shopify rejected the token request ({exc.code}):\n{body_text}\n\n"
            f"Common causes:\n"
            f"  * The app is not installed on {shop} yet — install it via "
            f"the Dev Dashboard's Custom distribution link first.\n"
            f"  * Client ID or Secret is wrong / from a different app.\n"
            f"  * Shop URL doesn't match the app's allowed shops."
        )


def write_env(env_path: Path, shop: str, client_id: str, client_secret: str) -> None:
    """Update or append SHOPAI_SHOPIFY_* lines in ``env_path``."""
    keys = {
        "SHOPAI_SHOPIFY_URL": shop,
        "SHOPAI_SHOPIFY_CLIENT_ID": client_id,
        "SHOPAI_SHOPIFY_CLIENT_SECRET": client_secret,
    }
    lines: list[str] = []
    seen: set[str] = set()
    if env_path.exists():
        for raw in env_path.read_text().splitlines():
            stripped = raw.lstrip()
            if "=" not in stripped or stripped.startswith("#"):
                lines.append(raw)
                continue
            key = stripped.split("=", 1)[0].strip()
            if key in keys:
                lines.append(f"{key}={keys[key]}")
                seen.add(key)
            else:
                lines.append(raw)
    for key, value in keys.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--shop", required=True, help="my-store.myshopify.com")
    p.add_argument("--client-id", required=True, dest="client_id")
    p.add_argument("--client-secret", required=True, dest="client_secret")
    p.add_argument(
        "--env",
        default=".env",
        help="Path to .env to update (default: .env). Pass '' to skip.",
    )
    p.add_argument(
        "--show-token",
        action="store_true",
        help=(
            "W962-67: show the full token (default truncates to "
            "prefix). Use only on a trusted terminal."
        ),
    )
    args = p.parse_args(argv)

    shop = _normalize_shop(args.shop)
    data = fetch_token(shop, args.client_id, args.client_secret)
    token = data.get("access_token", "")
    if not token:
        # W962-67: print keys only, never the full response
        # dict. CI logs / shell history / screen-sharing
        # sessions become attack vectors if a token leaks.
        print(
            "No access_token in response. Keys: "
            f"{sorted(data.keys())}",
            file=sys.stderr,
        )
        return 1

    # W962-67: token display.
    # Default: show prefix only. Operator can opt into full
    # disclosure via --show-token (which still warns).
    show_full = getattr(args, "show_token", False)
    if show_full:
        token_display = token
        print(
            "WARNING: full token shown via --show-token. "
            "Clear your terminal history when done.",
            file=sys.stderr,
        )
    else:
        token_display = (
            token[:15] + "..."
            if len(token) > 15 else "<short>"
        )
    print()
    print(f"  shop:        {shop}")
    print(
        f"  token:       {token_display}"
        + ("" if show_full else "  (truncated; --show-token to reveal)")
    )
    print(f"  scope:       {data.get('scope', '')}")
    print(f"  expires_in:  {data.get('expires_in', 'unknown')} s")
    print()

    if args.env:
        write_env(Path(args.env), shop, args.client_id, args.client_secret)
        print(f"Wrote SHOPAI_SHOPIFY_URL/CLIENT_ID/CLIENT_SECRET to {args.env}.")
        print("ShopifyAdapter will refresh the access token on its own from now on.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
