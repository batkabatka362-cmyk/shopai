"""Shopify App — embedded Shopify app with OAuth, session management, App Bridge.

Implements Shopify OAuth 2.0 flow:
  1. Store owner clicks "Install" → redirect to Shopify authorize
  2. Shopify redirects back with code → exchange for access token
  3. Token stored → used for all API calls
  4. App renders embedded in Shopify Admin via App Bridge
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen

from utils.logger import get_logger

logger = get_logger("shopify.app")

# Config from env
APP_KEY = os.environ.get("SHOPAI_APP_KEY", "")
APP_SECRET = os.environ.get("SHOPAI_APP_SECRET", "")
APP_SCOPES = "read_products,write_products,read_orders,read_customers,read_inventory,write_inventory"
APP_REDIRECT = os.environ.get("SHOPAI_APP_REDIRECT", "http://localhost:3000/auth/callback")


class SessionStore:
    """Thread-safe store for shop sessions (token + shop info)."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def save(self, shop: str, token: str, scope: str = "") -> None:
        with self._lock:
            self._sessions[shop] = {"token": token, "scope": scope, "installed_at": time.time()}

    def get(self, shop: str) -> dict[str, Any] | None:
        with self._lock:
            return self._sessions.get(shop)

    def get_token(self, shop: str) -> str:
        session = self.get(shop)
        return session["token"] if session else ""

    def is_installed(self, shop: str) -> bool:
        return self.get(shop) is not None

    def list_shops(self) -> list[str]:
        with self._lock:
            return list(self._sessions.keys())


_sessions = SessionStore()


