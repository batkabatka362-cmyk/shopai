"""ROLE-grouped credential inventory.

Joins the ``ENV_ALIASES`` registry in ``core/adapters/config.py``
with a curated category that explains what each credential
ENABLES (revenue-driving / cold-start / brain / etc.) so a fresh
operator sees both "what's missing" AND "what would it unlock".

Pure read-only. No Pattern J guard needed -- doesn't write to
disk; consults os.environ via AdapterConfig.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Each alias maps to (category, role_label, fix_hint).
# role_label answers the operator's question: "what does this
# unlock if I set it?"
#
# Categories ranked by importance for the autonomous earning loop:
#   1. shopify           -- mandatory (without it, nothing earns)
#   2. ad_channels       -- the revenue accelerator
#   3. email             -- the retention loop
#   4. brain             -- LLM consultant overlay
#   5. social            -- organic + paid social
#   6. cold_start        -- product sourcing + ad creative
#   7. observability     -- operator dashboards
#   8. support           -- customer service
#   9. reviews           -- UGC / trust signal
#  10. ad_intel          -- ad spy / opportunity discovery
#  11. workflow          -- automation glue
#  12. vector_db         -- AI memory backend
#  13. analytics         -- advanced metrics

# Where to sign up + get an API key. Maps alias -> URL.
# Only populated for the launch-critical signups (brain /
# ad_channels / email / cold_start / social / shopify);
# the rest fall back to the env-var name being self-
# documenting (and the operator's signup is rare or
# already-completed by the time they reach api-status).
SIGNUP_URLS: dict[str, str] = {
    # ── shopify ──
    "shopify_url": (
        "https://partners.shopify.com/ -> Create store"
    ),
    "shopify_key": (
        "Shopify Admin -> Apps -> Develop apps -> "
        "Admin API access token"
    ),
    # ── brain ──
    "openai":    "https://platform.openai.com/api-keys",
    "anthropic": "https://console.anthropic.com/settings/keys",
    "groq":      "https://console.groq.com/keys",
    "gemini":    "https://aistudio.google.com/app/apikey",
    "deepseek":  "https://platform.deepseek.com/api_keys",
    "mistral":   "https://console.mistral.ai/api-keys/",
    "openrouter": "https://openrouter.ai/keys",
    # ── ad_channels ──
    "meta_ads_access_token": (
        "https://developers.facebook.com/ -> Create app "
        "-> Marketing API -> long-lived token"
    ),
    "meta_ads_account_id": (
        "Meta Business Suite -> Ad Accounts -> "
        "Account ID (15 digits)"
    ),
    "google_ads_developer_token": (
        "https://ads.google.com/aw/apicenter -> "
        "Developer token"
    ),
    "google_ads_client_id": (
        "https://console.cloud.google.com/ -> "
        "OAuth 2.0 credentials"
    ),
    "google_ads_client_secret": (
        "same page as GOOGLE_ADS_CLIENT_ID"
    ),
    "google_ads_refresh_token": (
        "OAuth playground / one-time auth flow"
    ),
    # ── email ──
    "klaviyo":  "Klaviyo Account -> Settings -> "
                "API Keys -> Private API Key",
    "resend":   "https://resend.com/api-keys",
    "sendgrid": "https://app.sendgrid.com/settings/api_keys",
    "brevo":    "https://app.brevo.com/settings/keys/api",
    "postmark": "Postmark -> Servers -> API Tokens",
    # ── social ──
    "pinterest": (
        "https://developers.pinterest.com/ -> "
        "Create app -> Generate access token"
    ),
    "tiktok": (
        "https://business-api.tiktok.com/ -> "
        "Content Posting API"
    ),
    "instagram": (
        "https://developers.facebook.com/ -> Instagram "
        "Graph API (needs IG Business Account linked to "
        "a Facebook Page)"
    ),
    # ── cold_start ──
    "cj_email":    "https://developers.cjdropshipping.com/  "
                   "-- free signup",
    "cj_password": "same as CJ_DROPSHIPPING_EMAIL signup",
    "autods":      "https://www.autods.com/  "
                   "-- Dashboard -> Developer Settings -> "
                   "Generate API Token",
    "pexels":      "https://www.pexels.com/api/  -- "
                   "free key",
    "elevenlabs":  "https://elevenlabs.io/app/settings/api-keys",
    "runway":      "https://app.runwayml.com/ -> "
                   "Settings -> API",
    "stability_ai": "https://platform.stability.ai/account/keys",
    "removebg":    "https://www.remove.bg/api -- free key",
    "replicate":   "https://replicate.com/account/api-tokens",
    # ── reviews ──
    "judgeme":     "https://judge.me/ -> Settings -> API",
    # ── support ──
    "intercom":    "https://app.intercom.com/ -> "
                   "Settings -> Developer Hub -> API key",
}


def signup_url_for(alias: str) -> str:
    """Return the sign-up URL hint for an alias, or empty
    string when not catalogued."""
    return SIGNUP_URLS.get(alias, "")


# alias -> (category, role_label)
ALIAS_ROLES: dict[str, tuple[str, str]] = {
    # ── shopify (mandatory) ──
    "shopify_url": ("shopify", "Store URL"),
    "shopify_key": ("shopify", "Admin API token"),

    # ── ad_channels (high-value revenue accelerators) ──
    "meta_ads_access_token":
        ("ad_channels", "Meta Ads (Facebook + Instagram)"),
    "meta_ads_account_id":
        ("ad_channels", "Meta Ads account ID"),
    "google_ads_developer_token":
        ("ad_channels", "Google Ads"),
    "google_ads_client_id":
        ("ad_channels", "Google Ads OAuth client"),
    "google_ads_client_secret":
        ("ad_channels", "Google Ads OAuth secret"),
    "google_ads_refresh_token":
        ("ad_channels", "Google Ads refresh token"),
    "google_ads_customer_id":
        ("ad_channels", "Google Ads customer ID"),

    # ── email (retention loop) ──
    "klaviyo":  ("email", "Klaviyo (e-commerce ESP)"),
    "resend":   ("email", "Resend (transactional)"),
    "sendgrid": ("email", "SendGrid (transactional)"),
    "brevo":    ("email", "Brevo (marketing)"),
    "omnisend": ("email", "Omnisend (e-commerce)"),
    "postmark": ("email", "Postmark (transactional)"),
    "postscript": ("email", "Postscript (SMS marketing)"),

    # ── brain (LLM consultant -- SHOPAI_AI_STRATEGY=1) ──
    "openai":    ("brain", "OpenAI (primary LLM)"),
    "anthropic": ("brain", "Anthropic Claude (premium LLM)"),
    "groq":      ("brain", "Groq (fast cheap LLM)"),
    "gemini":    ("brain", "Google Gemini"),
    "deepseek":  ("brain", "DeepSeek"),
    "mistral":   ("brain", "Mistral"),
    "openrouter":("brain", "OpenRouter (multi-provider)"),
    "huggingface": ("brain", "HuggingFace"),
    "ollama_url": ("brain", "Ollama (local LLM URL)"),

    # ── social (organic + paid) ──
    "pinterest": ("social", "Pinterest API"),
    "tiktok":    ("social", "TikTok Business API"),
    "tiktok_business_id":
        ("social", "TikTok business account ID"),
    "instagram":
        ("social", "Instagram Graph API"),
    "instagram_account_id":
        ("social", "Instagram account ID"),

    # ── cold_start (product seeding + ad creative) ──
    "cj_email":
        ("cold_start", "CJ Dropshipping email"),
    "cj_password":
        ("cold_start", "CJ Dropshipping password"),
    "autods":
        ("cold_start", "AutoDS (paid dropshipping platform)"),
    "pexels":
        ("cold_start", "Pexels (stock video)"),
    "pixabay":
        ("cold_start", "Pixabay (stock video)"),
    "elevenlabs":
        ("cold_start", "ElevenLabs (voiceover)"),
    "higgsfield":
        ("cold_start", "Higgsfield (AI video)"),
    "runway":
        ("cold_start", "Runway Gen-3 (premium AI video)"),
    "replicate":
        ("cold_start", "Replicate (open AI models)"),
    "stability_ai":
        ("cold_start", "Stability AI (image gen)"),
    "removebg":
        ("cold_start", "RemoveBG (image cleanup)"),
    "imagekit_pub":
        ("cold_start", "ImageKit public key (CDN)"),
    "imagekit_priv":
        ("cold_start", "ImageKit private key (CDN)"),

    # ── observability (operator dashboards) ──
    "posthog":      ("observability", "PostHog"),
    "posthog_host": ("observability", "PostHog host"),
    "mixpanel":     ("observability", "Mixpanel"),
    "metabase_url": ("observability", "Metabase URL"),
    "metabase_api_key":
        ("observability", "Metabase API key"),

    # ── support (helpdesk) ──
    "intercom":         ("support", "Intercom"),
    "zendesk_subdomain":("support", "Zendesk subdomain"),
    "zendesk_email":    ("support", "Zendesk email"),
    "zendesk_api_token":("support", "Zendesk token"),
    "crisp_identifier": ("support", "Crisp identifier"),
    "crisp_key":        ("support", "Crisp key"),
    "crisp_website_id": ("support", "Crisp website ID"),

    # ── reviews ──
    "judgeme": ("reviews", "Judge.me (UGC reviews)"),

    # ── ad_intel ──
    "minea":              ("ad_intel", "Minea (ad spy, $49/mo)"),
    "pipiads":            ("ad_intel", "PiPiAds (TikTok spy)"),
    "bigspy":             ("ad_intel", "BigSpy (broad ad spy)"),
    "fb_ads_library_token":
        ("ad_intel", "FB Ads Library token"),
    "exa":                ("ad_intel", "Exa (search)"),
    "similarweb":         ("ad_intel", "SimilarWeb"),
    "perplexity":         ("ad_intel", "Perplexity"),
    "tavily":             ("ad_intel", "Tavily search"),
    "serper":             ("ad_intel", "Serper (Google search)"),
    "brave_search":       ("ad_intel", "Brave Search"),

    # ── workflow ──
    "zapier_nla":  ("workflow", "Zapier NLA"),
    "n8n_url":     ("workflow", "n8n URL"),
    "n8n_api_key": ("workflow", "n8n API key"),

    # ── vector_db ──
    "weaviate_url":    ("vector_db", "Weaviate URL"),
    "weaviate_api_key":("vector_db", "Weaviate API key"),
    "pinecone":        ("vector_db", "Pinecone"),
    "pinecone_environment":
        ("vector_db", "Pinecone environment"),
    "qdrant_url":      ("vector_db", "Qdrant URL"),
    "qdrant_api_key":  ("vector_db", "Qdrant API key"),
    "qdrant_collection":
        ("vector_db", "Qdrant collection"),

    # ── scraping / sourcing helpers ──
    "firecrawl": ("cold_start", "Firecrawl (web scraping)"),
    "apify":     ("cold_start", "Apify (web scraping)"),

    # ── translation ──
    "deepl": ("cold_start", "DeepL (translation)"),

    # ── payment processors ──
    "paypal_client_id":
        ("payment", "PayPal client ID"),
    "paypal_client_secret":
        ("payment", "PayPal client secret"),
    "paypal_env": ("payment", "PayPal env (live/sandbox)"),
    "stripe_secret_key":
        ("payment", "Stripe secret key"),
    "stripe_api_version":
        ("payment", "Stripe API version"),

    # ── subscriptions ──
    "recharge": ("retention", "ReCharge (subscriptions)"),

    # ── sms ──
    "twilio_account_sid":
        ("sms", "Twilio account SID"),
    "twilio_auth_token":
        ("sms", "Twilio auth token"),
    "twilio_from_number":
        ("sms", "Twilio from number"),
    "messagebird":
        ("sms", "MessageBird"),

    # ── crm ──
    "hubspot": ("support", "HubSpot CRM"),

    # ── knowledge ──
    "obsidian_vault_path":
        ("workflow", "Obsidian vault (knowledge base)"),
}


# Category metadata: priority + headline + fix-when-missing message.
# Categories are emitted in priority order (lower number = higher prio).
CATEGORIES: list[dict[str, object]] = [
    {
        "key": "shopify",
        "priority": 1,
        "title": "Shopify (MANDATORY)",
        "blocks": "Cannot earn -- Shopify creds are the bedrock.",
        "minimum": 2,
    },
    {
        "key": "brain",
        "priority": 2,
        "title": "Brain -- LLM consultant (recommended)",
        "blocks": (
            "SHOPAI_AI_STRATEGY=1 paths fall back to "
            "deterministic baselines without a brain key. "
            "One key is enough (openai is the canonical "
            "default; groq is the cheap/fast alternative)."
        ),
        "minimum": 1,
    },
    {
        "key": "ad_channels",
        "priority": 3,
        "title": "Ad channels (revenue accelerator)",
        "blocks": (
            "Without an ad channel adapter, ads_launcher / "
            "ads_creative_generator emit only PLANS, no "
            "live launches. Meta Ads is the highest-ROI "
            "starter."
        ),
        "minimum": 2,
    },
    {
        "key": "email",
        "priority": 4,
        "title": "Email (retention loop)",
        "blocks": (
            "Without email creds, cart_recovery / loyalty / "
            "welcome_series / browse_recovery / "
            "email_marketing can only mint codes -- no "
            "delivery. Klaviyo recommended for e-commerce."
        ),
        "minimum": 1,
    },
    {
        "key": "social",
        "priority": 5,
        "title": "Social channels (organic + paid)",
        "blocks": (
            "Pinterest + TikTok adapters exist and need "
            "creds. Instagram adapter is template-ready, "
            "needs both code wiring AND creds. Optional."
        ),
        "minimum": 0,
    },
    {
        "key": "cold_start",
        "priority": 6,
        "title": "Cold-start (product + ad creative)",
        "blocks": (
            "Without cold_start creds, earn-bootstrap can "
            "only emit research/candidates -- no creative "
            "generation. CJ for products + Pexels for "
            "stock video + ElevenLabs for voiceover is "
            "the minimal triple."
        ),
        "minimum": 1,
    },
    {
        "key": "observability",
        "priority": 7,
        "title": "Observability (operator dashboards)",
        "blocks": (
            "Optional -- the AGI loop self-reports via "
            "morning-brief / cycle status / empire. "
            "External dashboards are a nice-to-have."
        ),
        "minimum": 0,
    },
    {
        "key": "support",
        "priority": 8,
        "title": "Customer support",
        "blocks": (
            "Optional. customer_support engine wires "
            "ticket-tagging without support keys. "
            "Full helpdesk integration optional."
        ),
        "minimum": 0,
    },
    {
        "key": "reviews",
        "priority": 9,
        "title": "Reviews / UGC",
        "blocks": (
            "Optional. Judge.me unlocks review fetch + "
            "review_request automation."
        ),
        "minimum": 0,
    },
    {
        "key": "ad_intel",
        "priority": 10,
        "title": "Ad intelligence (spy / discovery)",
        "blocks": (
            "Optional. Ad spy tools accelerate cold-start "
            "creative -- without them the empire learns "
            "from its own attribution instead."
        ),
        "minimum": 0,
    },
    {
        "key": "workflow",
        "priority": 11,
        "title": "Workflow automation",
        "blocks": "Optional glue (Zapier / n8n).",
        "minimum": 0,
    },
    {
        "key": "vector_db",
        "priority": 12,
        "title": "Vector DB (AI memory backend)",
        "blocks": (
            "Optional. Local file-backed memory works "
            "without a vector DB; cloud vector DB scales."
        ),
        "minimum": 0,
    },
    {
        "key": "payment",
        "priority": 13,
        "title": "Payment processors",
        "blocks": (
            "Optional. Shopify Payments is built-in; "
            "PayPal / Stripe needed only for non-Shopify."
        ),
        "minimum": 0,
    },
    {
        "key": "sms",
        "priority": 14,
        "title": "SMS",
        "blocks": "Optional. SMS marketing channel.",
        "minimum": 0,
    },
    {
        "key": "retention",
        "priority": 15,
        "title": "Subscriptions",
        "blocks": "Optional. ReCharge for subscription products.",
        "minimum": 0,
    },
]


@dataclass
class AliasStatus:
    alias: str
    env_var: str
    role_label: str
    configured: bool
    signup_url: str = ""


@dataclass
class CategoryReport:
    key: str
    title: str
    priority: int
    blocks_msg: str
    minimum: int  # minimum aliases recommended for category to be "ready"
    aliases: list[AliasStatus] = field(default_factory=list)

    @property
    def configured_count(self) -> int:
        return sum(1 for a in self.aliases if a.configured)

    @property
    def total_count(self) -> int:
        return len(self.aliases)

    @property
    def status(self) -> str:
        c = self.configured_count
        m = self.minimum
        if m == 0:
            return "optional" if c == 0 else "ready"
        if c >= m:
            return "ready"
        return "incomplete"


@dataclass
class InventoryReport:
    total_aliases: int = 0
    configured_count: int = 0
    categories: list[CategoryReport] = field(
        default_factory=list,
    )
    headline: str = ""
    next_action: str = ""

    @property
    def incomplete_categories(self) -> list[CategoryReport]:
        return [
            c for c in self.categories
            if c.status == "incomplete"
        ]

    @property
    def ready_for_launch(self) -> bool:
        """All categories with minimum>0 must have >= minimum
        configured aliases."""
        return not any(
            c.status == "incomplete"
            for c in self.categories
        )


def build_inventory(
    *,
    env_aliases_override: dict[str, str] | None = None,
    configured_aliases_override: list[str] | None = None,
) -> InventoryReport:
    """Build the full ROLE-grouped inventory report.

    env_aliases_override + configured_aliases_override are
    test hooks: pass to bypass core.adapters.config and feed
    a synthetic state.
    """
    if env_aliases_override is None:
        from core.adapters.config import ENV_ALIASES
        env_aliases = dict(ENV_ALIASES)
    else:
        env_aliases = dict(env_aliases_override)

    if configured_aliases_override is None:
        from core.adapters.config import get_config
        configured = set(get_config().configured_aliases())
    else:
        configured = set(configured_aliases_override)

    report = InventoryReport()
    report.total_aliases = len(env_aliases)
    report.configured_count = sum(
        1 for a in env_aliases if a in configured
    )

    # Index aliases by category
    by_cat: dict[str, list[AliasStatus]] = {}
    for alias, env_var in env_aliases.items():
        role_entry = ALIAS_ROLES.get(alias)
        if role_entry is None:
            # Uncategorised alias -- park in 'other'
            cat_key = "other"
            role_label = alias
        else:
            cat_key, role_label = role_entry
        by_cat.setdefault(cat_key, []).append(AliasStatus(
            alias=alias,
            env_var=env_var,
            role_label=role_label,
            configured=alias in configured,
            signup_url=SIGNUP_URLS.get(alias, ""),
        ))

    # Build per-category reports in priority order
    seen_keys: set[str] = set()
    for cat_meta in CATEGORIES:
        key = str(cat_meta["key"])
        seen_keys.add(key)
        c = CategoryReport(
            key=key,
            title=str(cat_meta["title"]),
            priority=int(cat_meta["priority"]),
            blocks_msg=str(cat_meta["blocks"]),
            minimum=int(cat_meta["minimum"]),
            aliases=sorted(
                by_cat.get(key, []),
                key=lambda a: (a.configured, a.alias),
            ),
        )
        report.categories.append(c)

    # Catch any uncategorised aliases at the bottom
    leftover = [
        k for k in by_cat.keys() if k not in seen_keys
    ]
    for k in sorted(leftover):
        c = CategoryReport(
            key=k,
            title=f"Other ({k})",
            priority=999,
            blocks_msg="(uncategorised)",
            minimum=0,
            aliases=sorted(
                by_cat[k],
                key=lambda a: (a.configured, a.alias),
            ),
        )
        report.categories.append(c)

    # Compose headline + next_action
    incomplete = report.incomplete_categories
    if not report.categories:
        report.headline = "No adapter registry loaded."
        report.next_action = (
            "Check core/adapters/config.py is importable."
        )
    elif not incomplete:
        report.headline = (
            f"READY FOR LAUNCH -- "
            f"{report.configured_count}/{report.total_aliases} "
            "credential(s) configured; every required "
            "category meets its minimum."
        )
        report.next_action = (
            "shopai go-live  -- run the pre-flight gate "
            "before firing the first cycle."
        )
    else:
        top = incomplete[0]
        report.headline = (
            f"{len(incomplete)} categor(y/ies) below "
            "minimum. Top blocker: "
            f"{top.title} ({top.configured_count}/"
            f"{top.minimum} configured)."
        )
        # Suggest the first missing alias's env var
        missing_top = next(
            (a for a in top.aliases if not a.configured),
            None,
        )
        if missing_top:
            report.next_action = (
                f"Set {missing_top.env_var} (=...) for "
                f"'{missing_top.role_label}', then "
                "shopai api-status to re-check."
            )
        else:
            report.next_action = (
                f"Configure {top.minimum - top.configured_count} "
                f"more alias(es) in '{top.title}'."
            )

    return report
