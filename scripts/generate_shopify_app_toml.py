"""Generate shopify.app.toml from the canonical scope list.

Shopify CLI's ``shopify app deploy`` reads ``shopify.app.toml``
in the repo root and pushes the declared config (scopes,
redirect URLs, webhook subscriptions) to the Shopify Partners
Dashboard. Without this generator the toml drifts the moment
core.auth.shopify_scopes changes — exactly the problem we
hit between the legacy 18-scope audit and the post-wave-5
50-scope canonical list.

Usage:

    PYTHONPATH=. python scripts/generate_shopify_app_toml.py

Reads:
  * core.auth.shopify_scopes (required + recommended +
    optional plus-only)
  * SHOPAI_SHOPIFY_CLIENT_ID from env or .env (optional —
    generator writes a placeholder when absent so the toml
    is still committable)

Writes:
  * shopify.app.toml (overwrites)

Contract: the file always reflects ``core.auth.shopify_scopes``
exactly. A regression test in tests/test_shopify_app_toml.py
guards drift on every CI run.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys


_TEMPLATE = '''\
# shopify.app.toml — declarative Shopify app config.
#
# AUTO-GENERATED from core.auth.shopify_scopes. Do not edit by
# hand — re-run ``python scripts/generate_shopify_app_toml.py``
# instead. Drift is caught by tests/test_shopify_app_toml.py.

name = "ShopAI"
client_id = "{client_id}"
application_url = "{application_url}"
embedded = false

[access_scopes]
# Auto-granted on install. Failure to grant any of these
# breaks wave 1-5 features. {required_count} entries.
scopes = "{required_scopes}"

# Picker-list. Failure to grant degrades optional features
# but doesn't block install. {recommended_count} entries.
optional_scopes = [
{optional_scopes}
]

[auth]
redirect_urls = [
  "{redirect_url}"
]

[webhooks]
api_version = "2025-01"

[pos]
embedded = false

[build]
include_config_on_deploy = true
'''


def _load_dotenv(env_path: pathlib.Path) -> None:
    """Best-effort .env loader so this script works on
    PowerShell / cmd without a separate export step."""
    if not env_path.exists():
        return
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def render_toml(
    *,
    client_id: str,
    application_url: str,
    redirect_url: str,
) -> str:
    from core.auth.shopify_scopes import (
        recommended_scopes, required_scopes,
    )
    req = list(required_scopes())
    rec = list(recommended_scopes())
    optional_lines = ",\n".join(
        f'  "{s.handle}"' for s in rec
    )
    return _TEMPLATE.format(
        client_id=client_id or "<paste-from-partners-dashboard>",
        application_url=application_url,
        redirect_url=redirect_url,
        required_count=len(req),
        recommended_count=len(rec),
        required_scopes=",".join(s.handle for s in req),
        optional_scopes=optional_lines,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out",
        default="shopify.app.toml",
        help="output path (default: ./shopify.app.toml)",
    )
    ap.add_argument(
        "--application-url",
        default="http://localhost:9000",
        help="Shopify App URL (default localhost:9000)",
    )
    ap.add_argument(
        "--redirect-url",
        default="http://localhost:9000/callback",
        help="OAuth callback URL (default localhost:9000/callback)",
    )
    ap.add_argument(
        "--env",
        default=".env",
        help="env file to read SHOPAI_SHOPIFY_CLIENT_ID from",
    )
    args = ap.parse_args(argv)

    _load_dotenv(pathlib.Path(args.env))
    client_id = os.environ.get(
        "SHOPAI_SHOPIFY_CLIENT_ID", "",
    ).strip()

    out = pathlib.Path(args.out)
    body = render_toml(
        client_id=client_id,
        application_url=args.application_url,
        redirect_url=args.redirect_url,
    )
    out.write_text(body, encoding="utf-8")

    if client_id:
        print(
            f"✓ wrote {out} (client_id "
            f"{client_id[:8]}…{client_id[-4:]}, "
            f"{body.count(',') + 1} scope tokens)",
        )
    else:
        print(
            f"✓ wrote {out} (client_id is a placeholder — "
            "edit by hand or set SHOPAI_SHOPIFY_CLIENT_ID "
            "and re-run)",
            file=sys.stderr,
        )
    print()
    print("Next: deploy via Shopify CLI")
    print("  shopify app deploy --config=shopify.app.toml")
    print()
    print("Or trigger the OAuth install:")
    print("  python scripts/shopify_oauth_install.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
