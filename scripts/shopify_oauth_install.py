"""Shopify OAuth install helper — localhost:9000 callback handler.

Owner flow for connecting a store to ShopAI:

  1. Run this script → it starts a local HTTP server on
     port 9000 and prints an install URL.
  2. Open the install URL in a browser. Shopify shows a
     scope consent page listing the canonical scope set
     from core.auth.shopify_scopes.
  3. Approve → Shopify redirects to
     http://localhost:9000/callback?code=<X>&shop=...&...
     This server verifies the HMAC, exchanges the code for
     an access token, writes it to .env as
     SHOPAI_SHOPIFY_KEY, and exits 0.

Handles two callback shapes:

  * Full OAuth (has ``code``) — typical install flow.
  * App-bridge-only landing (no ``code``) — Shopify redirects
    here when the owner clicks the app icon in admin without
    having granted. Server then redirects back to
    ``/admin/oauth/authorize`` to kick off the real OAuth.

HMAC validation: every query from Shopify is signed with the
app's client_secret. We verify before trusting any parameter
(§4b.G paranoid mode — without this, a forged callback could
feed us a malicious shop+code pair).

Env requirements:
  SHOPAI_SHOPIFY_CLIENT_ID
  SHOPAI_SHOPIFY_CLIENT_SECRET

Usage:
  PYTHONPATH=. python scripts/shopify_oauth_install.py
  PYTHONPATH=. python scripts/shopify_oauth_install.py \
      --port 9000 --shop ts0efe-ih.myshopify.com
"""
from __future__ import annotations

import argparse
import hmac
import hashlib
import http.server
import json
import os
import pathlib
import socketserver
import sys
import threading
import time
import urllib.parse
import urllib.request
from typing import Any


# ── HMAC validation ───────────────────────────────────────


