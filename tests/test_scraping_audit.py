"""Tests for audit-pass-44 fixes — defensive hardening + 3 real
bugs across ``data_pipeline.ingestion.scraping`` (scraper.py,
crawler.py).

Real bugs fixed:

  * SECURITY: ``Scraper._fetch`` passed any URL straight to
    ``urllib.request.urlopen``, which accepts ``file://``
    (local file read), ``ftp://`` (leak), ``data://``, etc.
    A caller with partial control over the URL (scraped
    link, config-file entry, user-supplied query) could
    exfiltrate local files via ``file:///etc/passwd``. The
    fetch path now restricts to ``http`` / ``https``.

  * Crawler fetched each page TWO or THREE times instead of
    once:
      - ``crawl_site`` called ``scrape_page`` → 1 fetch
      - ``_extract_links`` called ``scrape_page`` AGAIN
        (with a dummy ``_links`` selector whose result is
        discarded), then called ``_fetch_raw_html`` → 2
        more fetches
      - ``extract_all_products`` re-fetched each product
        page 2 more times
    Per page cost pre-audit: 3+ HTTP calls. Fix: fetch once
    in ``crawl_site`` and pass the HTML to both the field
    parser and link parser.

  * ``_is_allowed`` mutated ``rp.allow_all = True`` in the
    "robots.txt unreachable" fallback. That DID work
    (``allow_all`` is a real but undocumented attribute the
    stdlib parser checks first in ``can_fetch``), but it's
    fragile: future stdlib refactors could rename the
    attribute and we'd silently start disallowing
    legitimate crawls. Now tracked explicitly via a
    ``_robots_unreachable`` set so the semantics are
    obvious at the call site.

  * Several ``.get(k, {}).get(...)`` chains in
    ``extract_product_data`` crashed on present-but-None
    ``offers`` / ``availability`` in malformed JSON-LD
    schemas.

  * ``_parse_price_float`` didn't handle European number
    format (``"1.234,56"``) and crashed on non-string input
    (int / float / None).

Plus defensive entry coercion on every public method.
"""
from __future__ import annotations

import threading
import unittest.mock as mock

import pytest

from data_pipeline.ingestion.scraping.crawler import Crawler
from data_pipeline.ingestion.scraping.scraper import (
    Scraper,
    ScraperError,
    _ALLOWED_SCHEMES,
)


# ═══════════════════════════════════════════════════════════
# Security: URL scheme allowlist
# ═══════════════════════════════════════════════════════════


class TestSchemeAllowlist:
    def test_file_scheme_rejected(self):
        s = Scraper()
        with pytest.raises(ScraperError, match="scheme"):
            s._fetch("file:///etc/passwd")

    def test_ftp_scheme_rejected(self):
        s = Scraper()
        with pytest.raises(ScraperError, match="scheme"):
            s._fetch("ftp://example.com/a")

    def test_data_scheme_rejected(self):
        s = Scraper()
        with pytest.raises(ScraperError, match="scheme"):
            s._fetch("data:text/plain,hello")

    def test_missing_host_rejected(self):
        s = Scraper()
        with pytest.raises(ScraperError, match="host"):
            s._fetch("http://")

    def test_http_and_https_allowed(self):
        assert "http" in _ALLOWED_SCHEMES
        assert "https" in _ALLOWED_SCHEMES

    def test_empty_url_rejected(self):
        s = Scraper()
        with pytest.raises(ScraperError, match="empty"):
            s._fetch("")
        with pytest.raises(ScraperError, match="empty"):
            s._fetch(None)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════
# Defensive entry coercion
# ═══════════════════════════════════════════════════════════


