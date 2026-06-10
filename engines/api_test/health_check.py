"""Per-adapter health probes -- make one real minimal API
call against each adapter's live endpoint and report the
result.

Each probe returns a HealthCheckResult with:

  * adapter (alias)
  * configured: True iff env-var set
  * reachable: True iff vendor responded at all
  * authenticated: True iff creds accepted
  * latency_ms
  * detail: free-text confirmation when ok
  * error: free-text reason when not ok

Probes are intentionally MINIMAL -- 1-token chat / list 1
voice / search 1 stock video. Total cost across the 4
configured-by-the-operator adapters is < $0.01.

Each probe is INDEPENDENT -- if one raises, the others
still run. The aggregator returns every result.
"""
from __future__ import annotations

import json as _json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


def _extract_error_message(text: str) -> str:
    """Try to pull the operator-actionable message out of a
    vendor JSON error body.

    Vendors return errors in nested shapes:
      OpenAI:  {"error": {"message": "...", "type": "..."}}
      Brevo:   {"code": "...", "message": "..."}
      Klaviyo: {"errors": [{"detail": "..."}]}
      Pexels:  {"error": "..."} or plain text
      Meta:    {"error": {"message": "...", "code": N}}

    Returns the deepest free-text message it finds, or the
    raw text if nothing matches. Always strips JSON noise
    so the operator sees the actionable content first.

    Handles TRUNCATED JSON bodies (which happen when the
    upstream HTTP handler clips the body before it reaches
    us): falls back to a regex scan for "message": "...".
    """
    if not text:
        return ""
    # Try to parse as JSON first -- handles every vendor's
    # nested shape uniformly.
    try:
        parsed = _json.loads(text)
    except (_json.JSONDecodeError, ValueError):
        # Truncated JSON or plain text. Try two regex
        # fallbacks before giving up:
        # 1. "message": "..."  -- closed quote form
        # 2. "message": "...   -- truncated form (no closing
        #    quote because upstream snippeted the body
        #    before it reached us)
        for key in ("message", "detail", "title"):
            m = re.search(
                rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"',
                text,
            )
            if m:
                raw = m.group(1)
                return raw.replace("\\n", " ").replace(
                    '\\"', '"',
                ).replace("\\\\", "\\").strip()
            # Truncated form -- take everything up to end
            # of text after the opening quote.
            m = re.search(
                rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)$',
                text,
            )
            if m:
                raw = m.group(1)
                return raw.replace("\\n", " ").replace(
                    '\\"', '"',
                ).replace("\\\\", "\\").strip()
        return text.strip()

    # Walk known nested shapes
    if isinstance(parsed, dict):
        # OpenAI / Meta: {"error": {"message": "..."}}
        err = parsed.get("error")
        if isinstance(err, dict):
            msg = err.get("message") or err.get("detail")
            if msg:
                return str(msg)
            return _json.dumps(err)[:300]
        if isinstance(err, str):
            return err
        # Brevo: {"code": "...", "message": "..."}
        if parsed.get("message"):
            return str(parsed["message"])
        # Klaviyo: {"errors": [{"detail": "..."}]}
        errs = parsed.get("errors")
        if isinstance(errs, list) and errs:
            first = errs[0]
            if isinstance(first, dict):
                msg = (
                    first.get("detail")
                    or first.get("message")
                    or first.get("title")
                )
                if msg:
                    return str(msg)
        # Fallback: dump first 300 chars
        return _json.dumps(parsed)[:300]
    return str(parsed)[:300]


def _short_http_error(
    status_code: int, body: str,
) -> str:
    """Build a concise HTTP error message: 'HTTP 401: <message>'.

    Used by every probe to keep error reporting uniform.
    """
    msg = _extract_error_message(body)
    return f"HTTP {status_code}: {msg[:240]}"


@dataclass
class HealthCheckResult:
    """Per-adapter probe result."""
    adapter: str
    configured: bool = False
    reachable: bool = False
    authenticated: bool = False
    latency_ms: float = 0.0
    detail: str = ""
    error: str = ""

    @property
    def cls(self) -> str:
        """ok / fail / skipped"""
        if not self.configured:
            return "skipped"
        if self.authenticated:
            return "ok"
        return "fail"


# ── Per-adapter probes ────────────────────────────────────


