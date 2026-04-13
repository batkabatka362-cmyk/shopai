"""Browser automation adapters.

Wraps headless browser engines (Playwright) behind ``BaseAdapter``
so the brain can request page scraping, screenshots, and data
extraction via the smart router.

Capabilities:

  * ``SCRAPE_PAGE``          — fetch a page's HTML / text content
  * ``BROWSER_SCREENSHOT``   — capture a full-page or viewport PNG
  * ``BROWSER_EXTRACT``      — extract structured data using CSS
                               selectors from a rendered page

Bootstrap::

    from core.adapters.browser.bootstrap import register_all
    register_all()
"""
from .playwright import PlaywrightAdapter

__all__ = ["PlaywrightAdapter"]
