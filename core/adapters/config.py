"""Adapter credential loading.

Reads vendor API keys / endpoints from environment variables (or
optionally from a ``.env`` file) and exposes them via a single
``AdapterConfig`` object so adapters never have to call
``os.environ`` directly.

Design notes:

* Hot-reloadable: ``AdapterConfig.reload()`` re-reads the
  environment without restarting the process. Useful for key
  rotation. Reads happen under a lock so concurrent
  ``get(...)`` calls during a reload do not see partial state.

* Never logged: secrets are returned by ``get()`` but the
  ``__repr__`` redacts them so accidental ``logger.debug(config)``
  calls do not leak keys into log files.

* Aliases: each adapter declares the env var it cares about
  (e.g. ``GROQ_API_KEY``). The config does NOT invent fallback
  names — explicit aliases are listed in ``ENV_ALIASES`` so
  changing them is a deliberate edit.

There is intentionally no encryption layer here. ShopAI runs
inside the operator's own infrastructure; secrets at rest live
in whatever secret manager the host already uses (Kubernetes
Secrets, AWS SM, dotenv, …). The adapter layer just reads them.
"""
from __future__ import annotations

import os
import threading
from typing import Any

from utils.logger import get_logger

logger = get_logger("adapters.config")


# Per-vendor env var names. Add a new key here when wiring a
# new adapter; the adapter then calls ``config.get("groq")`` etc.
ENV_ALIASES: dict[str, str] = {
    # ── LLM ────────────────────────────────────
    "groq":          "GROQ_API_KEY",
    "gemini":        "GEMINI_API_KEY",
    "deepseek":      "DEEPSEEK_API_KEY",
    "mistral":       "MISTRAL_API_KEY",
    "openrouter":    "OPENROUTER_API_KEY",
    "huggingface":   "HUGGINGFACE_API_KEY",
    "ollama_url":    "OLLAMA_BASE_URL",   # not a key, but a URL
    "anthropic":     "ANTHROPIC_API_KEY",
    "openai":        "OPENAI_API_KEY",

    # ── Search ────────────────────────────────
    "serper":        "SERPER_API_KEY",
    "brave_search":  "BRAVE_SEARCH_API_KEY",
    "perplexity":    "PERPLEXITY_API_KEY",
    "tavily":        "TAVILY_API_KEY",

    # ── Email / SMS ───────────────────────────
    "resend":        "RESEND_API_KEY",
    "brevo":         "BREVO_API_KEY",
    "sendgrid":      "SENDGRID_API_KEY",
    "klaviyo":       "KLAVIYO_API_KEY",
    "omnisend":      "OMNISEND_API_KEY",
    "postscript":    "POSTSCRIPT_API_KEY",
    # Twilio uses HTTP Basic auth: the Account SID is the
    # username and the Auth Token is the password. The "from"
    # number is tenant-wide so we keep it in config rather than
    # the per-call params.
    "twilio_account_sid": "TWILIO_ACCOUNT_SID",
    "twilio_auth_token":  "TWILIO_AUTH_TOKEN",
    "twilio_from_number": "TWILIO_FROM_NUMBER",

    # ── Media / scraping ──────────────────────
    "firecrawl":     "FIRECRAWL_API_KEY",
    "imagekit_pub":  "IMAGEKIT_PUBLIC_KEY",
    "imagekit_priv": "IMAGEKIT_PRIVATE_KEY",

    # ── Translation ───────────────────────────
    # DeepL free-tier keys end in ":fx"; paid-tier keys do not.
    # The adapter auto-selects the correct host based on that
    # suffix so operators never have to set a separate env var.
    "deepl":         "DEEPL_API_KEY",

    # ── Reviews / UGC ─────────────────────────
    # Judge.me uses an API token that's passed as a query
    # parameter (not a header). Keep the shop domain in the
    # per-call params rather than config so one ShopAI deployment
    # can fetch reviews for multiple shops.
    "judgeme":       "JUDGEME_API_TOKEN",

    # ── Payment processors ────────────────────
    # PayPal uses OAuth2 client credentials: both id + secret are
    # required, ``paypal_env`` is "live" or "sandbox" (default
    # sandbox so accidental misconfiguration never hits real money).
    "paypal_client_id":     "PAYPAL_CLIENT_ID",
    "paypal_client_secret": "PAYPAL_CLIENT_SECRET",
    "paypal_env":           "PAYPAL_ENV",
    # Stripe uses a single secret key. Live vs test is encoded in
    # the key prefix (sk_live_ vs sk_test_) — no separate env var.
    "stripe_secret_key":    "STRIPE_SECRET_KEY",
    "stripe_api_version":   "STRIPE_API_VERSION",

    # ── Shopify (already handled by core/auth/shopify_auth) ──
    "shopify_url":   "SHOPAI_SHOPIFY_URL",
    "shopify_key":   "SHOPAI_SHOPIFY_KEY",

    # ── Knowledge base (Obsidian) ────────
    "obsidian_vault_path": "OBSIDIAN_VAULT_PATH",

    # ── Vector databases ─────────────────
    # Weaviate: self-hosted (Docker) or Weaviate Cloud. The URL
    # points to the REST endpoint; gRPC port is inferred.
    "weaviate_url":     "WEAVIATE_URL",
    "weaviate_api_key": "WEAVIATE_API_KEY",
    # Pinecone: managed vector DB. API key + environment.
    "pinecone":         "PINECONE_API_KEY",
    "pinecone_environment": "PINECONE_ENVIRONMENT",

    # ── Advertising ──────────────────────
    # Google Ads: OAuth2 + developer token
    "google_ads_developer_token": "GOOGLE_ADS_DEVELOPER_TOKEN",
    "google_ads_client_id":       "GOOGLE_ADS_CLIENT_ID",
    "google_ads_client_secret":   "GOOGLE_ADS_CLIENT_SECRET",
    "google_ads_refresh_token":   "GOOGLE_ADS_REFRESH_TOKEN",
    "google_ads_customer_id":     "GOOGLE_ADS_CUSTOMER_ID",
    # Meta (Facebook) Ads: long-lived access token + ad account ID
    "meta_ads_access_token": "META_ADS_ACCESS_TOKEN",
    "meta_ads_account_id":   "META_ADS_ACCOUNT_ID",

    # ── Subscriptions ────────────────────
    "recharge":         "RECHARGE_API_TOKEN",

    # ── Voice / TTS ──────────────────────
    "elevenlabs":       "ELEVENLABS_API_KEY",

    # ── Automation ────────────────────────
    "zapier_nla":       "ZAPIER_NLA_API_KEY",

    # ── Helpdesk / Customer support ──────
    "intercom":         "INTERCOM_ACCESS_TOKEN",
}