def _check_openai() -> HealthCheckResult:
    """Send a 1-token chat completion to OpenAI."""
    out = HealthCheckResult(adapter="openai")
    try:
        from core.adapters.config import get_config
        from core.adapters.llm.openai import OpenAIAdapter
        cfg = get_config()
        if not cfg.has("openai"):
            return out
        out.configured = True

        adapter = OpenAIAdapter()
        from core.adapters.base import Capability
        start = time.monotonic()
        result = adapter._chat(
            Capability.CHAT_COMPLETE,
            {
                "prompt": "ping",
                "max_tokens": 5,
                "temperature": 0.0,
            },
        )
        out.latency_ms = round(
            (time.monotonic() - start) * 1000.0, 1,
        )
        out.reachable = True
        out.authenticated = bool(result.ok)
        if result.ok:
            data = result.data or {}
            out.detail = (
                f"model={data.get('model', '?')} "
                f"tokens_out={result.tokens_out}"
            )
        else:
            out.error = str(result.error or "")[:200]
    except Exception as exc:  # noqa: BLE001
        # Adapter errors often carry the vendor JSON body
        # in the message. The extractor's regex fallback
        # handles truncated/embedded JSON.
        raw = str(exc)
        parsed_msg = _extract_error_message(raw)
        out.error = (
            f"{type(exc).__name__}: {parsed_msg}"[:300]
        )
        if "auth" in raw.lower() or "401" in raw:
            out.reachable = True
    return out


def _check_anthropic() -> HealthCheckResult:
    """Send a 1-token Messages call to Anthropic."""
    out = HealthCheckResult(adapter="anthropic")
    try:
        from core.adapters.config import get_config
        from core.adapters.llm.anthropic import (
            AnthropicAdapter,
        )
        cfg = get_config()
        if not cfg.has("anthropic"):
            return out
        out.configured = True

        adapter = AnthropicAdapter()
        from core.adapters.base import Capability
        start = time.monotonic()
        result = adapter._chat(
            Capability.CHAT_COMPLETE,
            {
                "prompt": "ping",
                "max_tokens": 5,
                "temperature": 0.0,
            },
        )
        out.latency_ms = round(
            (time.monotonic() - start) * 1000.0, 1,
        )
        out.reachable = True
        out.authenticated = bool(result.ok)
        if result.ok:
            data = result.data or {}
            out.detail = (
                f"model={data.get('model', '?')} "
                f"tokens_out={result.tokens_out}"
            )
        else:
            out.error = str(result.error or "")[:200]
    except Exception as exc:  # noqa: BLE001
        # Adapter errors often carry the vendor JSON body
        # in the message. The extractor's regex fallback
        # handles truncated/embedded JSON.
        raw = str(exc)
        parsed_msg = _extract_error_message(raw)
        out.error = (
            f"{type(exc).__name__}: {parsed_msg}"[:300]
        )
        if "auth" in raw.lower() or "401" in raw:
            out.reachable = True
    return out


def _check_brevo() -> HealthCheckResult:
    """GET /v3/account to verify Brevo creds."""
    out = HealthCheckResult(adapter="brevo")
    try:
        from core.adapters.config import get_config
        cfg = get_config()
        if not cfg.has("brevo"):
            return out
        out.configured = True

        import requests  # type: ignore[import-not-found]
        key = cfg.get("brevo")
        start = time.monotonic()
        resp = requests.get(
            "https://api.brevo.com/v3/account",
            headers={
                "api-key": key,
                "Accept": "application/json",
            },
            timeout=15.0,
        )
        out.latency_ms = round(
            (time.monotonic() - start) * 1000.0, 1,
        )
        out.reachable = True
        if resp.status_code == 200:
            out.authenticated = True
            try:
                body = resp.json()
                email = body.get("email", "")
                plan = body.get("plan", [{}])
                if isinstance(plan, list) and plan:
                    plan_type = plan[0].get("type", "")
                else:
                    plan_type = ""
                out.detail = (
                    f"email={email} plan={plan_type}"
                )
            except Exception:  # noqa: BLE001
                out.detail = "account verified"
        else:
            out.error = _short_http_error(
                resp.status_code, resp.text,
            )
    except Exception as exc:  # noqa: BLE001
        out.error = f"{type(exc).__name__}: {exc}"[:200]
    return out


def _check_pexels() -> HealthCheckResult:
    """Search 1 stock video to verify Pexels creds."""
    out = HealthCheckResult(adapter="pexels")
    try:
        from core.adapters.config import get_config
        cfg = get_config()
        if not cfg.has("pexels"):
            return out
        out.configured = True

        import requests  # type: ignore[import-not-found]
        key = cfg.get("pexels")
        start = time.monotonic()
        resp = requests.get(
            "https://api.pexels.com/videos/search",
            headers={
                "Authorization": key,
                "Accept": "application/json",
            },
            params={"query": "test", "per_page": 1},
            timeout=15.0,
        )
        out.latency_ms = round(
            (time.monotonic() - start) * 1000.0, 1,
        )
        out.reachable = True
        if resp.status_code == 200:
            out.authenticated = True
            try:
                body = resp.json()
                total = body.get("total_results", 0)
                out.detail = f"videos_total={total}"
            except Exception:  # noqa: BLE001
                out.detail = "search ok"
        else:
            out.error = _short_http_error(
                resp.status_code, resp.text,
            )
    except Exception as exc:  # noqa: BLE001
        out.error = f"{type(exc).__name__}: {exc}"[:200]
    return out