class TestScraperDefensive:
    def test_none_url_scrape_page(self):
        s = Scraper()
        r = s.scrape_page(None, {})  # type: ignore[arg-type]
        assert isinstance(r, dict)
        assert r["errors"]

    def test_none_selectors(self):
        """Monkey-patch _fetch to avoid a real network call."""
        s = Scraper()
        with mock.patch.object(s, "_fetch", return_value="<html></html>"):
            r = s.scrape_page("http://example.com", None)  # type: ignore[arg-type]
        assert isinstance(r, dict)

    def test_non_dict_selectors(self):
        s = Scraper()
        with mock.patch.object(s, "_fetch", return_value="<html></html>"):
            r = s.scrape_page("http://example.com", ["not", "a", "dict"])  # type: ignore[arg-type]
        assert isinstance(r, dict)

    def test_extract_product_data_none_html(self):
        s = Scraper()
        result = s.extract_product_data(None)  # type: ignore[arg-type]
        assert result["title"] == ""
        assert result["price"] is None

    def test_extract_product_data_non_string(self):
        s = Scraper()
        result = s.extract_product_data(42)  # type: ignore[arg-type]
        assert result["title"] == ""


# ═══════════════════════════════════════════════════════════
# Price parsing (European format + non-string inputs)
# ═══════════════════════════════════════════════════════════


class TestPriceParsing:
    def test_us_format_with_thousands(self):
        assert Scraper._parse_price_float("$1,234.56") == 1234.56

    def test_us_format_no_thousands(self):
        assert Scraper._parse_price_float("99.99") == 99.99

    def test_european_format(self):
        """Regression: pre-audit ``re.sub(r"[^\\d.]", "",
        text.replace(",", ""))`` turned ``"1.234,56"`` into
        ``"1.23456"`` (wrong). Now detects European format
        via regex."""
        assert Scraper._parse_price_float("1.234,56") == 1234.56

    def test_european_with_currency(self):
        assert Scraper._parse_price_float("€1.234,56") == 1234.56

    def test_integer_input(self):
        """Pre-audit was string-only."""
        assert Scraper._parse_price_float(99) == 99.0

    def test_float_input(self):
        assert Scraper._parse_price_float(99.5) == 99.5

    def test_none_input(self):
        assert Scraper._parse_price_float(None) is None

    def test_bool_input_rejected(self):
        # bool is a subclass of int, but price-as-bool makes no sense.
        assert Scraper._parse_price_float(True) is None

    def test_empty_string(self):
        assert Scraper._parse_price_float("") is None

    def test_garbage_string(self):
        assert Scraper._parse_price_float("not a price") is None


# ═══════════════════════════════════════════════════════════
# JSON-LD product extraction (present-but-None fields)
# ═══════════════════════════════════════════════════════════


