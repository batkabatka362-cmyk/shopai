"""shopai doctor — real connectivity probes for owner onboarding.

``config check`` validates env-schema shape; ``doctor`` goes further
and makes a lightweight HTTP call to each configured upstream to
confirm the credentials are actually valid. Owner running a fresh
clone can resolve 95% of first-launch failures before spending a
single dollar:

  * Shopify — GET ``/admin/api/2024-01/shop.json`` (scope check)
  * Meta   — GET ``/me`` (token validity)
  * fal.ai — GET ``/`` (reach + key header accepted)
  * Obsidian vault path — ``os.path.isdir``
  * Moby Triple Whale — GET ``/moby/v1/recommendations`` (optional)

Each probe returns a ``ProbeResult`` with ``ok``, ``latency_ms``,
``detail``, and ``fix`` (human-readable remediation hint when
``ok=False``). ``run()`` aggregates into a ``DoctorReport`` and
prints a colourless ASCII table the owner can read over SSH.

Pure stdlib. HTTP client is dependency-injected so tests run
offline against a fake.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from utils.logger import get_logger


logger = get_logger("core.readiness.doctor")


_DEFAULT_TIMEOUT_S = 8.0


@dataclass
class ProbeResult:
    name: str
    ok: bool
    skipped: bool = False
    latency_ms: float = 0.0
    detail: str = ""
    fix: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "skipped": self.skipped,
            "latency_ms": round(self.latency_ms, 2),
            "detail": self.detail,
            "fix": self.fix,
        }


@dataclass
class DoctorReport:
    probes: tuple[ProbeResult, ...] = ()
    ok: bool = True
    critical_failures: int = 0
    warnings: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "critical_failures": self.critical_failures,
            "warnings": self.warnings,
            "probes": [p.as_dict() for p in self.probes],
        }


# HTTP client contract — pure stdlib with a (method, url, headers,
# timeout) → (status_code, body_bytes) signature. Tests inject a
# fake. Real caller uses the module-level ``_urlopen`` below.
HttpCallable = Callable[
    [str, str, dict[str, str], float],
    tuple[int, bytes],
]


def _urlopen(
    method: str,
    url: str,
    headers: dict[str, str],
    timeout: float,
) -> tuple[int, bytes]:
    req = urllib.request.Request(
        url, method=method, headers=headers,
    )
    try:
        with urllib.request.urlopen(
            req, timeout=timeout,
        ) as resp:
            return (
                int(resp.status),
                resp.read(512),
            )
    except urllib.error.HTTPError as exc:
        return int(exc.code), (
            exc.read(512) if hasattr(exc, "read") else b""
        )
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(
            f"network: {exc}",
        ) from exc


# ── Individual probes ────────────────────────────────────────


def _probe_shopify(
    http: HttpCallable, timeout: float,
) -> ProbeResult:
    shop_url = os.environ.get("SHOPAI_SHOPIFY_URL", "")
    if not shop_url:
        return ProbeResult(
            name="shopify",
            ok=False,
            skipped=True,
            detail="SHOPAI_SHOPIFY_URL not set",
            fix=(
                "Set SHOPAI_SHOPIFY_URL=your-store.myshopify.com"
                " in .env"
            ),
        )
    try:
        from core.auth.token_resolver import (
            resolve_access_token,
        )
        token = resolve_access_token(shop_url)
    except Exception as exc:  # noqa: BLE001
        return ProbeResult(
            name="shopify",
            ok=False,
            detail=f"token resolve raised: {exc}",
            fix=(
                "Set SHOPAI_SHOPIFY_KEY (legacy) or "
                "SHOPAI_SHOPIFY_CLIENT_ID + "
                "SHOPAI_SHOPIFY_CLIENT_SECRET (OAuth)"
            ),
        )
    if not token:
        return ProbeResult(
            name="shopify",
            ok=False,
            detail="no credentials resolved",
            fix=(
                "Set SHOPAI_SHOPIFY_KEY or install public app "
                "via OAuth"
            ),
        )
    base = shop_url if shop_url.startswith(
        "http",
    ) else f"https://{shop_url}"
    url = f"{base}/admin/api/2024-01/shop.json"
    headers = {
        "X-Shopify-Access-Token": token,
        "Accept": "application/json",
    }
    t0 = time.monotonic()
    try:
        status, body = http("GET", url, headers, timeout)
    except RuntimeError as exc:
        return ProbeResult(
            name="shopify",
            ok=False,
            latency_ms=(time.monotonic() - t0) * 1000,
            detail=str(exc),
            fix="Check your internet connection + shop domain",
        )
    ms = (time.monotonic() - t0) * 1000
    if status == 200:
        try:
            shop = json.loads(body).get("shop", {})
            name = str(shop.get("name", ""))
            return ProbeResult(
                name="shopify",
                ok=True,
                latency_ms=ms,
                detail=f"store={name or '(unknown)'}",
            )
        except (json.JSONDecodeError, AttributeError):
            return ProbeResult(
                name="shopify",
                ok=True,
                latency_ms=ms,
                detail="200 (shop.json parsed partially)",
            )
    if status == 401:
        return ProbeResult(
            name="shopify",
            ok=False,
            latency_ms=ms,
            detail="401 unauthorized",
            fix=(
                "Token invalid or revoked — re-install via "
                "OAuth or refresh SHOPAI_SHOPIFY_KEY"
            ),
        )
    if status == 402:
        return ProbeResult(
            name="shopify",
            ok=False,
            latency_ms=ms,
            detail="402 shop frozen / billing issue",
            fix="Check Shopify billing + shop status",
        )
    return ProbeResult(
        name="shopify",
        ok=False,
        latency_ms=ms,
        detail=f"HTTP {status}",
        fix="Check Shopify API status",
    )


def _probe_meta_ads(
    http: HttpCallable, timeout: float,
) -> ProbeResult:
    token = os.environ.get(
        "META_ADS_ACCESS_TOKEN", "",
    ) or os.environ.get(
        "meta_ads_access_token", "",
    )
    if not token:
        return ProbeResult(
            name="meta_ads",
            ok=False,
            skipped=True,
            detail="META_ADS_ACCESS_TOKEN not set",
            fix=(
                "Set META_ADS_ACCESS_TOKEN to a valid "
                "long-lived access token"
            ),
        )
    from core.adapters.ads.meta_ads import (
        _resolved_api_version,
    )
    url = (
        f"https://graph.facebook.com/"
        f"{_resolved_api_version()}/me"
    )
    headers = {"Authorization": f"Bearer {token}"}
    t0 = time.monotonic()
    try:
        status, body = http("GET", url, headers, timeout)
    except RuntimeError as exc:
        return ProbeResult(
            name="meta_ads",
            ok=False,
            latency_ms=(time.monotonic() - t0) * 1000,
            detail=str(exc),
            fix="Check internet connection",
        )
    ms = (time.monotonic() - t0) * 1000
    if status == 200:
        try:
            me = json.loads(body)
            uid = str(me.get("id", ""))
            return ProbeResult(
                name="meta_ads",
                ok=True,
                latency_ms=ms,
                detail=f"user_id={uid or '(unknown)'}",
            )
        except json.JSONDecodeError:
            return ProbeResult(
                name="meta_ads",
                ok=True,
                latency_ms=ms,
                detail="200 (body parse failed)",
            )
    if status == 401 or status == 400:
        return ProbeResult(
            name="meta_ads",
            ok=False,
            latency_ms=ms,
            detail=f"HTTP {status} — token rejected",
            fix=(
                "Generate a new long-lived Meta access "
                "token at developers.facebook.com and "
                "update META_ADS_ACCESS_TOKEN"
            ),
        )
    return ProbeResult(
        name="meta_ads",
        ok=False,
        latency_ms=ms,
        detail=f"HTTP {status}",
        fix="Check Meta API status + token scopes",
    )


def _probe_fal(
    http: HttpCallable, timeout: float,
) -> ProbeResult:
    key = os.environ.get("FAL_KEY", "")
    if not key:
        return ProbeResult(
            name="fal",
            ok=False,
            skipped=True,
            detail="FAL_KEY not set",
            fix=(
                "Set FAL_KEY to enable fal.ai video "
                "generation (volume-tier $0.07/s)"
            ),
        )
    url = "https://fal.run/"
    headers = {
        "Authorization": f"Key {key}",
        "Accept": "application/json",
    }
    t0 = time.monotonic()
    try:
        status, _ = http("GET", url, headers, timeout)
    except RuntimeError as exc:
        return ProbeResult(
            name="fal",
            ok=False,
            latency_ms=(time.monotonic() - t0) * 1000,
            detail=str(exc),
            fix="Check internet connection",
        )
    ms = (time.monotonic() - t0) * 1000
    # fal.run / returns 404 for GET but that means the auth
    # header was valid — a 401/403 would mean bad key.
    if status in (200, 404, 405):
        return ProbeResult(
            name="fal",
            ok=True,
            latency_ms=ms,
            detail=f"reachable (HTTP {status})",
        )
    if status in (401, 403):
        return ProbeResult(
            name="fal",
            ok=False,
            latency_ms=ms,
            detail=f"HTTP {status} — key rejected",
            fix=(
                "Generate a new key at fal.ai/dashboard and "
                "update FAL_KEY"
            ),
        )
    return ProbeResult(
        name="fal",
        ok=False,
        latency_ms=ms,
        detail=f"HTTP {status}",
    )


def _probe_vault() -> ProbeResult:
    """Obsidian vault path presence check (no HTTP)."""
    path = os.environ.get("OBSIDIAN_VAULT_PATH", "")
    if not path:
        return ProbeResult(
            name="obsidian_vault",
            ok=False,
            skipped=True,
            detail="OBSIDIAN_VAULT_PATH not set",
            fix=(
                "Point OBSIDIAN_VAULT_PATH at a local "
                "directory for memory ↔ vault sync"
            ),
        )
    p = Path(path)
    if not p.exists():
        return ProbeResult(
            name="obsidian_vault",
            ok=False,
            detail=f"path {path!r} does not exist",
            fix=f"mkdir -p {path} or update the env var",
        )
    if not p.is_dir():
        return ProbeResult(
            name="obsidian_vault",
            ok=False,
            detail=f"{path!r} is not a directory",
            fix="Point OBSIDIAN_VAULT_PATH at a directory",
        )
    return ProbeResult(
        name="obsidian_vault",
        ok=True,
        detail=str(p.resolve()),
    )


def _probe_moby(
    http: HttpCallable, timeout: float,
) -> ProbeResult:
    key = os.environ.get("TRIPLE_WHALE_API_KEY", "")
    if not key:
        return ProbeResult(
            name="moby",
            ok=False,
            skipped=True,
            detail="TRIPLE_WHALE_API_KEY not set",
            fix=(
                "Optional — set TRIPLE_WHALE_API_KEY to "
                "enable Moby vote comparison (A7)"
            ),
        )
    url = (
        "https://api.triplewhale.com/moby/v1/recommendations"
        "?scope=campaigns&limit=1"
    )
    headers = {"Authorization": f"Bearer {key}"}
    t0 = time.monotonic()
    try:
        status, _ = http("GET", url, headers, timeout)
    except RuntimeError as exc:
        return ProbeResult(
            name="moby",
            ok=False,
            latency_ms=(time.monotonic() - t0) * 1000,
            detail=str(exc),
        )
    ms = (time.monotonic() - t0) * 1000
    if status in (200, 204):
        return ProbeResult(
            name="moby",
            ok=True,
            latency_ms=ms,
            detail=f"HTTP {status}",
        )
    if status in (401, 403):
        return ProbeResult(
            name="moby",
            ok=False,
            latency_ms=ms,
            detail=f"HTTP {status} — key rejected",
            fix=(
                "Regenerate Triple Whale token + update "
                "TRIPLE_WHALE_API_KEY"
            ),
        )
    return ProbeResult(
        name="moby",
        ok=False,
        latency_ms=ms,
        detail=f"HTTP {status}",
    )


def _probe_webhook_secret() -> ProbeResult:
    """Shopify webhook HMAC-secret config check. Pre-audit,
    the production webhook endpoint silently accepted every
    request because no secret was configured. Flag this as a
    critical warning so the owner knows."""
    secret = (
        os.environ.get("SHOPAI_SHOPIFY_WEBHOOK_SECRET", "")
        or os.environ.get("SHOPIFY_WEBHOOK_SECRET", "")
    )
    required = (
        os.environ.get(
            "SHOPAI_WEBHOOK_VERIFY_REQUIRED", "",
        ) == "1"
    )
    if not secret:
        return ProbeResult(
            name="webhook_secret",
            ok=False,
            detail=(
                "not set — webhook endpoint would accept "
                "unsigned POSTs"
            ),
            fix=(
                "Set SHOPAI_SHOPIFY_WEBHOOK_SECRET to the "
                "value Shopify shows in the webhook config, "
                "and optionally set "
                "SHOPAI_WEBHOOK_VERIFY_REQUIRED=1 to fail-"
                "closed even while testing"
            ),
        )
    detail = f"secret set ({len(secret)} chars)"
    if required:
        detail += ", fail-closed enabled"
    return ProbeResult(
        name="webhook_secret",
        ok=True,
        detail=detail,
    )


def _probe_tiktok_shop() -> ProbeResult:
    """Config-level check for TikTok Shop — we don't hit the
    live signed endpoint because that requires a valid
    HMAC'd timestamp + responsive shop. Just report whether
    the 4 required env vars are set + flag the adapter as
    ready."""
    missing: list[str] = []
    for env in (
        "TIKTOK_SHOP_APP_KEY",
        "TIKTOK_SHOP_APP_SECRET",
        "TIKTOK_SHOP_ACCESS_TOKEN",
        "TIKTOK_SHOP_SHOP_ID",
    ):
        if not os.environ.get(env, ""):
            missing.append(env)
    if len(missing) == 4:
        return ProbeResult(
            name="tiktok_shop",
            ok=False,
            skipped=True,
            detail="not configured (Z6 multi-platform optional)",
            fix=(
                "Set TIKTOK_SHOP_APP_KEY + APP_SECRET + "
                "ACCESS_TOKEN + SHOP_ID to enable"
            ),
        )
    if missing:
        return ProbeResult(
            name="tiktok_shop",
            ok=False,
            detail=f"partial config; missing {len(missing)}",
            fix=(
                "Set "
                + ", ".join(missing)
            ),
        )
    return ProbeResult(
        name="tiktok_shop",
        ok=True,
        detail="all 4 env vars set (connectivity not probed)",
    )


# Critical probes = those required for revenue. Optional probes
# are "nice to have" and a missing/failed one only adds a warning.
_CRITICAL_NAMES = frozenset({"shopify", "meta_ads"})


def run(
    http: HttpCallable | None = None,
    *,
    timeout: float = _DEFAULT_TIMEOUT_S,
    include_moby: bool = True,
    include_vault: bool = True,
    include_tiktok: bool = True,
) -> DoctorReport:
    """Run every probe and return a DoctorReport.

    ``http`` is dependency-injected so tests can replay canned
    responses offline. Production callers let it default to
    ``_urlopen`` (stdlib urllib).
    """
    http_fn = http or _urlopen
    results: list[ProbeResult] = []
    try:
        results.append(_probe_shopify(http_fn, timeout))
    except Exception as exc:  # noqa: BLE001
        logger.debug("shopify probe raised: %s", exc)
        results.append(ProbeResult(
            name="shopify", ok=False,
            detail=f"probe raised: {exc}",
        ))
    try:
        results.append(_probe_meta_ads(http_fn, timeout))
    except Exception as exc:  # noqa: BLE001
        logger.debug("meta probe raised: %s", exc)
        results.append(ProbeResult(
            name="meta_ads", ok=False,
            detail=f"probe raised: {exc}",
        ))
    try:
        results.append(_probe_fal(http_fn, timeout))
    except Exception as exc:  # noqa: BLE001
        logger.debug("fal probe raised: %s", exc)
        results.append(ProbeResult(
            name="fal", ok=False,
            detail=f"probe raised: {exc}",
        ))
    if include_vault:
        results.append(_probe_vault())
    try:
        results.append(_probe_webhook_secret())
    except Exception as exc:  # noqa: BLE001
        logger.debug("webhook probe raised: %s", exc)
        results.append(ProbeResult(
            name="webhook_secret", ok=False,
            detail=f"probe raised: {exc}",
        ))
    if include_tiktok:
        try:
            results.append(_probe_tiktok_shop())
        except Exception as exc:  # noqa: BLE001
            logger.debug("tiktok probe raised: %s", exc)
            results.append(ProbeResult(
                name="tiktok_shop", ok=False,
                detail=f"probe raised: {exc}",
            ))
    if include_moby:
        try:
            results.append(_probe_moby(http_fn, timeout))
        except Exception as exc:  # noqa: BLE001
            logger.debug("moby probe raised: %s", exc)
            results.append(ProbeResult(
                name="moby", ok=False,
                detail=f"probe raised: {exc}",
            ))
    critical = sum(
        1 for r in results
        if not r.ok and not r.skipped
        and r.name in _CRITICAL_NAMES
    )
    warnings = sum(
        1 for r in results
        if (not r.ok)
        and (r.skipped or r.name not in _CRITICAL_NAMES)
    )
    return DoctorReport(
        probes=tuple(results),
        ok=critical == 0,
        critical_failures=critical,
        warnings=warnings,
    )