def _check_elevenlabs() -> HealthCheckResult:
    """GET /v1/voices to verify ElevenLabs creds + scopes."""
    out = HealthCheckResult(adapter="elevenlabs")
    try:
        from core.adapters.config import get_config
        cfg = get_config()
        if not cfg.has("elevenlabs"):
            return out
        out.configured = True

        import requests  # type: ignore[import-not-found]
        key = cfg.get("elevenlabs")
        start = time.monotonic()
        resp = requests.get(
            "https://api.elevenlabs.io/v1/voices",
            headers={
                "xi-api-key": key,
                "Accept": "application/json",
            },
            timeout=15.0,
        )
        out.latency_ms = round(
            (time.monotonic() - start) * 1000.0, 1,
        )
        out.reachable = True
        if resp.status_code == 200:
            out.authenticated = True
            try:
                body = resp.json()
                voices = body.get("voices") or []
                out.detail = f"voices={len(voices)}"
            except Exception:  # noqa: BLE001
                out.detail = "voices list ok"
        else:
            out.error = _short_http_error(
                resp.status_code, resp.text,
            )
    except Exception as exc:  # noqa: BLE001
        out.error = f"{type(exc).__name__}: {exc}"[:200]
    return out


def _check_klaviyo() -> HealthCheckResult:
    """GET /accounts to verify Klaviyo creds."""
    out = HealthCheckResult(adapter="klaviyo")
    try:
        from core.adapters.config import get_config
        cfg = get_config()
        if not cfg.has("klaviyo"):
            return out
        out.configured = True

        import requests  # type: ignore[import-not-found]
        key = cfg.get("klaviyo")
        start = time.monotonic()
        resp = requests.get(
            "https://a.klaviyo.com/api/accounts",
            headers={
                "Authorization": f"Klaviyo-API-Key {key}",
                "Accept": "application/json",
                "revision": "2024-10-15",
            },
            timeout=15.0,
        )
        out.latency_ms = round(
            (time.monotonic() - start) * 1000.0, 1,
        )
        out.reachable = True
        if resp.status_code == 200:
            out.authenticated = True
            try:
                body = resp.json()
                data = body.get("data") or []
                out.detail = (
                    f"accounts={len(data)}"
                )
            except Exception:  # noqa: BLE001
                out.detail = "accounts list ok"
        else:
            out.error = _short_http_error(
                resp.status_code, resp.text,
            )
    except Exception as exc:  # noqa: BLE001
        out.error = f"{type(exc).__name__}: {exc}"[:200]
    return out


def _check_meta_ads() -> HealthCheckResult:
    """GET /me to verify Meta Ads access token."""
    out = HealthCheckResult(adapter="meta_ads")
    try:
        from core.adapters.config import get_config
        cfg = get_config()
        if not cfg.has("meta_ads_access_token"):
            return out
        out.configured = True

        import requests  # type: ignore[import-not-found]
        key = cfg.get("meta_ads_access_token")
        start = time.monotonic()
        resp = requests.get(
            "https://graph.facebook.com/v21.0/me",
            params={"access_token": key},
            timeout=15.0,
        )
        out.latency_ms = round(
            (time.monotonic() - start) * 1000.0, 1,
        )
        out.reachable = True
        if resp.status_code == 200:
            out.authenticated = True
            try:
                body = resp.json()
                name = body.get("name", "")
                user_id = body.get("id", "")
                out.detail = (
                    f"user={name} id={user_id}"
                )
            except Exception:  # noqa: BLE001
                out.detail = "auth ok"
        else:
            out.error = _short_http_error(
                resp.status_code, resp.text,
            )
    except Exception as exc:  # noqa: BLE001
        out.error = f"{type(exc).__name__}: {exc}"[:200]
    return out


def _check_autods() -> HealthCheckResult:
    """AutoDS skeleton: only verifies env-var presence,
    cannot make a real API call until endpoint URLs are
    wired."""
    out = HealthCheckResult(adapter="autods")
    try:
        from core.adapters.config import get_config
        cfg = get_config()
        if not cfg.has("autods"):
            return out
        out.configured = True
        # Skeleton: no real endpoint wired yet. Report
        # configured + reachable=False + clear error so
        # operator knows the gate.
        out.reachable = False
        out.error = (
            "skeleton: endpoint URLs not yet wired -- "
            "see core/adapters/sourcing/autods.py "
            "(W963-102)"
        )
    except Exception as exc:  # noqa: BLE001
        out.error = f"{type(exc).__name__}: {exc}"[:200]
    return out


