"""Stealth patches + user-agent rotation for the browser adapter.

Commodity headless-Chromium is trivially detectable — sites look at
``navigator.webdriver``, the absence of a ``chrome`` runtime object,
a zero-length ``navigator.plugins`` array, and a dozen other giveaways.
Modern bot walls (Cloudflare, Datadome, PerimeterX) fingerprint the
browser within a handful of requests and serve a challenge page to
anything that looks automated.

This module ships two mitigations:

  * ``STEALTH_INIT_SCRIPT`` — a small JS snippet injected via
    ``context.add_init_script`` before any site JS runs. It papers
    over the cheapest, most widely-checked signals so a plain
    ``Chromium --headless`` looks like a real Chrome. It does
    **not** defeat sophisticated fingerprinting (canvas, WebGL,
    audio context) — that arms race needs a dedicated service.

  * ``pick_user_agent()`` — selects a modern UA string from a
    curated pool (Chrome, Firefox, Safari / Windows, macOS, Linux).
    Rotating the UA per context makes the request fleet look like
    a mixed population instead of 1000 identical bots.

Pair these with ``BrowserSession`` (cookie jar + persistent
context) so repeat visitors don't re-trip the wall on every hit.
"""
from __future__ import annotations

import hashlib
import random
from typing import Final

# Init script runs on every page in the context before site JS.
# Keep it small — every line adds to our detection surface. These
# patches cover the "cheap" tells that naive bot-detection checks.
STEALTH_INIT_SCRIPT: Final[str] = """
// 1. Hide the webdriver flag — the single most common tell.
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true,
});

// 2. Fake a populated plugins array (headless has an empty one).
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
        { name: 'Native Client', filename: 'internal-nacl-plugin' },
    ],
    configurable: true,
});

// 3. Fake realistic languages (match common geolocations).
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
    configurable: true,
});

// 4. Provide a chrome runtime object so feature checks don't fail.
if (!window.chrome) {
    window.chrome = { runtime: {} };
}

// 5. Permissions API: 'notifications' returning 'default' is the
//    real-browser behaviour; headless Chromium returns 'denied'.
if (navigator.permissions && navigator.permissions.query) {
    const origQuery = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = (parameters) => (
        parameters && parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : origQuery(parameters)
    );
}

// 6. WebGL vendor/renderer — many walls read these. Return common
//    desktop Intel/NVIDIA values instead of 'Google Inc.' / 'SwiftShader'.
try {
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function (parameter) {
        if (parameter === 37445) return 'Intel Inc.';      // UNMASKED_VENDOR_WEBGL
        if (parameter === 37446) return 'Intel Iris OpenGL Engine';
        return getParameter.apply(this, [parameter]);
    };
} catch (e) { /* WebGL may be unavailable in some contexts — ignore */ }
"""


# Curated modern user-agent pool. Each UA is a recent real build
# across Chrome / Firefox / Safari and Windows / macOS / Linux so
# the rotation looks like an organic browser mix.
_USER_AGENT_POOL: Final[tuple[str, ...]] = (
    # Chrome / Windows 10
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    # Chrome / macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    # Chrome / Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    # Firefox / Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
    "Gecko/20100101 Firefox/128.0",
    # Firefox / macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.5; rv:128.0) "
    "Gecko/20100101 Firefox/128.0",
    # Safari / macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    # Edge / Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
)


def pick_user_agent(*, seed: str | None = None) -> str:
    """Return a user-agent string.

    When *seed* is provided, the same seed always maps to the same
    UA (useful for per-profile stickiness — a "profile" browser
    shouldn't change UA between calls or sites will flag the
    inconsistency). Otherwise, a random UA is returned.
    """
    if seed is None:
        return random.choice(_USER_AGENT_POOL)
    # Deterministic per-seed: hash → index into pool.
    digest = hashlib.md5(seed.encode("utf-8")).digest()
    idx = int.from_bytes(digest[:4], "big") % len(_USER_AGENT_POOL)
    return _USER_AGENT_POOL[idx]


def user_agent_pool() -> tuple[str, ...]:
    """Exposed for tests and diagnostics."""
    return _USER_AGENT_POOL


# ── Captcha / bot-wall detection ───────────────────────────────


# Surface-bound markers to avoid the false-positive trap of
# matching "just a moment..." in a blog post or "g-recaptcha" in
# a Shopify login page (that's the SDK, not a challenge page).
#
# Each marker is a (surface, needle) pair where surface is one of
# ``{"title", "url", "html"}`` — the needle is ONLY matched on
# that surface. That way the distinctive markers (Cloudflare's
# cf-chl-bypass form, reCAPTCHA's challenge iframe URL) fire
# while the ambiguous ones (the word "recaptcha" appearing
# anywhere in HTML) no longer trip.
_CAPTCHA_MARKERS: Final[tuple[tuple[str, tuple[tuple[str, str], ...]], ...]] = (
    ("cloudflare", (
        ("html", "cf-chl-bypass"),              # challenge form
        ("html", "cf-browser-verification"),    # old variant
        ("html", "/cdn-cgi/challenge-platform"),
        ("url", "challenges.cloudflare.com"),
        # "Just a moment..." is the Cloudflare interstitial title;
        # it's also a valid English phrase, so we only flag it
        # when it's the ENTIRE title (not a substring of prose).
        ("title_exact", "just a moment..."),
        ("title_exact", "just a moment"),
    )),
    ("hcaptcha", (
        # hCaptcha challenge iframe lives at hcaptcha.com/captcha.
        ("url", "hcaptcha.com/captcha"),
        ("url", "newassets.hcaptcha.com"),
        ("html", 'data-hcaptcha-widget-id'),   # live widget marker
        ("html", 'class="h-captcha-challenge"'),
    )),
    ("recaptcha", (
        # Only the interactive challenge iframe — NOT the invisible
        # SDK include on ordinary login pages (that was the
        # false-positive the audit caught).
        ("url", "recaptcha/api2/bframe"),
        ("url", "recaptcha/enterprise/bframe"),
    )),
    ("datadome", (
        ("url", "geo.captcha-delivery.com"),
        ("html", 'id="ddg-captcha-container"'),
    )),
    ("perimeterx", (
        # "_px3" is too short → collides with random identifiers;
        # rely on the full challenge-page marker instead.
        ("html", 'px-captcha'),
        ("url", "captcha.px-cdn.net"),
    )),
)


def detect_captcha(*, title: str = "", html: str = "", url: str = "") -> str | None:
    """Return the provider name if the page looks like a bot
    challenge, else ``None``.

    Markers are bound to the surface where they actually appear:

      * ``title``       — case-insensitive substring of the title
      * ``title_exact`` — entire title equals the marker (used
                          for short everyday phrases like "just a
                          moment..." that collide with prose)
      * ``url``         — case-insensitive substring of the URL
      * ``html``        — case-insensitive substring of first 16 KB

    The scan is intentionally cheap — if you need 100% accuracy
    on an edge case, bypass with ``allow_captcha=True``.
    """
    title_raw = (title or "").strip()
    title_l = title_raw.lower()
    url_l = (url or "").lower()
    html_l = (html or "")[:16_384].lower()

    for provider, markers in _CAPTCHA_MARKERS:
        for surface, needle in markers:
            n = needle.lower()
            hit = False
            if surface == "title":
                hit = n in title_l
            elif surface == "title_exact":
                hit = title_l == n
            elif surface == "url":
                hit = n in url_l
            elif surface == "html":
                hit = n in html_l
            if hit:
                return provider
    return None