class TestJsonLdExtraction:
    def test_null_offers_does_not_crash(self):
        """Regression: ``json_ld.get("offers", {}).get(...)``
        crashed on ``"offers": null``."""
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "Product", "name": "Test", "offers": null}
        </script>
        </head></html>
        """
        s = Scraper()
        try:
            import bs4  # noqa: F401
        except ImportError:
            pytest.skip("bs4 not installed")
        result = s.extract_product_data(html)
        assert result["title"] == "Test"
        assert result["price"] is None

    def test_null_availability(self):
        """Pre-audit ``offer.get("availability", "").replace(...)``
        crashed on ``"availability": null``."""
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "Product", "name": "Test",
         "offers": {"price": "9.99", "availability": null}}
        </script>
        </head></html>
        """
        s = Scraper()
        try:
            import bs4  # noqa: F401
        except ImportError:
            pytest.skip("bs4 not installed")
        result = s.extract_product_data(html)
        assert result["price"] == 9.99
        assert result["availability"] == ""

    def test_offers_as_list(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "Product", "name": "Test",
         "offers": [{"price": "5.00"}, {"price": "6.00"}]}
        </script>
        </head></html>
        """
        s = Scraper()
        try:
            import bs4  # noqa: F401
        except ImportError:
            pytest.skip("bs4 not installed")
        result = s.extract_product_data(html)
        assert result["price"] == 5.0


# ═══════════════════════════════════════════════════════════
# Scraper thread safety
# ═══════════════════════════════════════════════════════════


class TestScraperThreadSafety:
    def test_concurrent_throttle_does_not_crash(self):
        """Two threads calling _throttle on the same host
        must not raise dict-size-changed errors."""
        s = Scraper(rate_limit=0.0)  # no actual delay
        stop = threading.Event()
        errors: list[Exception] = []

        def worker(host_suffix: int):
            try:
                while not stop.is_set():
                    s._throttle(f"http://host{host_suffix % 5}")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        import time
        time.sleep(0.1)
        stop.set()
        for t in threads:
            t.join(timeout=2)
        assert not errors


# ═══════════════════════════════════════════════════════════
# Crawler: fetch-once behavior
# ═══════════════════════════════════════════════════════════


class TestCrawlerFetchOnce:
    def test_single_page_crawl_fetches_once(self):
        """Regression: pre-audit each page was fetched 2-3
        times (once via scrape_page, then again via
        _extract_links→_fetch_raw_html, and for product pages
        a further re-fetch in extract_all_products). Now the
        crawler should fetch each URL exactly once per crawl."""
        try:
            import bs4  # noqa: F401
        except ImportError:
            pytest.skip("bs4 not installed")

        c = Crawler(max_pages=1, depth=0, respect_robots=False, rate_limit=0.0)
        fetch_counts: dict[str, int] = {}

        def fake_fetch(url: str) -> str:
            fetch_counts[url] = fetch_counts.get(url, 0) + 1
            return (
                "<html><head><title>Test</title>"
                "<meta name='description' content='Test page'>"
                "</head><body><h1>Test Page</h1>"
                "<a href='/page2'>link</a></body></html>"
            )

        with mock.patch.object(c._scraper, "_fetch", side_effect=fake_fetch):
            results = c.crawl_site("http://example.com")

        assert len(results) == 1
        # The crawler may normalise the URL (adding trailing slash,
        # lowercasing scheme/host) before dispatching _fetch, so
        # assert on the total count rather than an exact key.
        assert sum(fetch_counts.values()) == 1, fetch_counts

    def test_two_page_crawl_fetches_each_once(self):
        try:
            import bs4  # noqa: F401
        except ImportError:
            pytest.skip("bs4 not installed")

        c = Crawler(max_pages=5, depth=1, respect_robots=False, rate_limit=0.0)
        fetch_counts: dict[str, int] = {}

        def fake_fetch(url: str) -> str:
            fetch_counts[url] = fetch_counts.get(url, 0) + 1
            if "page2" in url:
                return "<html><body><h1>Page 2</h1></body></html>"
            return (
                "<html><head><title>Home</title></head>"
                "<body><a href='http://example.com/page2'>p2</a></body></html>"
            )

        with mock.patch.object(c._scraper, "_fetch", side_effect=fake_fetch):
            results = c.crawl_site("http://example.com")

        # Each URL fetched exactly once.
        assert all(v == 1 for v in fetch_counts.values()), fetch_counts
        assert len(fetch_counts) == 2


# ═══════════════════════════════════════════════════════════
# Crawler: robots.txt fallback actually works
# ═══════════════════════════════════════════════════════════


class TestRobotsFallback:
    def test_unreachable_robots_tracked_explicitly(self):
        """Pre-audit the unreachable-robots fallback mutated
        the stdlib parser's ``allow_all`` attribute directly.
        That worked (``allow_all`` is a real if undocumented
        attribute), but it's fragile. Audit pass 44 tracks
        unreachability explicitly via ``_robots_unreachable``
        so the intent is visible at the call site."""
        c = Crawler(respect_robots=True)

        # Force robots.txt read to fail.
        with mock.patch(
            "urllib.robotparser.RobotFileParser.read",
            side_effect=Exception("network error"),
        ):
            allowed = c._is_allowed("http://no-such-host.invalid/page")

        assert allowed is True
        assert "http://no-such-host.invalid" in c._robots_unreachable

    def test_respect_robots_false_short_circuits(self):
        c = Crawler(respect_robots=False)
        assert c._is_allowed("http://any-url.example/path") is True
