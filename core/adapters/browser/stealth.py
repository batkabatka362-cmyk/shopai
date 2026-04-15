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


# Cheap HTML/title substring markers that indicate the page is a
# challenge wall rather than the content the caller asked for.
# Order matters — the first hit wins so put the most specific
# markers first.
_CAPTCHA_MARKERS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("cloudflare", (
        'cf-chl-bypass',              # cloudflare challenge form
        'cf-browser-verification',    # old variant
        'challenge-platform',         # new variant (challenges.cloudflare.com)
        'just a moment...',           # title text
        '/cdn-cgi/challenge-platform',
    )),
    ("hcaptcha", (
        'h-captcha',
        'hcaptcha.com',
    )),
    ("recaptcha", (
        'g-recaptcha',
        'www.google.com/recaptcha',
    )),
    ("datadome", (
        'datadome-',
        'geo.captcha-delivery.com',
    )),
    ("perimeterx", (
        '_px3',
        'px-captcha',
    )),
)


def detect_captcha(*, title: str = "", html: str = "", url: str = "") -> str | None:
    """Return the provider name if the page looks like a bot
    challenge, else ``None``.

    The check is intentionally cheap: lowercase substring match
    against the title, URL, and first 16 KB of HTML. False
    positives on a pentest page with ``g-recaptcha`` in a docs
    snippet are possible but rare — the wins (not hammering a
    challenge loop for 30 retries) dominate.
    """
    title_l = (title or "").lower()
    url_l = (url or "").lower()
    html_l = (html or "")[:16_384].lower()

    for provider, markers in _CAPTCHA_MARKERS:
        for marker in markers:
            m = marker.lower()
            if m in title_l or m in url_l or m in html_l:
                return provider
    return None