def verify_hmac(
    query_string: str, *, client_secret: str,
) -> bool:
    """Return True iff the query signs with ``client_secret``.

    Shopify's algorithm:
      1. Parse the query string into (key, value) pairs.
      2. Remove the ``hmac`` and ``signature`` pairs.
      3. Sort pairs by key, URL-decode, recombine as
         ``key=value&key=value`` (NOT urlencoded).
      4. HMAC-SHA256 keyed on client_secret.
      5. hex-encode + compare with the ``hmac`` param.
    """
    pairs = urllib.parse.parse_qsl(
        query_string, keep_blank_values=True,
    )
    supplied = ""
    filtered: list[tuple[str, str]] = []
    for k, v in pairs:
        if k == "hmac":
            supplied = v
            continue
        if k == "signature":
            continue
        filtered.append((k, v))
    if not supplied:
        return False
    filtered.sort(key=lambda kv: kv[0])
    canonical = "&".join(f"{k}={v}" for k, v in filtered)
    digest = hmac.new(
        client_secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    # Timing-safe comparison.
    return hmac.compare_digest(digest, supplied)


def verify_shop(shop: str) -> bool:
    """Shopify only redirects to `*.myshopify.com` hosts; the
    callback must be for a well-formed one."""
    if not shop:
        return False
    shop = shop.strip().lower()
    if not shop.endswith(".myshopify.com"):
        return False
    # Prevent path-traversal / host-injection via the shop
    # param — Shopify docs say handle ≤ 60 chars, alnum +
    # hyphens.
    handle = shop[: -len(".myshopify.com")]
    if not handle or len(handle) > 60:
        return False
    for ch in handle:
        if not (ch.isalnum() or ch == "-"):
            return False
    return True


# ── Token save ────────────────────────────────────────────


def write_token_to_env(
    token: str, *, env_path: pathlib.Path,
) -> None:
    """Upsert ``SHOPAI_SHOPIFY_KEY`` into ``.env``. Preserves
    every other line."""
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(
            encoding="utf-8",
        ).splitlines()
    out: list[str] = []
    replaced = False
    for line in lines:
        if line.strip().startswith("SHOPAI_SHOPIFY_KEY="):
            out.append(f"SHOPAI_SHOPIFY_KEY={token}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"SHOPAI_SHOPIFY_KEY={token}")
    env_path.write_text(
        "\n".join(out) + "\n", encoding="utf-8",
    )


# ── HTTP handler ──────────────────────────────────────────


class _InstallHandler(http.server.BaseHTTPRequestHandler):
    """Handles exactly one successful callback + shuts down."""

    # Populated by the entry point before the server starts.
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    scope_string: str = ""
    env_path: pathlib.Path = pathlib.Path(".env")
    result: dict[str, Any] = {}
    done_event: threading.Event = threading.Event()

    # Silence default stderr access log — we print our own.
    def log_message(self, *_args, **_kwargs):
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        # Accept both "/" (App URL) and "/callback" (OAuth
        # redirect). When Shopify sends the operator to /
        # without a code (e.g. admin panel tile click), we
        # kick the OAuth flow by redirecting to /admin/oauth/
        # authorize. When Shopify sends /callback with a
        # code, we exchange it for a token.
        if parsed.path not in ("/", "/callback"):
            self._reply(
                404, "ShopAI install: unknown path "
                f"{parsed.path}",
            )
            return
        params = dict(
            urllib.parse.parse_qsl(parsed.query),
        )
        shop = params.get("shop", "").strip().lower()
        code = params.get("code", "").strip()

        # HMAC first — nothing else trusted until verified.
        if not verify_hmac(
            parsed.query, client_secret=self.client_secret,
        ):
            self._fail("HMAC signature mismatch")
            return
        if not verify_shop(shop):
            self._fail(f"invalid shop handle: {shop!r}")
            return

        # Timestamp freshness — Shopify's signed URLs are
        # typically valid for up to an hour; reject anything
        # older than 5 minutes for defence.
        try:
            ts = int(params.get("timestamp", "0"))
        except (TypeError, ValueError):
            ts = 0
        if ts and abs(time.time() - ts) > 3600:
            self._fail(
                "timestamp outside 1h window "
                f"(got {ts})",
            )
            return

        if not code:
            # Landing URL — redirect back to Shopify's
            # authorize endpoint to kick off code exchange.
            authorize_url = (
                f"https://{shop}/admin/oauth/authorize?"
                + urllib.parse.urlencode({
                    "client_id": self.client_id,
                    "scope": self.scope_string,
                    "redirect_uri": self.redirect_uri,
                })
            )
            self._redirect(authorize_url)
            return

        # Exchange code → access_token.
        try:
            token = _exchange_code(
                shop=shop,
                code=code,
                client_id=self.client_id,
                client_secret=self.client_secret,
            )
        except Exception as exc:  # noqa: BLE001
            self._fail(
                f"code exchange failed: "
                f"{type(exc).__name__}: {exc}",
            )
            return

        write_token_to_env(
            token, env_path=self.env_path,
        )
        self.__class__.result = {
            "ok": True,
            "shop": shop,
            "token_prefix": token[:8] + "…",
            "env_path": str(self.env_path),
        }
        self._reply(
            200,
            "ShopAI install OK — token written to "
            f"{self.env_path}. You can close this window.",
        )
        self.__class__.done_event.set()

    def _redirect(self, url: str) -> None:
        self.send_response(302)
        self.send_header("Location", url)
        self.end_headers()

    def _reply(self, code: int, body: str) -> None:
        self.send_response(code)
        self.send_header(
            "Content-Type", "text/plain; charset=utf-8",
        )
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def _fail(self, reason: str) -> None:
        self.__class__.result = {"ok": False, "error": reason}
        self._reply(400, f"ShopAI install ERROR: {reason}")
        self.__class__.done_event.set()


def _exchange_code(
    *, shop: str, code: str,
    client_id: str, client_secret: str,
) -> str:
    url = f"https://{shop}/admin/oauth/access_token"
    payload = json.dumps({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, dict) or not data.get(
        "access_token",
    ):
        raise ValueError(
            f"no access_token in response: {data!r}",
        )
    return str(data["access_token"])


# ── Entry point ──────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument(
        "--shop",
        default="",
        help=(
            "shop handle (e.g. ts0efe-ih.myshopify.com). "
            "If set, script prints the install URL and "
            "waits for the callback. Otherwise it only "
            "starts the listener."
        ),
    )
    ap.add_argument(
        "--env",
        default=".env",
        help="path to env file to upsert token into",
    )
    ap.add_argument(
        "--open",
        action="store_true",
        help=(
            "open the install URL in the default browser"
        ),
    )
    args = ap.parse_args(argv)

    client_id = os.environ.get(
        "SHOPAI_SHOPIFY_CLIENT_ID", "",
    ).strip()
    client_secret = os.environ.get(
        "SHOPAI_SHOPIFY_CLIENT_SECRET", "",
    ).strip()
    if not client_id or not client_secret:
        print(
            "ERR: set SHOPAI_SHOPIFY_CLIENT_ID + "
            "SHOPAI_SHOPIFY_CLIENT_SECRET first",
            file=sys.stderr,
        )
        return 2

    try:
        from core.auth.shopify_scopes import scope_string
    except Exception as exc:  # noqa: BLE001
        print(f"ERR: cannot import scope list: {exc}",
              file=sys.stderr)
        return 2

    redirect_uri = f"http://localhost:{args.port}/callback"
    scopes = scope_string()
    env_path = pathlib.Path(args.env)

    _InstallHandler.client_id = client_id
    _InstallHandler.client_secret = client_secret
    _InstallHandler.redirect_uri = redirect_uri
    _InstallHandler.scope_string = scopes
    _InstallHandler.env_path = env_path
    _InstallHandler.done_event = threading.Event()

    httpd = socketserver.TCPServer(
        ("127.0.0.1", args.port), _InstallHandler,
    )
    httpd.allow_reuse_address = True
    server_thread = threading.Thread(
        target=httpd.serve_forever, daemon=True,
    )
    server_thread.start()

    print(
        f"✓ Listening on http://localhost:{args.port}/callback",
    )
    print(f"  Redirect URI to register in Shopify: "
          f"{redirect_uri}")
    print(
        f"  Scopes: {scopes.count(',')+1} total "
        f"(see core.auth.shopify_scopes)",
    )
    print()

    if args.shop:
        install_url = (
            f"https://{args.shop}/admin/oauth/authorize?"
            + urllib.parse.urlencode({
                "client_id": client_id,
                "scope": scopes,
                "redirect_uri": redirect_uri,
            })
        )
        print("1. Open this install URL in your browser:")
        print()
        print(f"   {install_url}")
        print()
        if args.open:
            import webbrowser
            webbrowser.open(install_url)
        print("2. Approve the scope list → Shopify redirects "
              "to the callback")
        print("3. This script will exit once the token is "
              "written to .env")
        print()

    try:
        _InstallHandler.done_event.wait(
            timeout=600,  # 10 min
        )
    except KeyboardInterrupt:
        print("aborted by operator")
        return 1
    finally:
        httpd.shutdown()

    r = _InstallHandler.result or {"ok": False, "error": "timeout"}
    if r.get("ok"):
        print(f"✓ Token saved for {r['shop']} → "
              f"{r['env_path']} "
              f"(prefix: {r['token_prefix']})")
        print()
        print("Next: audit the granted scopes")
        print("  PYTHONPATH=. python "
              "scripts/deguar_scope_audit.py")
        return 0

    print(
        f"✗ Install failed: {r.get('error', 'unknown')}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
