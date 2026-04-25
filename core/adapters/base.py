"""Adapter foundation: BaseAdapter, AdapterResult, Capability.

ShopAI's "Lego principle" surface. Every external dependency
(Shopify Admin API, Klaviyo, Gemini, Groq, Ollama, Firecrawl, …)
implements the same ``BaseAdapter`` interface so the brain can
ask for a *capability* (``"chat_complete"``, ``"send_email"``,
``"create_fulfillment"``) without knowing which vendor is going
to satisfy it. The smart router (``core/adapters/router.py``)
maps the capability to the best registered adapter at call time.

Three pieces define the surface:

  * ``Capability``      — registry of every action the adapter
                          ecosystem can perform. New adapters
                          declare which capabilities they
                          implement.
  * ``AdapterResult``   — uniform success/failure envelope. Wraps
                          the vendor's response so consumers
                          never depend on vendor-specific dicts.
  * ``BaseAdapter``     — abstract class. Concrete adapters
                          override ``execute()`` (and optionally
                          ``health_check()`` / ``estimate_cost()``).

The pattern intentionally mirrors how ``core/system/llm_adapter``
and ``core/auth/shopify_auth`` are structured so the rest of the
codebase recognises it on sight.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from utils.logger import get_logger

from .errors import AdapterError, AdapterNotConfigured, AdapterValidationError

logger = get_logger("adapters.base")


# ── Categorisation ─────────────────────────────────────────────


class AdapterCategory(str, Enum):
    """Top-level grouping. Used by the router for diagnostics
    and by metrics for cost rollups."""

    SHOPIFY_NATIVE = "shopify_native"     # Shopify Admin / GraphQL endpoints
    SHOPIFY_APP = "shopify_app"           # 3rd-party Shopify App store apps
    LLM = "llm"                            # Cloud or local LLM providers
    EMBEDDING = "embedding"                # Vector embedding models
    SEARCH = "search"                      # Web search APIs (Brave, Serper)
    SCRAPER = "scraper"                    # Web scraping (Firecrawl, Apify)
    EMAIL = "email"                        # Transactional / marketing email
    SMS = "sms"                            # SMS / push notification
    IMAGE_GEN = "image_gen"                # Image generation (Pollinations, HF)
    IMAGE_CDN = "image_cdn"                # Image CDN / optimization
    VIDEO_GEN = "video_gen"                # Video gen / stock video search (Pexels, Higgsfield)
    TRANSLATION = "translation"            # Translation services
    ANALYTICS = "analytics"                # Analytics ingestion / readout
    ADS = "ads"                            # Ad platform APIs
    PAYMENT = "payment"                    # Payment processors
    LOGISTICS = "logistics"                # Shipping carrier APIs
    KNOWLEDGE_BASE = "knowledge_base"      # Obsidian / Notion / local vaults
    BROWSER = "browser"                    # Browser automation (Playwright)
    VECTOR_DB = "vector_db"                # Vector databases (Weaviate, Pinecone)
    SUBSCRIPTION = "subscription"          # Subscription management (ReCharge)
    VOICE = "voice"                        # Voice / TTS / speech APIs
    AUTOMATION = "automation"              # Workflow automation (Zapier, n8n)
    REVIEWS = "reviews"                    # Product reviews (Judge.me)
    HELPDESK = "helpdesk"                  # Customer support (Intercom, Zendesk)
    CRM = "crm"                            # Customer relationship management (HubSpot)
    SOURCING = "sourcing"                  # Dropshipping suppliers (CJ, AutoDS, Spocket)
    OTHER = "other"


class Capability(str, Enum):
    """The verbs an adapter can offer. Adding a new capability
    here is a deliberate API change — every router consumer that
    asks for it must have at least one registered adapter that
    implements it, otherwise ``router.route()`` raises
    ``AdapterNotConfigured``.

    The set is intentionally small. Specific vendor features
    (e.g. "klaviyo_create_flow") should NOT show up here — they
    belong inside the adapter's params dict, behind a generic
    capability like ``send_email`` or ``trigger_flow``.
    """

    # ── LLM ────────────────────────────────────
    CHAT_COMPLETE = "chat_complete"           # General chat / instruction following
    REASON_DEEP = "reason_deep"               # Multi-step reasoning, planning
    REASON_FAST = "reason_fast"               # Low-latency single-shot reasoning
    CODE_GENERATE = "code_generate"           # Code generation (Rust for Functions)
    LONG_CONTEXT = "long_context"             # >100K token context
    IMAGE_ANALYZE = "image_analyze"           # Vision / multimodal input
    EMBED_TEXT = "embed_text"                 # Text → vector embedding

    # ── Shopify ────────────────────────────────
    SHOPIFY_FETCH_PRODUCTS = "shopify_fetch_products"
    SHOPIFY_FETCH_ORDERS = "shopify_fetch_orders"
    SHOPIFY_FETCH_CUSTOMERS = "shopify_fetch_customers"
    SHOPIFY_CREATE_FULFILLMENT = "shopify_create_fulfillment"
    SHOPIFY_ASSESS_RISK = "shopify_assess_risk"
    SHOPIFY_UPDATE_INVENTORY = "shopify_update_inventory"
    SHOPIFY_CREATE_DISCOUNT = "shopify_create_discount"
    SHOPIFY_LIST_DISCOUNTS = "shopify_list_discounts"
    SHOPIFY_UPDATE_CUSTOMER = "shopify_update_customer"
    SHOPIFY_CREATE_REFUND = "shopify_create_refund"
    SHOPIFY_QUERY_SEGMENT = "shopify_query_segment"
    SHOPIFY_SET_METAFIELD = "shopify_set_metafield"
    SHOPIFY_UPLOAD_FILE = "shopify_upload_file"
    SHOPIFY_LIST_FILES = "shopify_list_files"
    SHOPIFY_CREATE_DRAFT_ORDER = "shopify_create_draft_order"
    SHOPIFY_COMPLETE_DRAFT_ORDER = "shopify_complete_draft_order"
    SHOPIFY_LIST_DRAFT_ORDERS = "shopify_list_draft_orders"
    SHOPIFY_CREATE_MARKETING_ACTIVITY = "shopify_create_marketing_activity"
    SHOPIFY_UPDATE_MARKETING_ACTIVITY = "shopify_update_marketing_activity"
    SHOPIFY_ADD_MARKETING_ENGAGEMENT = "shopify_add_marketing_engagement"
    SHOPIFY_LIST_MARKETING_ACTIVITIES = "shopify_list_marketing_activities"
    SHOPIFY_LIST_RETURNS = "shopify_list_returns"
    SHOPIFY_GET_RETURN = "shopify_get_return"
    SHOPIFY_APPROVE_RETURN = "shopify_approve_return"
    SHOPIFY_DECLINE_RETURN = "shopify_decline_return"
    SHOPIFY_CREATE_METAOBJECT = "shopify_create_metaobject"
    SHOPIFY_UPDATE_METAOBJECT = "shopify_update_metaobject"
    SHOPIFY_GET_METAOBJECT = "shopify_get_metaobject"
    SHOPIFY_LIST_METAOBJECTS = "shopify_list_metaobjects"
    SHOPIFY_LIST_PUBLICATIONS = "shopify_list_publications"
    SHOPIFY_PUBLISH_RESOURCE = "shopify_publish_resource"
    SHOPIFY_UNPUBLISH_RESOURCE = "shopify_unpublish_resource"
    SHOPIFY_EDIT_ORDER = "shopify_edit_order"
    SHOPIFY_LIST_THEMES = "shopify_list_themes"
    SHOPIFY_LIST_THEME_FILES = "shopify_list_theme_files"
    SHOPIFY_UPSERT_THEME_FILES = "shopify_upsert_theme_files"
    SHOPIFY_RUN_ANALYTICS_QUERY = "shopify_run_analytics_query"
    SHOPIFY_GET_TRANSLATABLE_RESOURCE = "shopify_get_translatable_resource"
    SHOPIFY_REGISTER_TRANSLATIONS = "shopify_register_translations"
    SHOPIFY_REMOVE_TRANSLATIONS = "shopify_remove_translations"
    SHOPIFY_GET_SEGMENT_MEMBERS = "shopify_get_segment_members"
    SHOPIFY_CREATE_SEGMENT = "shopify_create_segment"
    SHOPIFY_GET_REFUND = "shopify_get_refund"
    SHOPIFY_LIST_ORDER_REFUNDS = "shopify_list_order_refunds"
    SHOPIFY_CREATE_PAYMENT_CUSTOMIZATION = "shopify_create_payment_customization"
    SHOPIFY_LIST_PAYMENT_CUSTOMIZATIONS = "shopify_list_payment_customizations"
    SHOPIFY_DELETE_PAYMENT_CUSTOMIZATION = "shopify_delete_payment_customization"
    SHOPIFY_CREATE_DELIVERY_CUSTOMIZATION = "shopify_create_delivery_customization"
    SHOPIFY_LIST_DELIVERY_CUSTOMIZATIONS = "shopify_list_delivery_customizations"
    SHOPIFY_DELETE_DELIVERY_CUSTOMIZATION = "shopify_delete_delivery_customization"
    SHOPIFY_CREATE_GIFT_CARD = "shopify_create_gift_card"
    SHOPIFY_LIST_GIFT_CARDS = "shopify_list_gift_cards"
    SHOPIFY_GET_GIFT_CARD = "shopify_get_gift_card"
    SHOPIFY_DEACTIVATE_GIFT_CARD = "shopify_deactivate_gift_card"
    SHOPIFY_LIST_SUBSCRIPTION_CONTRACTS = "shopify_list_subscription_contracts"
    SHOPIFY_GET_SUBSCRIPTION_CONTRACT = "shopify_get_subscription_contract"
    SHOPIFY_PAUSE_SUBSCRIPTION_CONTRACT = "shopify_pause_subscription_contract"
    SHOPIFY_RESUME_SUBSCRIPTION_CONTRACT = "shopify_resume_subscription_contract"
    SHOPIFY_CANCEL_SUBSCRIPTION_CONTRACT = "shopify_cancel_subscription_contract"
    SHOPIFY_LIST_MARKETS = "shopify_list_markets"
    SHOPIFY_GET_MARKET = "shopify_get_market"
    SHOPIFY_LIST_SHOP_LOCALES = "shopify_list_shop_locales"
    SHOPIFY_CREATE_WEB_PIXEL = "shopify_create_web_pixel"
    SHOPIFY_UPDATE_WEB_PIXEL = "shopify_update_web_pixel"
    SHOPIFY_DELETE_WEB_PIXEL = "shopify_delete_web_pixel"
    SHOPIFY_LIST_COMPANIES = "shopify_list_companies"
    SHOPIFY_GET_COMPANY = "shopify_get_company"
    SHOPIFY_CREATE_COMPANY = "shopify_create_company"
    SHOPIFY_LIST_LOCATIONS = "shopify_list_locations"
    SHOPIFY_GET_LOCATION = "shopify_get_location"
    SHOPIFY_CREATE_LOCATION = "shopify_create_location"
    SHOPIFY_UPDATE_LOCATION = "shopify_update_location"
    SHOPIFY_LIST_INVENTORY_SHIPMENTS = "shopify_list_inventory_shipments"
    SHOPIFY_GET_INVENTORY_SHIPMENT = "shopify_get_inventory_shipment"
    SHOPIFY_CREATE_INVENTORY_SHIPMENT = "shopify_create_inventory_shipment"
    SHOPIFY_LIST_CHANNELS = "shopify_list_channels"
    SHOPIFY_CREATE_CART_TRANSFORM = "shopify_create_cart_transform"
    SHOPIFY_LIST_CART_TRANSFORMS = "shopify_list_cart_transforms"
    SHOPIFY_DELETE_CART_TRANSFORM = "shopify_delete_cart_transform"
    SHOPIFY_CREATE_VALIDATION = "shopify_create_validation"
    SHOPIFY_LIST_VALIDATIONS = "shopify_list_validations"
    SHOPIFY_DELETE_VALIDATION = "shopify_delete_validation"
    SHOPIFY_LIST_PRODUCTS = "shopify_list_products"
    SHOPIFY_GET_PRODUCT = "shopify_get_product"
    SHOPIFY_CREATE_PRODUCT = "shopify_create_product"
    SHOPIFY_UPDATE_PRODUCT = "shopify_update_product"
    SHOPIFY_DELETE_PRODUCT = "shopify_delete_product"
    SHOPIFY_UPDATE_VARIANTS = "shopify_update_variants"
    SHOPIFY_LIST_ORDERS = "shopify_list_orders"
    SHOPIFY_GET_ORDER = "shopify_get_order"
    SHOPIFY_UPDATE_ORDER = "shopify_update_order"
    SHOPIFY_TAG_ORDER = "shopify_tag_order"
    SHOPIFY_UNTAG_ORDER = "shopify_untag_order"
    SHOPIFY_CLOSE_ORDER = "shopify_close_order"
    SHOPIFY_GET_CUSTOMER = "shopify_get_customer"
    SHOPIFY_CREATE_CUSTOMER = "shopify_create_customer"
    SHOPIFY_TAG_CUSTOMER = "shopify_tag_customer"
    SHOPIFY_UNTAG_CUSTOMER = "shopify_untag_customer"
    SHOPIFY_DELETE_CUSTOMER = "shopify_delete_customer"
    SHOPIFY_LIST_WEBHOOKS = "shopify_list_webhooks"
    SHOPIFY_CREATE_WEBHOOK = "shopify_create_webhook"
    SHOPIFY_UPDATE_WEBHOOK = "shopify_update_webhook"
    SHOPIFY_DELETE_WEBHOOK = "shopify_delete_webhook"
    SHOPIFY_RUN_BULK_QUERY = "shopify_run_bulk_query"
    SHOPIFY_GET_BULK_OPERATION = "shopify_get_bulk_operation"
    SHOPIFY_CANCEL_BULK_OPERATION = "shopify_cancel_bulk_operation"
    SHOPIFY_GET_SHOP = "shopify_get_shop"
    SHOPIFY_GET_SHOP_POLICIES = "shopify_get_shop_policies"
    SHOPIFY_LIST_CURRENCIES = "shopify_list_currencies"
    SHOPIFY_LIST_PAGES = "shopify_list_pages"
    SHOPIFY_GET_PAGE = "shopify_get_page"
    SHOPIFY_CREATE_PAGE = "shopify_create_page"
    SHOPIFY_UPDATE_PAGE = "shopify_update_page"
    SHOPIFY_DELETE_PAGE = "shopify_delete_page"
    SHOPIFY_LIST_BLOGS = "shopify_list_blogs"
    SHOPIFY_LIST_ARTICLES = "shopify_list_articles"
    SHOPIFY_GET_ARTICLE = "shopify_get_article"
    SHOPIFY_CREATE_ARTICLE = "shopify_create_article"
    SHOPIFY_UPDATE_ARTICLE = "shopify_update_article"
    SHOPIFY_DELETE_ARTICLE = "shopify_delete_article"
    SHOPIFY_RUN_BULK_MUTATION = "shopify_run_bulk_mutation"
    SHOPIFY_STAGE_UPLOAD = "shopify_stage_upload"
    SHOPIFY_LIST_DISPUTES = "shopify_list_disputes"
    SHOPIFY_GET_DISPUTE = "shopify_get_dispute"
    SHOPIFY_LIST_DELIVERY_PROFILES = "shopify_list_delivery_profiles"
    SHOPIFY_GET_DELIVERY_PROFILE = "shopify_get_delivery_profile"
    SHOPIFY_GET_DELIVERY_SETTINGS = "shopify_get_delivery_settings"

    # ── Search & research ─────────────────────
    WEB_SEARCH = "web_search"
    DEEP_RESEARCH = "deep_research"
    SCRAPE_PAGE = "scrape_page"

    # ── Communication ─────────────────────────
    SEND_EMAIL_TRANSACTIONAL = "send_email_transactional"
    SEND_EMAIL_CAMPAIGN = "send_email_campaign"
    SEND_SMS = "send_sms"
    SEND_PUSH = "send_push"

    # ── Media ─────────────────────────────────
    GENERATE_IMAGE = "generate_image"
    OPTIMIZE_IMAGE = "optimize_image"
    TRANSLATE_TEXT = "translate_text"

    # ── Marketplace integrations ──────────────
    PRODUCT_REVIEWS_FETCH = "product_reviews_fetch"
    SUBSCRIPTION_MANAGE = "subscription_manage"
    SHIPPING_RATE_QUOTE = "shipping_rate_quote"
    SHIPPING_LABEL_BUY = "shipping_label_buy"

    # ── Payment processing ────────────────────
    PAYMENT_REFUND = "payment_refund"
    PAYMENT_CAPTURE = "payment_capture"
    PAYMENT_LIST_DISPUTES = "payment_list_disputes"

    # ── Browser automation ────────────────
    BROWSER_SCREENSHOT = "browser_screenshot"
    BROWSER_EXTRACT = "browser_extract"
    BROWSER_CLICK = "browser_click"
    BROWSER_FILL = "browser_fill"
    BROWSER_WAIT_SELECTOR = "browser_wait_selector"

    # ── Vector database ──────────────────
    VECTOR_STORE = "vector_store"
    VECTOR_SEARCH = "vector_search"
    VECTOR_DELETE = "vector_delete"

    # ── Knowledge base ────────────────────
    VAULT_READ_NOTES = "vault_read_notes"
    VAULT_SEARCH_NOTES = "vault_search_notes"
    VAULT_WRITE_NOTE = "vault_write_note"

    # ── Advertising ───────────────────────
    ADS_CREATE_CAMPAIGN = "ads_create_campaign"
    ADS_GET_PERFORMANCE = "ads_get_performance"
    ADS_UPDATE_BUDGET = "ads_update_budget"
    ADS_PAUSE_CAMPAIGN = "ads_pause_campaign"
    ADS_RESUME_CAMPAIGN = "ads_resume_campaign"

    # ── Ads intelligence / spy ────────────
    # Used to discover winning products already proven on
    # competitor ad platforms. Every spy adapter (free scrapers
    # and paid APIs like Minea, PiPiAds, BigSpy) returns the
    # same normalised ad-record shape so the winning-product
    # engine can rank across sources without vendor-specific code.
    ADS_SPY_SEARCH = "ads_spy_search"            # Search ads by keyword/country
    ADS_SPY_TOP_PRODUCTS = "ads_spy_top_products"  # Trending products by engagement
    ADS_SPY_AD_DETAILS = "ads_spy_ad_details"      # Single ad deep-dive

    # ── Voice / TTS ──────────────────────
    VOICE_TEXT_TO_SPEECH = "voice_text_to_speech"
    VOICE_LIST_VOICES = "voice_list_voices"

    # ── Video generation / stock ─────────
    # Hybrid strategy: stock-video libraries (Pexels) + AI video
    # generators (Higgsfield/Sora/Veo) + simple slideshow fallback.
    # Consumers call the capability; the router picks the best
    # configured adapter. Every adapter returns a unified "clip"
    # record so the ad_creative_generator engine can compose
    # videos without vendor-specific code.
    VIDEO_STOCK_SEARCH = "video_stock_search"    # Pexels / Pixabay: query → clips
    VIDEO_GENERATE = "video_generate"            # AI text→video (Higgsfield/Sora/Veo)
    VIDEO_GET_STATUS = "video_get_status"        # Poll async AI video job status

    # ── Automation ────────────────────────
    AUTOMATION_TRIGGER = "automation_trigger"
    AUTOMATION_LIST_ZAPS = "automation_list_zaps"

    # ── Helpdesk / Customer support ──────
    HELPDESK_LIST_CONVERSATIONS = "helpdesk_list_conversations"
    HELPDESK_SEND_REPLY = "helpdesk_send_reply"
    HELPDESK_SEARCH_CONTACTS = "helpdesk_search_contacts"
    HELPDESK_CREATE_TICKET = "helpdesk_create_ticket"

    # ── Analytics ─────────────────────────
    ANALYTICS_TRACK_EVENT = "analytics_track_event"
    ANALYTICS_QUERY = "analytics_query"
    ANALYTICS_IDENTIFY = "analytics_identify"

    # ── CRM ──────────────────────────────
    CRM_SEARCH_CONTACTS = "crm_search_contacts"
    CRM_UPSERT_CONTACT = "crm_upsert_contact"
    CRM_LIST_DEALS = "crm_list_deals"
    CRM_CREATE_DEAL = "crm_create_deal"

    # ── Sourcing / dropshipping ───────────
    SOURCING_SEARCH_PRODUCTS = "sourcing_search_products"
    SOURCING_GET_PRODUCT = "sourcing_get_product"
    SOURCING_CREATE_ORDER = "sourcing_create_order"
    SOURCING_GET_ORDER_STATUS = "sourcing_get_order_status"


# ── Result envelope ────────────────────────────────────────────


@dataclass
class AdapterResult:
    """Uniform return value for ``BaseAdapter.execute``.

    Wraps the vendor's response so consumers never depend on
    vendor-specific dicts. Carries metadata (latency, cost, model
    used) that the metrics layer feeds back into the smart
    router's cost optimiser.

    The ``ok`` flag is the only thing callers need to check —
    failures populate ``error`` (with the typed exception) and
    leave ``data`` empty.
    """

    ok: bool
    adapter: str                                # Name of the adapter that ran
    capability: str                             # Capability that was requested
    data: dict[str, Any] = field(default_factory=dict)
    error: AdapterError | None = None
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""                             # Specific model the vendor used
    raw: Any = None                             # Vendor's raw response (for debugging)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(
        cls,
        adapter: str,
        capability: str,
        data: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AdapterResult:
        return cls(
            ok=True,
            adapter=adapter,
            capability=capability,
            data=data or {},
            **kwargs,
        )

    @classmethod
    def failure(
        cls,
        adapter: str,
        capability: str,
        error: AdapterError,
        **kwargs: Any,
    ) -> AdapterResult:
        return cls(
            ok=False,
            adapter=adapter,
            capability=capability,
            error=error,
            **kwargs,
        )


# ── Base adapter abstract class ────────────────────────────────


class BaseAdapter(ABC):
    """Abstract base for every adapter in the registry.

    Concrete adapters MUST set:

      * ``name``         — unique snake_case identifier (used as
                           registry key + metrics key + log tag)
      * ``category``     — see ``AdapterCategory``
      * ``capabilities`` — set of ``Capability`` enums it can serve

    They MAY override:

      * ``cost_per_call`` — average $/call (for budget routing)
      * ``priority``      — higher = preferred when multiple
                            adapters offer the same capability
                            (default 50)
      * ``health_check()`` — vendor ping; default returns
                             ``is_configured()``
      * ``estimate_cost(params)`` — per-call cost estimate

    They MUST implement ``_execute()`` which returns an
    ``AdapterResult``. The public ``execute()`` wraps it with
    timing, error normalisation, and metrics emission so concrete
    adapters never have to repeat that boilerplate.
    """

    name: str = ""
    category: AdapterCategory = AdapterCategory.OTHER
    capabilities: set[Capability] = set()
    cost_per_call: float = 0.0
    priority: int = 50

    def __init__(self) -> None:
        if not self.name:
            raise ValueError(
                f"{type(self).__name__}.name must be set",
            )
        if not self.capabilities:
            raise ValueError(
                f"{type(self).__name__}.capabilities must be non-empty",
            )

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        """Return True iff the adapter has everything it needs to
        run a real call (API key, local model file, etc.). The
        smart router skips unconfigured adapters silently.

        Default: True (override in concrete adapters that need
        credentials)."""
        return True

    def health_check(self) -> bool:
        """Best-effort vendor liveness probe. Default: just check
        configuration — concrete adapters can override with a
        real ping (e.g. GET /health, list models)."""
        return self.is_configured()

    def supports(self, capability: Capability | str) -> bool:
        """True iff this adapter implements *capability*."""
        if isinstance(capability, str):
            try:
                capability = Capability(capability)
            except ValueError:
                return False
        return capability in self.capabilities

    # ── Cost estimation ────────────────────────────────────────

    def estimate_cost(self, capability: Capability, params: dict[str, Any]) -> float:
        """Optional pre-flight cost estimate in USD. The router
        uses this when the caller passes a ``budget`` constraint.
        Default: ``cost_per_call`` regardless of params."""
        return float(self.cost_per_call)

    # ── Execution surface ──────────────────────────────────────

    def execute(
        self,
        capability: Capability | str,
        params: dict[str, Any] | None = None,
    ) -> AdapterResult:
        """Public entry point. Validates the request, calls
        ``_execute()`` with timing, normalises any vendor
        exception into an ``AdapterError`` subclass, and emits
        metrics.

        Concrete adapters override ``_execute()``, NOT this
        method, so the timing/metrics/normalisation contract is
        guaranteed across the registry.
        """
        params = params or {}

        # Capability normalisation
        try:
            cap = (
                capability
                if isinstance(capability, Capability)
                else Capability(capability)
            )
        except ValueError as exc:
            err = AdapterValidationError(
                self.name, f"unknown capability: {capability!r}",
            )
            return AdapterResult.failure(self.name, str(capability), err)

        if cap not in self.capabilities:
            err = AdapterValidationError(
                self.name, f"adapter does not implement {cap.value}",
            )
            return AdapterResult.failure(self.name, cap.value, err)

        if not self.is_configured():
            err = AdapterNotConfigured(self.name, "missing credentials")
            return AdapterResult.failure(self.name, cap.value, err)

        start = time.monotonic()
        try:
            result = self._execute(cap, params)
        except AdapterError as exc:
            elapsed = (time.monotonic() - start) * 1000
            logger.warning(
                "adapter %s failed (%s): %s",
                self.name, type(exc).__name__, exc.reason,
            )
            return AdapterResult.failure(
                self.name, cap.value, exc, latency_ms=round(elapsed, 2),
            )
        except Exception as exc:  # noqa: BLE001
            # Vendor / library raised something we don't know
            # how to classify — wrap as generic AdapterError so
            # the router can still react.
            elapsed = (time.monotonic() - start) * 1000
            logger.exception(
                "adapter %s raised unexpected %s",
                self.name, type(exc).__name__,
            )
            err = AdapterError(self.name, f"{type(exc).__name__}: {exc}")
            return AdapterResult.failure(
                self.name, cap.value, err, latency_ms=round(elapsed, 2),
            )

        # _execute is allowed to return a fully-formed
        # AdapterResult OR raise. Patch the latency in if it
        # didn't set one.
        if not isinstance(result, AdapterResult):
            err = AdapterValidationError(
                self.name,
                f"_execute returned {type(result).__name__}, "
                f"expected AdapterResult",
            )
            return AdapterResult.failure(self.name, cap.value, err)

        if result.latency_ms == 0.0:
            result.latency_ms = round((time.monotonic() - start) * 1000, 2)
        if not result.adapter:
            result.adapter = self.name
        if not result.capability:
            result.capability = cap.value

        return result

    @abstractmethod
    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        """Concrete execution. Implement in subclasses.

        May raise any ``AdapterError`` subclass — the public
        ``execute()`` will catch and wrap it. Should never raise
        a bare ``Exception``; vendor errors must be classified.
        """

    # ── Diagnostics ────────────────────────────────────────────

    def describe(self) -> dict[str, Any]:
        """Return a JSON-serialisable description of this
        adapter. Used by ``AdapterRegistry.list()`` and the
        observability dashboard."""
        return {
            "name": self.name,
            "category": self.category.value,
            "capabilities": sorted(c.value for c in self.capabilities),
            "configured": self.is_configured(),
            "cost_per_call": self.cost_per_call,
            "priority": self.priority,
        }