def _check_shopify() -> HealthCheckResult:
    """GET /shop.json to verify Shopify Admin API."""
    out = HealthCheckResult(adapter="shopify")
    try:
        from core.adapters.config import get_config
        cfg = get_config()
        url = cfg.get("shopify_url")
        key = cfg.get("shopify_key")
        if not (url and key):
            return out
        out.configured = True

        # Normalise: accept "shop.myshopify.com" or
        # "https://shop.myshopify.com"
        host = url.replace("https://", "").replace(
            "http://", "",
        ).strip("/")
        endpoint = (
            f"https://{host}/admin/api/2024-10/shop.json"
        )

        import requests  # type: ignore[import-not-found]
        start = time.monotonic()
        resp = requests.get(
            endpoint,
            headers={
                "X-Shopify-Access-Token": key,
                "Accept": "application/json",
            },
            timeout=15.0,
        )
        out.latency_ms = round(
            (time.monotonic() - start) * 1000.0, 1,
        )
        out.reachable = True
        if resp.status_code == 200:
            out.authenticated = True
            try:
                body = resp.json()
                shop = body.get("shop") or {}
                out.detail = (
                    f"shop={shop.get('name', '?')} "
                    f"currency={shop.get('currency', '?')}"
                )
            except Exception:  # noqa: BLE001
                out.detail = "shop.json ok"
        else:
            out.error = _short_http_error(
                resp.status_code, resp.text,
            )
    except Exception as exc:  # noqa: BLE001
        out.error = f"{type(exc).__name__}: {exc}"[:200]
    return out


# ── Registry ──────────────────────────────────────────────


# Probes ordered by importance. Operator scanning output
# sees the critical ones first.
PROBES = [
    ("shopify", _check_shopify),
    ("openai", _check_openai),
    ("anthropic", _check_anthropic),
    ("brevo", _check_brevo),
    ("klaviyo", _check_klaviyo),
    ("meta_ads", _check_meta_ads),
    ("pexels", _check_pexels),
    ("elevenlabs", _check_elevenlabs),
    ("autods", _check_autods),
]


# ── Aggregator ────────────────────────────────────────────


@dataclass
class ApiTestReport:
    results: list[HealthCheckResult] = field(
        default_factory=list,
    )
    headline: str = ""
    next_action: str = ""

    @property
    def ok_count(self) -> int:
        return sum(
            1 for r in self.results if r.cls == "ok"
        )

    @property
    def fail_count(self) -> int:
        return sum(
            1 for r in self.results if r.cls == "fail"
        )

    @property
    def skipped_count(self) -> int:
        return sum(
            1 for r in self.results
            if r.cls == "skipped"
        )

    @property
    def configured_count(self) -> int:
        return sum(
            1 for r in self.results if r.configured
        )

    @property
    def all_configured_ok(self) -> bool:
        return self.fail_count == 0 and (
            self.configured_count > 0
        )


def run_api_test(
    *,
    only_alias: str = "",
) -> ApiTestReport:
    """Run every probe in PROBES order. If only_alias is
    supplied, run JUST that probe (skip the rest)."""
    report = ApiTestReport()
    for alias, probe in PROBES:
        if only_alias and only_alias != alias:
            continue
        try:
            result = probe()
        except Exception as exc:  # noqa: BLE001
            # Defensive: each probe is wrapped in its own
            # try/except internally; this is for the
            # impossible case where the probe constructor
            # raises before its inner handler engages.
            logger.debug(
                "probe %s raised: %s", alias, exc,
            )
            result = HealthCheckResult(
                adapter=alias,
                error=(
                    f"probe crashed: "
                    f"{type(exc).__name__}: {exc}"
                )[:200],
            )
        report.results.append(result)

    cfg_count = report.configured_count
    ok_count = report.ok_count
    fail_count = report.fail_count
    skip_count = report.skipped_count

    if cfg_count == 0:
        report.headline = (
            "No adapters configured -- nothing to test"
        )
        report.next_action = (
            "shopai api-status --missing-only  "
            "(set keys then re-run)"
        )
    elif fail_count == 0:
        report.headline = (
            f"All {ok_count}/{cfg_count} configured "
            "adapters live + authenticated"
        )
        report.next_action = (
            "shopai earn-readiness  (then cycle run --yes)"
        )
    else:
        failing = [
            r.adapter for r in report.results
            if r.cls == "fail"
        ]
        report.headline = (
            f"{fail_count}/{cfg_count} configured "
            f"adapter(s) failed -- "
            f"{', '.join(failing[:3])}"
        )
        # First failing adapter's error guides the
        # operator's next step
        for r in report.results:
            if r.cls == "fail":
                report.next_action = (
                    f"Fix {r.adapter}: {r.error[:120]}"
                )
                break
    return report
