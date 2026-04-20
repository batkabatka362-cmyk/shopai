# nav: adapters

Every external service lives behind an adapter. The rest
of the codebase never calls requests / SDKs directly.

## Physical source

`core/adapters/` — ~30+ adapters grouped by service:

- `shopify/` — Admin REST + GraphQL + OAuth.
  - `modern_client.py` — 2026-Q2 GraphQL w/ cost budget.
  - `oauth_auth.py` — static-token fallback.
  - Wave F: `core/auth/shopify_expiring_token.py` —
    60min access token + 90-day refresh (D1 pending).
- `ads/meta_ads.py` — Meta Ads v25+ with Andromeda.
- `ads/google_ads.py` — PMax + demand gen.
- `fulfillment/` — CJ, Autods, Spocket.
- `llms/` — Groq, Gemini, DeepSeek, OpenRouter,
  HuggingFace, Ollama fallback.
- `triplewhale/moby.py` — Moby Agents + RL
  disagreement log (C1).
- `fal/video_router.py` — cost-aware video gen (D1).
- `obsidian/` — vault ↔ memory bridge.
- `social/` — Twilio, SendGrid, Telegram.

## Facade

`adapters/__init__.py` re-exports the stable surface:
`MetaAdsAdapter`, `MobyAdapter`, `FalVideoRouter`,
`ShopifyModernClient`, `CJFulfillAdapter`,
`AgenticStorefrontBridge`, etc.

## Contract

Every adapter:
- `is_available()` → bool based on env config.
- Injectable `http=` for offline tests.
- `stats()` → diagnostics (call count, last error).
- Idempotent writes via `_client_request_id` when the
  upstream supports it.
- Never raises on transient failures — returns a
  neutral result + logs.debug.

## Rules

- Before building: check if an adapter already exists.
  `grep -rln <service> core/adapters/`.
- New adapter → contract test in
  `tests/test_<service>_adapter.py`.
- Secrets come from env or `config/settings.json`, never
  hard-coded.