class ShopifyOAuth:
    """Handles Shopify OAuth 2.0 install flow."""

    @staticmethod
    def get_install_url(shop: str, nonce: str = "") -> str:
        """Generate Shopify OAuth authorize URL."""
        if not nonce:
            nonce = hashlib.sha256(f"{shop}{time.time()}".encode()).hexdigest()[:16]
        params = {
            "client_id": APP_KEY,
            "scope": APP_SCOPES,
            "redirect_uri": APP_REDIRECT,
            "state": nonce,
        }
        return f"https://{shop}/admin/oauth/authorize?{urlencode(params)}"

    @staticmethod
    def exchange_token(shop: str, code: str) -> dict[str, Any]:
        """Exchange authorization code for permanent access token."""
        url = f"https://{shop}/admin/oauth/access_token"
        payload = json.dumps({
            "client_id": APP_KEY,
            "client_secret": APP_SECRET,
            "code": code,
        }).encode()

        try:
            req = Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                token = data.get("access_token", "")
                scope = data.get("scope", "")
                _sessions.save(shop, token, scope)
                return {"success": True, "shop": shop, "scope": scope}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @staticmethod
    def verify_hmac(query_params: dict[str, str], secret: str = "") -> bool:
        """Verify Shopify request HMAC."""
        secret = secret or APP_SECRET
        if not secret:
            return True  # Skip in dev

        hmac_value = query_params.pop("hmac", "")
        sorted_params = "&".join(f"{k}={v}" for k, v in sorted(query_params.items()))
        computed = hmac.new(secret.encode(), sorted_params.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(computed, hmac_value)


# App Bridge HTML — renders inside Shopify Admin
APP_BRIDGE_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="shopify-api-key" content="{api_key}">
  <script src="https://cdn.shopify.com/shopifycloud/app-bridge.js"></script>
  <script src="https://cdn.shopify.com/shopifycloud/app-bridge-utils/app-bridge-utils.js"></script>
  <style>
    body {{ font-family: -apple-system, sans-serif; margin: 0; padding: 20px; background: #f6f6f7; }}
    .card {{ background: #fff; border-radius: 8px; padding: 20px; margin: 10px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
    h1 {{ font-size: 20px; margin: 0 0 16px; }}
    .metric {{ font-size: 32px; font-weight: 700; color: #202223; }}
    .label {{ font-size: 13px; color: #6d7175; margin-top: 4px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }}
    button {{ padding: 8px 16px; background: #008060; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }}
    button:hover {{ background: #006e52; }}
    #output {{ background: #1a1a2e; color: #e0e0e0; padding: 16px; border-radius: 8px; font-family: monospace; font-size: 12px; max-height: 400px; overflow-y: auto; white-space: pre-wrap; }}
  </style>
</head>
<body>
  <h1>ShopAI — AI Store Operator</h1>

  <div class="grid">
    <div class="card"><div class="metric" id="score">--</div><div class="label">Store Score</div></div>
    <div class="card"><div class="metric" id="engines">2498</div><div class="label">Engines</div></div>
    <div class="card"><div class="metric" id="actions">--</div><div class="label">Actions</div></div>
    <div class="card"><div class="metric" id="health">--</div><div class="label">Health</div></div>
  </div>

  <div class="card" style="margin-top: 16px;">
    <button onclick="runAutonomous()">🤖 Run Autonomous Cycle</button>
    <button onclick="quickCheck()">⚡ Quick Check</button>
    <button onclick="runPricing()">💰 Pricing Analysis</button>
    <button onclick="runSEO()">🔍 SEO Audit</button>
  </div>

  <div class="card" style="margin-top: 16px;">
    <div id="output">Ready. Click a button to run ShopAI intelligence.</div>
  </div>

  <script>
    const BASE = window.location.origin;

    async function runAutonomous() {{
      output('Running autonomous cycle...');
      const r = await fetch(BASE + '/app/api/autonomous');
      const d = await r.json();
      document.getElementById('score').textContent = d.store_score?.score || '--';
      document.getElementById('actions').textContent = d.results?.automation?.actions_generated || 0;
      document.getElementById('health').textContent = d.status || '--';
      output(JSON.stringify(d, null, 2));
    }}

    async function quickCheck() {{
      output('Quick check...');
      const r = await fetch(BASE + '/app/api/quick');
      const d = await r.json();
      document.getElementById('health').textContent = d.health || '--';
      output(JSON.stringify(d, null, 2));
    }}

    async function runPricing() {{
      output('Running pricing analysis...');
      const r = await fetch(BASE + '/app/api/pricing');
      output(JSON.stringify(await r.json(), null, 2));
    }}

    async function runSEO() {{
      output('Running SEO audit...');
      const r = await fetch(BASE + '/app/api/seo');
      output(JSON.stringify(await r.json(), null, 2));
    }}

    function output(text) {{ document.getElementById('output').textContent = text; }}
    quickCheck();
  </script>
</body>
</html>"""


class ShopifyAppHandler(BaseHTTPRequestHandler):
    """HTTP handler for Shopify embedded app."""

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        if path == "/auth/install":
            shop = params.get("shop", "")
            if not shop:
                self._json(400, {"error": "Missing shop parameter"})
                return
            url = ShopifyOAuth.get_install_url(shop)
            self._redirect(url)

        elif path == "/auth/callback":
            shop = params.get("shop", "")
            code = params.get("code", "")
            if not shop or not code:
                self._json(400, {"error": "Missing shop or code"})
                return
            result = ShopifyOAuth.exchange_token(shop, code)
            if result["success"]:
                self._redirect(f"https://{shop}/admin/apps/{APP_KEY}")
            else:
                self._json(500, result)

        elif path == "/app" or path == "":
            self._html(200, APP_BRIDGE_HTML.format(api_key=APP_KEY))

        elif path == "/app/api/autonomous":
            self._run_autonomous()

        elif path == "/app/api/quick":
            self._run_quick()

        elif path == "/app/api/pricing":
            self._run_pricing()

        elif path == "/app/api/seo":
            self._run_seo()

        elif path == "/app/api/status":
            self._json(200, {"shops": _sessions.list_shops(), "engines": 2498})

        else:
            self._json(404, {"error": "Not found"})

    def _run_autonomous(self):
        try:
            from core.autonomous import AutonomousOperator
            result = AutonomousOperator().operate()
            self._json(200, result)
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _run_quick(self):
        try:
            from core.autonomous import AutonomousOperator
            result = AutonomousOperator().quick_check()
            self._json(200, result)
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _run_pricing(self):
        try:
            from core.bridge.shopify_bridge import ShopifyBridge
            from core.orchestrator import MainOrchestrator
            orch = MainOrchestrator()
            orch.initialize()
            products = ShopifyBridge().fetch_products()
            result = orch.submit_task("pricing", {"products": products})
            orch.shutdown()
            self._json(200, result.get("result", {}))
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _run_seo(self):
        try:
            from core.bridge.shopify_bridge import ShopifyBridge
            from core.intelligence import SEOIntelligence
            products = ShopifyBridge().fetch_products()
            si = SEOIntelligence()
            audits = []
            for p in products[:5]:
                audit = si.audit_page({"title": p.get("name", ""), "keyword": p.get("category", "product")})
                audits.append({"product": p.get("name"), "score": audit["score"], "grade": audit["grade"], "issues": audit["issue_count"]})
            self._json(200, {"audits": audits, "avg_score": round(sum(a["score"] for a in audits) / max(len(audits), 1), 1)})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())

    def _html(self, status, html):
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def _redirect(self, url):
        self.send_response(302)
        self.send_header("Location", url)
        self.end_headers()

    def log_message(self, *args):
        pass


def start_app(port: int = 3000):
    """Start Shopify embedded app server."""
    print(f"ShopAI Shopify App: http://localhost:{port}/app")
    print(f"Install URL: http://localhost:{port}/auth/install?shop=YOUR-STORE.myshopify.com")
    server = HTTPServer(("0.0.0.0", port), ShopifyAppHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nApp stopped.")


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    start_app(port)
