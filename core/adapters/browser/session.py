"""BrowserSession — persistent Chromium + per-profile context pool.

The naive adapter pattern (fire up Chromium, do one thing, tear it
down) costs 2-4 seconds per call and loses every cookie between
hits. That's fine for a one-off scrape, but a controller that
touches the same e-commerce site 50 times a cycle burns two
minutes on browser-launch overhead and triggers a bot wall on hit
#3 because the session never sticks.

``BrowserSession`` fixes both:

  * **One persistent Playwright + Chromium** — launched lazily on
    first use, kept alive for the process lifetime, torn down
    cleanly on ``shutdown()``. Amortises the launch cost across
    every call.

  * **Per-profile contexts with a cookie jar** — a "profile" is
    the operator's chosen identity (e.g. ``"shopify-main"``,
    ``"google-review-crawler"``). Each profile gets its own
    ``BrowserContext`` with its own cookies, UA, and storage.
    Cookies persist to disk under ``<cookie_dir>/<profile>.json``
    so sessions survive process restarts.

  * **Per-profile lock** — Playwright's sync API is not
    thread-safe on a single context, so calls against the same
    profile serialize. Different profiles run in parallel.

  * **Stealth patches** — every new context gets
    ``STEALTH_INIT_SCRIPT`` injected before any site JS runs, so
    naive ``navigator.webdriver`` checks return false.

  * **UA rotation** — each profile picks a stable UA derived from
    its name (hashed) so a profile looks consistent across calls,
    but different profiles look like different browsers.

Typical usage (from the adapter)::

    session = BrowserSession.instance()
    with session.acquire_page(profile="shopify-main", timeout_ms=30_000) as page:
        page.goto(url)
        ...

Best-effort: if ``playwright`` is not installed, ``instance()``
still returns an object whose ``acquire_page`` raises
``AdapterUnavailable``. The caller (BaseAdapter) maps that to a
soft skip.
"""
from __future__ import annotations

import atexit
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar, Iterator

from utils.logger import get_logger

from ..errors import AdapterError, AdapterUnavailable
from .stealth import STEALTH_INIT_SCRIPT, pick_user_agent

try:
    from playwright.sync_api import sync_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PLAYWRIGHT_AVAILABLE = False
    sync_playwright = None  # type: ignore[assignment]

logger = get_logger("adapters.browser.session")


_DEFAULT_VIEWPORT: dict[str, int] = {"width": 1920, "height": 1080}
_DEFAULT_COOKIE_DIR = "/tmp/shopai_browser_profiles"


