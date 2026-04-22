"""Competitor intelligence agent — scrape + analyze other
Shopify stores.

Shopify exposes a surprising amount of data on every public
store:

  /products.json            — up to 250 products incl. prices,
                              titles, handles, images
  /collections.json         — category structure
  homepage HTML             — active offer, announcement bar
  script tags (in HTML)     — installed apps (Klaviyo, Loox,
                              PushOwl, ReCharge, etc)
  generator <meta>          — theme name (Dawn / Impulse /
                              custom)

The ``analyze_competitor`` function bundles all five reads
into a single scrape + optionally calls an LLM to synthesise
a strategic take ("here's what Gymshark's doing differently,
here's what Deguar should copy / avoid").

Soft-fail per source: if /collections.json 404s, the rest
still runs. If the LLM is unreachable, ``insights`` stays
empty + the raw data is still useful.

Pure stdlib. HTTP client + LLM dispatcher injectable for
tests.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from utils.logger import get_logger


logger = get_logger("agents.competitor_intel")


_SHOPIFY_APP_SIGNATURES: dict[str, str] = {
    "klaviyo": "Klaviyo (email/SMS)",
    "loox": "Loox (photo reviews)",
    "yotpo": "Yotpo (reviews/loyalty)",
    "judge.me": "Judge.me (reviews)",
    "rechargeapps": "Recharge (subscriptions)",
    "bold-subscriptions": "Bold Subscriptions",
    "pushowl": "PushOwl (push notifications)",
    "smile.io": "Smile.io (loyalty/referrals)",
    "swym": "Swym Wishlist",
    "tidio": "Tidio (chat)",
    "gorgias": "Gorgias (support)",
    "omnisend": "Omnisend (email)",
    "privy.com": "Privy (popups)",
    "optinly": "Optinly (popups)",
    "zipify": "Zipify (landing pages)",
    "shogun": "Shogun (page builder)",
    "gempages": "GemPages (page builder)",
    "trustpulse": "TrustPulse (social proof)",
    "fomo.com": "Fomo (social proof)",
    "privy-cdn": "Privy",
    "clearco": "Clearco (capital)",
    "upsellpopup": "Upsell Popup",
    "after-sell": "AfterSell",
    "reconvert": "ReConvert (post-purchase upsell)",
    "one-click-upsell": "OneClick Upsell",
    "bundle-upsell": "Bundle Upsell",
    "stamped.io": "Stamped (reviews)",
    "reviews.io": "Reviews.io",
    "facebook.net/tr": "Meta Pixel",
    "googletagmanager": "Google Tag Manager",
    "google-analytics": "Google Analytics",
    "hotjar": "Hotjar (heatmaps)",
    "tiktok-pixel": "TikTok Pixel",
    "analytics.tiktok": "TikTok Pixel",
}


HttpGetter = Callable[[str], dict[str, Any]]
LlmDispatcher = Callable[[str], str]


@dataclass
class StoreCatalogSummary:
    store: str
    product_count: int = 0
    price_range: tuple[float, float] = (0.0, 0.0)
    median_price: float = 0.0
    top_tags: list[str] = field(default_factory=list)
    top_types: list[str] = field(default_factory=list)
    top_products: list[dict[str, Any]] = field(
        default_factory=list,
    )
    newest_products: list[dict[str, Any]] = field(
        default_factory=list,
    )
    currencies: list[str] = field(default_factory=list)
    vendor: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "store": self.store,
            "product_count": self.product_count,
            "price_range": list(self.price_range),
            "median_price": round(self.median_price, 2),
            "top_tags": list(self.top_tags),
            "top_types": list(self.top_types),
            "top_products": list(self.top_products),
            "newest_products": list(self.newest_products),
            "currencies": list(self.currencies),
            "vendor": self.vendor,
            "error": self.error,
        }


@dataclass
class HomepageSignals:
    theme_hint: str = ""
    apps_detected: list[str] = field(default_factory=list)
    hero_heading: str = ""
    announcement_bar: str = ""
    has_meta_pixel: bool = False
    has_klaviyo: bool = False
    has_loox_or_judge: bool = False
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "theme_hint": self.theme_hint,
            "apps_detected": list(self.apps_detected),
            "hero_heading": self.hero_heading,
            "announcement_bar": self.announcement_bar,
            "has_meta_pixel": self.has_meta_pixel,
            "has_klaviyo": self.has_klaviyo,
            "has_loox_or_judge": self.has_loox_or_judge,
            "error": self.error,
        }


@dataclass
class CompetitorReport:
    store: str
    scraped_at: float = 0.0
    catalog: StoreCatalogSummary | None = None
    homepage: HomepageSignals | None = None
    collection_handles: list[str] = field(default_factory=list)
    insights: str = ""
    errors: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "store": self.store,
            "scraped_at": self.scraped_at,
            "product_count": (
                self.catalog.product_count
                if self.catalog else 0
            ),
            "price_range_usd": (
                list(self.catalog.price_range)
                if self.catalog else []
            ),
            "median_price_usd": (
                self.catalog.median_price
                if self.catalog else 0.0
            ),
            "theme": (
                self.homepage.theme_hint
                if self.homepage else ""
            ),
            "apps": (
                self.homepage.apps_detected
                if self.homepage else []
            ),
            "collections": len(self.collection_handles),
            "has_error": bool(self.errors),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "store": self.store,
            "scraped_at": self.scraped_at,
            "catalog": (
                self.catalog.as_dict()
                if self.catalog else None
            ),
            "homepage": (
                self.homepage.as_dict()
                if self.homepage else None
            ),
            "collection_handles": list(self.collection_handles),
            "insights": self.insights,
            "errors": list(self.errors),
            "summary": self.summary(),
        }


# ── HTTP defaults ────────────────────────────────────────


def _default_http_get(url: str) -> dict[str, Any]:
    """Return ``{"status": int, "body": str, "headers": dict}``."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (ShopAI Competitor Intel; "
            "+https://deguar.myshopify.com)"
        ),
        "Accept": (
            "text/html,application/json,"
            "application/xhtml+xml;q=0.9,*/*;q=0.8"
        ),
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode(
                resp.headers.get_content_charset() or "utf-8",
                errors="replace",
            )
            return {
                "status": resp.status,
                "body": body,
                "headers": dict(resp.headers),
            }
    except urllib.error.HTTPError as exc:
        return {
            "status": exc.code,
            "body": "",
            "error": f"HTTP {exc.code}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": 0,
            "body": "",
            "error": str(exc),
        }