class AdapterConfig:
    """Centralised credential lookup.

    Use ``get(alias)`` to fetch the value for an alias defined
    in ``ENV_ALIASES``. Returns an empty string when the var is
    unset (caller decides whether that means "not configured"
    or "use a default").
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cache: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        """Re-read every alias from ``os.environ``.

        Hot-reload-safe: callers can call this after rotating an
        API key and the next ``get()`` will see the new value
        without restarting the process. Reads happen under the
        lock so other threads never see partial state.
        """
        with self._lock:
            new_cache: dict[str, str] = {}
            for alias, env_name in ENV_ALIASES.items():
                value = os.environ.get(env_name, "") or ""
                new_cache[alias] = value
            self._cache = new_cache
        logger.debug(
            "AdapterConfig reloaded (%d aliases, %d set)",
            len(self._cache),
            sum(1 for v in self._cache.values() if v),
        )

    def get(self, alias: str, default: str = "") -> str:
        """Return the value for *alias* or *default* if unset."""
        with self._lock:
            return self._cache.get(alias, "") or default

    def has(self, alias: str) -> bool:
        """True iff the alias has a non-empty value."""
        with self._lock:
            return bool(self._cache.get(alias, ""))

    def env_var_for(self, alias: str) -> str:
        """Return the OS env var name backing *alias* (for error
        messages: "set GROQ_API_KEY=..."). Empty string if the
        alias is unknown."""
        return ENV_ALIASES.get(alias, "")

    def aliases(self) -> list[str]:
        with self._lock:
            return sorted(self._cache.keys())

    def configured_aliases(self) -> list[str]:
        """List the aliases that currently have a value set."""
        with self._lock:
            return sorted(k for k, v in self._cache.items() if v)

    def __repr__(self) -> str:
        # Redact secrets — never log raw values.
        with self._lock:
            configured = sum(1 for v in self._cache.values() if v)
        return (
            f"<AdapterConfig {configured}/{len(self._cache)} configured>"
        )

    def describe(self) -> dict[str, Any]:
        """Return a JSON-safe summary (counts only, no secrets)."""
        with self._lock:
            return {
                "total_aliases": len(self._cache),
                "configured_count": sum(1 for v in self._cache.values() if v),
                "configured": [k for k, v in self._cache.items() if v],
                "missing": [k for k, v in self._cache.items() if not v],
            }


# ── Module-level singleton ─────────────────────────────────────


_config: AdapterConfig | None = None
_config_lock = threading.Lock()


def get_config() -> AdapterConfig:
    """Return the process-wide adapter config singleton."""
    global _config
    if _config is None:
        with _config_lock:
            if _config is None:
                _config = AdapterConfig()
    return _config


def reset_config() -> None:
    """Force-reload the singleton (test helper)."""
    global _config
    with _config_lock:
        _config = AdapterConfig()