class BrowserSession:
    """Process-wide persistent browser + per-profile context pool.

    Thread-safe. Construct via ``instance()`` — the constructor
    exists for tests and advanced callers but the singleton is
    what production code should use.
    """

    _instance: ClassVar["BrowserSession | None"] = None
    _singleton_lock: ClassVar[threading.Lock] = threading.Lock()

    # ── Construction / singleton ──────────────────────────────

    def __init__(
        self,
        *,
        cookie_dir: str | None = None,
        headless: bool = True,
        register_atexit: bool = True,
    ) -> None:
        self._cookie_dir = Path(cookie_dir or _DEFAULT_COOKIE_DIR)
        self._headless = headless

        # Lazy playwright handles.
        self._pw: Any = None
        self._browser: Any = None
        self._start_lock = threading.Lock()

        # Per-profile context + lock.
        self._contexts: dict[str, Any] = {}
        self._profile_locks: dict[str, threading.Lock] = {}
        self._file_locks: dict[str, threading.Lock] = {}
        self._context_map_lock = threading.Lock()

        # One-way lifecycle flag. Once True, all ``acquire_page``
        # calls fail loudly instead of silently re-launching
        # Chromium on top of a shutting-down session.
        self._closed = False

        # Diagnostics.
        self._launch_count = 0
        self._acquire_count = 0
        self._captcha_count = 0

        # Process-exit safety net: flush cookies + close the
        # browser even if the caller forgets ``shutdown()``.
        # Tests opt out to keep the pytest atexit registry clean.
        if register_atexit:
            atexit.register(self._atexit_shutdown)

    @classmethod
    def instance(
        cls,
        *,
        cookie_dir: str | None = None,
        headless: bool = True,
    ) -> "BrowserSession":
        """Return the process-wide singleton, creating on first call.

        The cookie_dir / headless flags only apply on first
        construction; subsequent calls ignore them and return the
        existing instance. Use ``reset()`` to force a fresh one
        (primarily for tests).
        """
        if cls._instance is not None:
            return cls._instance
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls(
                    cookie_dir=cookie_dir, headless=headless,
                )
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Tear down the current singleton (if any). Intended for
        tests — production code should call ``shutdown()`` on the
        specific instance instead."""
        with cls._singleton_lock:
            if cls._instance is not None:
                try:
                    cls._instance.shutdown()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("reset shutdown error: %s", exc)
                cls._instance = None

    # ── Availability ──────────────────────────────────────────

    @property
    def is_available(self) -> bool:
        """True if Playwright imported successfully. Adapters
        check this instead of trying to launch and catching."""
        return _PLAYWRIGHT_AVAILABLE

    @property
    def launch_count(self) -> int:
        return self._launch_count

    @property
    def acquire_count(self) -> int:
        return self._acquire_count

    @property
    def captcha_count(self) -> int:
        return self._captcha_count

    def note_captcha(self) -> None:
        """Called by the adapter when detect_captcha fires — kept
        here so metrics live alongside other session diagnostics."""
        self._captcha_count += 1

    # ── Lifecycle ─────────────────────────────────────────────

    def _ensure_browser(self) -> None:
        """Start playwright + launch Chromium if not already up.

        Acquires ``_start_lock`` for the full check-and-launch so
        a concurrent ``shutdown()`` can't nil ``_browser`` between
        the fast-path check and the use-the-browser statement
        above the caller. ``shutdown()`` also takes this lock, so
        the two operations serialise.
        """
        if not _PLAYWRIGHT_AVAILABLE:
            raise AdapterUnavailable(
                "browser_session", "playwright not installed",
            )
        with self._start_lock:
            if self._closed:
                raise AdapterUnavailable(
                    "browser_session", "session is closed",
                )
            if self._browser is not None:
                return
            # sync_playwright().start() is the manual variant of the
            # context manager — returns a live Playwright object we
            # stop() in shutdown().
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(
                headless=self._headless,
                # Extra args reduce noise from headless fingerprint.
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
            )
            self._launch_count += 1
            logger.info("BrowserSession: launched Chromium (launch_count=%d)",
                        self._launch_count)

    def shutdown(self) -> None:
        """Close every context + the browser + stop playwright.

        Saves each profile's cookies/storage_state to disk first.
        Safe to call multiple times. After shutdown, any further
        ``acquire_page`` raises ``AdapterUnavailable`` — ``_closed``
        is a one-way flag.
        """
        # Take both locks so ``_ensure_browser`` cannot be racing
        # with us. Order: start_lock first, context_map_lock
        # second — same order as ``acquire_page`` never holds both
        # simultaneously, so no deadlock path exists.
        with self._start_lock:
            already_closed = self._closed
            self._closed = True
            # Snapshot profiles under the map lock so a concurrent
            # ``_get_or_create_context`` (which also takes it) is
            # either fully done or fully blocked.
            with self._context_map_lock:
                contexts = list(self._contexts.items())
                self._contexts.clear()
                self._profile_locks.clear()
                self._file_locks.clear()

            for profile, ctx in contexts:
                try:
                    self._save_storage_state(profile, ctx)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("save state for %s failed: %s", profile, exc)
                try:
                    ctx.close()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("context close for %s failed: %s", profile, exc)

            if self._browser is not None:
                try:
                    self._browser.close()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("browser close failed: %s", exc)
                self._browser = None
            if self._pw is not None:
                try:
                    self._pw.stop()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("playwright stop failed: %s", exc)
                self._pw = None
            if not already_closed:
                logger.debug("BrowserSession: shutdown complete")

    def _atexit_shutdown(self) -> None:
        """Process-exit safety net. Swallows every error — by the
        time atexit runs, the logger, socket, and even stderr may
        already be torn down."""
        try:
            self.shutdown()
        except Exception:  # noqa: BLE001
            pass

    # ── Profile / context management ──────────────────────────

    def _profile_lock(self, profile: str) -> threading.Lock:
        """Return the per-profile serialisation lock, creating on
        first access."""
        with self._context_map_lock:
            lock = self._profile_locks.get(profile)
            if lock is None:
                lock = threading.Lock()
                self._profile_locks[profile] = lock
            return lock

    def _file_lock(self, profile: str) -> threading.Lock:
        """Return the per-profile file-write lock. Protects
        ``_save_storage_state`` from concurrent writes on the
        same cookie file (shutdown vs. in-flight acquire)."""
        with self._context_map_lock:
            lock = self._file_locks.get(profile)
            if lock is None:
                lock = threading.Lock()
                self._file_locks[profile] = lock
            return lock

    def _get_or_create_context(
        self,
        profile: str,
        *,
        user_agent: str | None,
        viewport: dict[str, int] | None,
    ) -> Any:
        """Return the live context for *profile*, creating (and
        loading cookies from disk) on first use.

        Thread-safe across profiles: all reads/writes to
        ``self._contexts`` happen under ``_context_map_lock``, and
        a double-checked-locking pattern ensures exactly one
        context per profile even if two threads race past the
        fast path. Tests use ``__new__`` bypass + monkeypatch so
        this lock ordering stays test-friendly.
        """
        # Fast path — common case: context already exists.
        with self._context_map_lock:
            if self._closed:
                raise AdapterUnavailable(
                    "browser_session", "session is closed",
                )
            ctx = self._contexts.get(profile)
            if ctx is not None:
                return ctx

        # Slow path — launch browser + build context OUTSIDE the
        # map lock so the expensive I/O doesn't block other
        # profiles. Re-check under the lock before installing to
        # avoid "lost" contexts when two threads race.
        self._ensure_browser()
        ua = user_agent or pick_user_agent(seed=profile)
        vp = viewport or _DEFAULT_VIEWPORT
        storage_state = self._load_storage_state(profile)

        kwargs: dict[str, Any] = {
            "viewport": vp,
            "user_agent": ua,
            "locale": "en-US",
            "timezone_id": "UTC",
        }
        if storage_state is not None:
            kwargs["storage_state"] = storage_state

        new_ctx = self._browser.new_context(**kwargs)
        new_ctx.add_init_script(STEALTH_INIT_SCRIPT)

        with self._context_map_lock:
            if self._closed:
                # Shutdown happened while we were building.
                try:
                    new_ctx.close()
                except Exception:  # noqa: BLE001
                    pass
                raise AdapterUnavailable(
                    "browser_session", "session is closed",
                )
            existing = self._contexts.get(profile)
            if existing is not None:
                # Another thread beat us; discard our fresh ctx.
                try:
                    new_ctx.close()
                except Exception:  # noqa: BLE001
                    pass
                return existing
            self._contexts[profile] = new_ctx
            logger.debug(
                "BrowserSession: created context profile=%s ua=%s",
                profile, ua[:40],
            )
            return new_ctx

    def _cookie_file(self, profile: str) -> Path:
        """Disk path for a profile's cookie/storage state."""
        # Sanitise — profiles should already be safe but keep a
        # basic guard against path traversal.
        safe = "".join(
            c if c.isalnum() or c in ("-", "_") else "_" for c in profile
        )
        return self._cookie_dir / f"{safe}.json"

    def _load_storage_state(self, profile: str) -> dict[str, Any] | None:
        """Load cookies + localStorage for *profile* from disk, or
        return None if there's no saved state yet.

        A corrupted file (partial JSON, truncated write from a
        previous crash) is renamed to ``<name>.corrupt`` and
        treated as "no state" — so the next save writes a fresh
        file instead of silently losing auth cookies forever.
        """
        path = self._cookie_file(profile)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            logger.debug(
                "load_storage_state for %s: not a dict, quarantining",
                profile,
            )
        except json.JSONDecodeError as exc:
            logger.warning(
                "load_storage_state for %s: corrupt JSON, "
                "quarantining as .corrupt (%s)", profile, exc,
            )
        except OSError as exc:
            logger.debug("load_storage_state for %s failed: %s", profile, exc)
            return None
        # Quarantine the bad file so operators can inspect.
        try:
            path.rename(path.with_suffix(".json.corrupt"))
        except OSError as exc:
            logger.debug(
                "quarantine rename failed for %s: %s", profile, exc,
            )
        return None

    def _save_storage_state(self, profile: str, ctx: Any) -> None:
        """Dump cookies + localStorage for *profile* to disk.

        Atomic: writes to a temp file and ``os.replace``s onto the
        target so a crash mid-write never leaves a truncated
        cookie jar. Per-profile file lock blocks concurrent writes
        from shutdown vs. in-flight acquire.

        Called on shutdown and — cheaply — after each page acquire
        completes so a crash doesn't lose auth state.
        """
        try:
            state = ctx.storage_state()
        except Exception as exc:  # noqa: BLE001
            logger.debug("storage_state() for %s failed: %s", profile, exc)
            return
        path = self._cookie_file(profile)
        lock = self._file_lock(profile)
        with lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                # tempfile in same dir → os.replace is atomic on POSIX.
                fd, tmp_path = tempfile.mkstemp(
                    prefix=path.name + ".", suffix=".tmp",
                    dir=str(path.parent),
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(state, f)
                    os.replace(tmp_path, path)
                except Exception:
                    # Clean up temp on any failure so /tmp doesn't fill.
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    raise
            except OSError as exc:
                logger.debug(
                    "save_storage_state for %s failed: %s", profile, exc,
                )

    # ── Acquire page (main API) ───────────────────────────────

    @contextmanager
    def acquire_page(
        self,
        *,
        profile: str = "default",
        user_agent: str | None = None,
        viewport: dict[str, int] | None = None,
        timeout_ms: int = 30_000,
    ) -> Iterator[Any]:
        """Yield a Playwright ``page`` on *profile*'s context.

        The per-profile lock serialises concurrent calls against
        the same profile (Playwright's sync API is not thread-safe
        on one context). Calls against *different* profiles run
        in parallel.

        Cookies are persisted after each successful acquire so a
        crash loses at most the in-flight page.
        """
        if not _PLAYWRIGHT_AVAILABLE:
            raise AdapterUnavailable(
                "browser_session", "playwright not installed",
            )
        if self._closed:
            raise AdapterUnavailable(
                "browser_session", "session is closed",
            )

        lock = self._profile_lock(profile)
        with lock:
            ctx = self._get_or_create_context(
                profile, user_agent=user_agent, viewport=viewport,
            )
            page = ctx.new_page()
            page.set_default_timeout(timeout_ms)
            self._acquire_count += 1
            try:
                yield page
            finally:
                # Flush cookies FIRST so a concurrent
                # ``clear_profile`` (or an exception in page.close)
                # can't strand auth cookies set mid-redirect.
                try:
                    self._save_storage_state(profile, ctx)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("cookie flush failed: %s", exc)
                # Then close the page; keep context alive.
                try:
                    page.close()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("page close failed: %s", exc)

    def clear_profile(self, profile: str) -> None:
        """Drop *profile*'s context and delete its cookie file.

        Use when an operator explicitly wants a fresh session
        (e.g. after a captcha triggered and they want to retry
        from zero)."""
        with self._context_map_lock:
            ctx = self._contexts.pop(profile, None)
            self._profile_locks.pop(profile, None)
        if ctx is not None:
            try:
                ctx.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("clear context close failed: %s", exc)
        path = self._cookie_file(profile)
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            logger.debug("unlink cookie file %s failed: %s", path, exc)


__all__ = ["BrowserSession"]