# ── Catalog scrape ───────────────────────────────────────


def _normalise_host(store: str) -> str:
    s = store.strip()
    if s.startswith(("http://", "https://")):
        s = s.split("://", 1)[1]
    if s.endswith("/"):
        s = s[:-1]
    return s


def _fetch_products_json(
    store: str, http_get: HttpGetter,
) -> list[dict[str, Any]]:
    host = _normalise_host(store)
    # Up to 5 pages × 250 products = 1250 SKUs max
    products: list[dict[str, Any]] = []
    for page in range(1, 6):
        url = (
            f"https://{host}/products.json"
            f"?limit=250&page={page}"
        )
        resp = http_get(url)
        if resp.get("status") != 200 or not resp.get("body"):
            break
        try:
            payload = json.loads(resp["body"])
        except (TypeError, ValueError):
            break
        batch = payload.get("products", []) or []
        products.extend(batch)
        if len(batch) < 250:
            break
    return products


def _build_catalog_summary(
    store: str, products: list[dict[str, Any]],
) -> StoreCatalogSummary:
    if not products:
        return StoreCatalogSummary(
            store=store,
            error="no products fetched (store private or empty)",
        )
    prices: list[float] = []
    tags: dict[str, int] = {}
    types: dict[str, int] = {}
    vendors: dict[str, int] = {}
    currencies: set[str] = set()
    for p in products:
        # variants[].price
        for v in p.get("variants") or []:
            try:
                prices.append(float(v.get("price") or 0))
            except (TypeError, ValueError):
                pass
            if v.get("presentment_prices"):
                for pp in v["presentment_prices"]:
                    cur = (
                        pp.get("price", {}) or {}
                    ).get("currency_code")
                    if cur:
                        currencies.add(cur)
        for t in (p.get("tags") or "").split(","):
            t = t.strip()
            if t:
                tags[t] = tags.get(t, 0) + 1
        pt = (p.get("product_type") or "").strip()
        if pt:
            types[pt] = types.get(pt, 0) + 1
        v = (p.get("vendor") or "").strip()
        if v:
            vendors[v] = vendors.get(v, 0) + 1
    prices = [p for p in prices if p > 0]
    prices.sort()
    median = (
        prices[len(prices) // 2] if prices else 0.0
    )
    top_tags = [
        k for k, _ in sorted(
            tags.items(), key=lambda kv: -kv[1],
        )[:15]
    ]
    top_types = [
        k for k, _ in sorted(
            types.items(), key=lambda kv: -kv[1],
        )[:10]
    ]
    top_vendor = (
        sorted(
            vendors.items(), key=lambda kv: -kv[1],
        )[0][0]
        if vendors else ""
    )
    top_products = [
        {
            "title": p.get("title", ""),
            "handle": p.get("handle", ""),
            "type": p.get("product_type", ""),
            "price": (
                (p.get("variants") or [{}])[0].get("price", "")
            ),
        }
        for p in products[:10]
    ]
    sorted_by_date = sorted(
        products,
        key=lambda p: p.get("published_at") or "",
        reverse=True,
    )
    newest = [
        {
            "title": p.get("title", ""),
            "handle": p.get("handle", ""),
            "published_at": p.get("published_at", ""),
        }
        for p in sorted_by_date[:5]
    ]
    return StoreCatalogSummary(
        store=store,
        product_count=len(products),
        price_range=(
            (min(prices), max(prices))
            if prices else (0.0, 0.0)
        ),
        median_price=median,
        top_tags=top_tags,
        top_types=top_types,
        top_products=top_products,
        newest_products=newest,
        currencies=sorted(currencies),
        vendor=top_vendor,
    )


# ── Homepage scrape ──────────────────────────────────────


_THEME_META_RE = re.compile(
    r'<meta\s+name="generator"\s+content="([^"]+)"', re.I,
)
_H1_RE = re.compile(
    r"<h1[^>]*>\s*(.*?)\s*</h1>", re.I | re.S,
)
_ANNOUNCEMENT_RE = re.compile(
    r'class="[^"]*announcement[^"]*"[^>]*>\s*'
    r"(?:<[^>]+>\s*)*([^<]{5,200})",
    re.I | re.S,
)


def _detect_apps(html: str) -> list[str]:
    lower = html.lower()
    detected: list[str] = []
    seen: set[str] = set()
    for signature, label in _SHOPIFY_APP_SIGNATURES.items():
        if signature in lower and label not in seen:
            detected.append(label)
            seen.add(label)
    return detected


def _detect_theme(html: str) -> str:
    m = _THEME_META_RE.search(html)
    if m:
        return m.group(1).strip()
    # Shopify Dawn-family leaves a shopify-section-wrapper hint
    if "shopify-section-header" in html.lower():
        return "Shopify theme (unknown generator)"
    return ""


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _fetch_homepage_signals(
    store: str, http_get: HttpGetter,
) -> HomepageSignals:
    host = _normalise_host(store)
    resp = http_get(f"https://{host}/")
    if resp.get("status") != 200 or not resp.get("body"):
        return HomepageSignals(
            error=f"homepage fetch failed: "
            f"{resp.get('error') or resp.get('status')}",
        )
    html = resp["body"]
    theme = _detect_theme(html)
    apps = _detect_apps(html)
    h1 = _H1_RE.search(html)
    hero = _strip_tags(h1.group(1)) if h1 else ""
    ann = _ANNOUNCEMENT_RE.search(html)
    announcement = _strip_tags(ann.group(1)) if ann else ""
    return HomepageSignals(
        theme_hint=theme,
        apps_detected=apps,
        hero_heading=hero[:200],
        announcement_bar=announcement[:200],
        has_meta_pixel="Meta Pixel" in apps,
        has_klaviyo=any("Klaviyo" in a for a in apps),
        has_loox_or_judge=any(
            k in a.lower()
            for a in apps
            for k in ("loox", "judge")
        ),
    )


# ── Collections scrape ───────────────────────────────────


def _fetch_collection_handles(
    store: str, http_get: HttpGetter,
) -> list[str]:
    host = _normalise_host(store)
    resp = http_get(
        f"https://{host}/collections.json?limit=250",
    )
    if resp.get("status") != 200 or not resp.get("body"):
        return []
    try:
        data = json.loads(resp["body"])
    except (TypeError, ValueError):
        return []
    return [
        (c.get("handle") or "")
        for c in (data.get("collections") or [])
        if c.get("handle")
    ]


# ── LLM insight synthesis ────────────────────────────────


def _build_insight_prompt(
    our_store: str, report: CompetitorReport,
) -> str:
    cat = report.catalog
    hp = report.homepage
    lines = [
        f"You are analysing a competitor Shopify store for "
        f"{our_store}. Output a compact strategic take: "
        f"what they do well, what they skip, 2-3 concrete "
        f"moves our store should consider. Keep under "
        f"200 words. No preamble.",
        "",
        f"Competitor: {report.store}",
    ]
    if cat:
        lines.extend([
            f"Product count: {cat.product_count}",
            f"Price range: ${cat.price_range[0]:.2f}–"
            f"${cat.price_range[1]:.2f} "
            f"(median ${cat.median_price:.2f})",
            f"Top categories: {', '.join(cat.top_types[:5])}",
            f"Top tags: {', '.join(cat.top_tags[:10])}",
            f"Currencies: {', '.join(cat.currencies)}",
        ])
        lines.append("Sample newest products:")
        for np in cat.newest_products[:5]:
            lines.append(
                f"  - {np['title']} (/{np['handle']})",
            )
    if hp:
        lines.extend([
            f"Theme: {hp.theme_hint}",
            f"Apps: {', '.join(hp.apps_detected[:12])}",
            f"Hero H1: {hp.hero_heading}",
            f"Announcement: {hp.announcement_bar}",
        ])
    lines.append(
        f"Collections: {len(report.collection_handles)}",
    )
    return "\n".join(lines)


# ── Public API ───────────────────────────────────────────


def analyze_competitor(
    store: str,
    *,
    our_store: str = "deguar.myshopify.com",
    http_get: HttpGetter | None = None,
    llm: LlmDispatcher | None = None,
    now_fn: Callable[[], float] | None = None,
) -> CompetitorReport:
    """Scrape + summarise one competitor Shopify store.

    ``llm`` is optional — when missing, ``insights`` stays
    empty but the raw scraped data is still useful."""
    http = http_get or _default_http_get
    now = now_fn or time.time
    report = CompetitorReport(
        store=store, scraped_at=float(now()),
    )
    # Catalog
    try:
        products = _fetch_products_json(store, http)
        report.catalog = _build_catalog_summary(
            store, products,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "catalog scrape failed for %s: %s", store, exc,
        )
        report.errors.append(f"catalog: {exc}")
    # Collections
    try:
        report.collection_handles = (
            _fetch_collection_handles(store, http)
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "collections scrape failed for %s: %s",
            store, exc,
        )
        report.errors.append(f"collections: {exc}")
    # Homepage
    try:
        report.homepage = _fetch_homepage_signals(
            store, http,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "homepage scrape failed for %s: %s", store, exc,
        )
        report.errors.append(f"homepage: {exc}")
    # LLM insights
    if llm is not None:
        try:
            report.insights = llm(
                _build_insight_prompt(our_store, report),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "llm synthesis failed for %s: %s",
                store, exc,
            )
            report.errors.append(f"llm: {exc}")
    return report


def analyze_competitors(
    stores: list[str],
    *,
    our_store: str = "deguar.myshopify.com",
    http_get: HttpGetter | None = None,
    llm: LlmDispatcher | None = None,
    throttle_s: float = 0.5,
) -> list[CompetitorReport]:
    """Batch. Throttles between stores to stay friendly with
    each store's rate limits."""
    out: list[CompetitorReport] = []
    for s in stores:
        out.append(analyze_competitor(
            s, our_store=our_store,
            http_get=http_get, llm=llm,
        ))
        if throttle_s > 0 and s != stores[-1]:
            time.sleep(throttle_s)
    return out
