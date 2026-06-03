"""One-shot helper: complete a Shopify Custom Distribution OAuth
install by exchanging the authorization code (or using
client_credentials) for an access token.

Usage::

    py scripts/finish_install.py \
        --shop my-store.myshopify.com \
        --client-id <CLIENT_ID> \
        --client-secret <CLIENT_SECRET> \
        [--code <OAUTH_CODE>]

If ``--code`` is supplied, tries the ``authorization_code`` grant
first. If omitted (or the code is already burned), falls back to
``client_credentials`` which works for any Custom Distribution app
once installed on the store.

Writes the resulting access token + credentials to ``.env`` with
the four ``SHOPAI_SHOPIFY_*`` keys + chmod 0o600. The token is
NEVER echoed in full -- only the 7-char prefix + length.

This script handles the LAST step of the OAuth install. Run it
once after clicking the install URL.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def _post(url: str, payload: dict) -> dict | None:
    body = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
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
        print(f"  -> HTTP {exc.code}: {body_text[:200]}")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--shop", required=True,
        help="my-store.myshopify.com",
    )
    parser.add_argument(
        "--client-id", required=True, dest="client_id",
    )
    parser.add_argument(
        "--client-secret", required=True, dest="client_secret",
    )
    parser.add_argument(
        "--code", default=None,
        help=(
            "OAuth authorization_code (optional). If omitted, "
            "uses client_credentials grant directly."
        ),
    )
    parser.add_argument(
        "--env-path", default=".env",
        help="Where to write credentials (default: .env)",
    )
    args = parser.parse_args()

    shop = args.shop.strip().rstrip("/")
    if shop.startswith("https://"):
        shop = shop[len("https://"):]
    elif shop.startswith("http://"):
        shop = shop[len("http://"):]

    url = f"https://{shop}/admin/oauth/access_token"

    token = ""

    if args.code:
        print("[1/2] Trying authorization_code grant...")
        data = _post(url, {
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "code": args.code,
        })
        token = (data or {}).get("access_token", "")

    if not token:
        print()
        print("[2/2] Trying client_credentials grant...")
        data = _post(url, {
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "grant_type": "client_credentials",
        })
        token = (data or {}).get("access_token", "")

    if not token:
        print()
        print("FAILED: no token from either grant.")
        print(
            "Most likely: install URL needs to be re-opened in "
            "browser to mint a fresh code, OR the app is not "
            "marked installed on the store."
        )
        return 1

    print()
    print(f"SUCCESS prefix={token[:7]}*** len={len(token)}")
    scope = (data or {}).get("scope", "")
    if scope:
        print(f"scopes granted: {len(scope.split(','))}")

    env_path = args.env_path
    lines: list[str] = []
    seen: set[str] = set()
    keys = {
        "SHOPAI_SHOPIFY_URL": shop,
        "SHOPAI_SHOPIFY_KEY": token,
        "SHOPAI_SHOPIFY_CLIENT_ID": args.client_id,
        "SHOPAI_SHOPIFY_CLIENT_SECRET": args.client_secret,
    }
    if os.path.exists(env_path):
        for raw in open(env_path, encoding="utf-8").read().splitlines():
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
    for k, v in keys.items():
        if k not in seen:
            lines.append(f"{k}={v}")

    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    try:
        os.chmod(env_path, 0o600)
    except OSError:
        pass
    print(f"wrote: {env_path}")
    print()
    print("Next: shopai store list")
    return 0


if __name__ == "__main__":
    sys.exit(main())
