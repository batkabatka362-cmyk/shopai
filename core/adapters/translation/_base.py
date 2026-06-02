"""TranslationBaseAdapter — shared HTTP base for translators.

Concrete adapters (DeepL today; Google Translate, Lokalise,
LibreTranslate later) inherit this class and override only the
vendor-specific bits:

  * ``base_url``                   — vendor API root
  * ``config_alias``               — ``ENV_ALIASES`` key for the
                                     API credential
  * ``_translate_url``             — endpoint that returns the
                                     translated text
  * ``_auth_headers``              — vendor-specific auth header
  * ``_build_translate_payload``   — normalised params → vendor
                                     body
  * ``_parse_translate_response``  — vendor response → normalised
                                     result dict

The base handles:

  * Capability dispatch for ``Capability.TRANSLATE_TEXT``
  * Required-field validation (``text`` + ``target_lang``;
    ``source_lang`` optional and defaults to auto-detect)
  * Text length cap (50,000 chars — the router should chunk
    larger documents, not hand them to one vendor call)
  * HTTP POST execution with typed error mapping
  * AdapterResult assembly; ``cost_usd`` scales with the
    character count so the budget advisor sees per-character
    translation spend accurately

Normalised request shape (vendor-agnostic):

    {
        "text":         "Your order has shipped.",  # required
        "target_lang":  "de",                        # required, ISO 639-1
        "source_lang":  "en",                        # optional
        "formality":    "more",                      # optional
        "preserve_formatting": True,                 # optional
    }

Also accepts ``"text": ["sentence 1", "sentence 2"]`` for batch
translation. The response's ``translations`` list always
contains one entry per input segment regardless of whether the
caller passed a string or a list.

Normalised response shape:

    {
        "translations": [
            {
                "text":             "Ihre Bestellung wurde versandt.",
                "detected_source":  "en",
            },
            ...
        ],
        "target_lang":  "de",
        "characters":   24,         # billed chars for cost tracking
    }

Scope note: Wave 1 covers *text translation* only. Document
translation (PDF, DOCX uploads), glossary management, and
translation memory are out of scope.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from ..base import (
    AdapterCategory,
    AdapterResult,
    BaseAdapter,
    Capability,
)
from ..config import get_config
from ..errors import (
    AdapterAuthError,
    AdapterError,
    AdapterNotConfigured,
    AdapterQuotaExhausted,
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUnavailable,
    AdapterValidationError,
)

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False

logger = get_logger("adapters.translation")


_DEFAULT_TIMEOUT = 30.0
_MAX_TEXT_CHARS = 50_000
_MAX_BATCH_SEGMENTS = 50


class TranslationBaseAdapter(BaseAdapter):
    """Abstract base for every translation adapter.

    Concrete adapters MUST set:

      * ``name``         — registry key (e.g. ``"deepl"``)
      * ``base_url``     — vendor API root (may be dynamic —
                           override as a ``@property``)
      * ``config_alias`` — env alias for the API key

    They MAY override:

      * ``priority``      — router preference (0-100)
      * ``cost_per_char`` — $/char (DeepL paid API is ~$25 per
                            1M characters → 0.000025/char)
      * ``timeout``       — per-request timeout in seconds
    """

    category = AdapterCategory.TRANSLATION
    capabilities = {Capability.TRANSLATE_TEXT}

    base_url: str = ""
    config_alias: str = ""
    timeout: float = _DEFAULT_TIMEOUT

    cost_per_call: float = 0.0
    cost_per_char: float = 0.0
    priority: int = 50

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            return False
        if not self.config_alias:
            return False
        return bool(get_config().get(self.config_alias))

    def _api_key(self) -> str:
        key = get_config().get(self.config_alias)
        if not key:
            env = get_config().env_var_for(self.config_alias)
            raise AdapterNotConfigured(
                self.name,
                f"missing API key (set ${env or self.config_alias})",
            )
        return key

    # ── Cost estimation ────────────────────────────────────────

    def estimate_cost(
        self, capability: Capability, params: dict[str, Any],
    ) -> float:
        """Cost scales with the number of billed characters.
        Subclasses with flat or tiered pricing override this."""
        text = params.get("text", "")
        chars = self._count_chars(text)
        return float(self.cost_per_call) + (
            float(self.cost_per_char) * chars
        )

    @staticmethod
    def _count_chars(text: Any) -> int:
        if isinstance(text, str):
            return len(text)
        if isinstance(text, (list, tuple)):
            return sum(len(t) for t in text if isinstance(t, str))
        return 0

    # ── Capability dispatch ────────────────────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        if capability != Capability.TRANSLATE_TEXT:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        self._validate_translate(params)
        url = self._translate_url()
        body = self._build_translate_payload(params)
        raw = self._http_post(url, body, headers=self._auth_headers())
        normalised = self._parse_translate_response(raw, params)

        chars = int(normalised.get("characters") or self._count_chars(
            params.get("text", ""),
        ))
        cost = float(self.cost_per_call) + (
            float(self.cost_per_char) * chars
        )

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data=normalised,
            cost_usd=cost,
            raw=raw,
        )

    # ── Validation ─────────────────────────────────────────────

    def _validate_translate(self, params: dict[str, Any]) -> None:
        text = params.get("text")
        if text is None:
            raise AdapterValidationError(
                self.name, "'text' is required for translate_text",
            )

        if isinstance(text, str):
            if not text.strip():
                raise AdapterValidationError(
                    self.name, "'text' must be non-empty",
                )
            if len(text) > _MAX_TEXT_CHARS:
                raise AdapterValidationError(
                    self.name,
                    f"'text' too long ({len(text)} chars; "
                    f"max {_MAX_TEXT_CHARS})",
                )
        elif isinstance(text, (list, tuple)):
            if not text:
                raise AdapterValidationError(
                    self.name, "'text' list must be non-empty",
                )
            if len(text) > _MAX_BATCH_SEGMENTS:
                raise AdapterValidationError(
                    self.name,
                    f"'text' batch too large ({len(text)} segments; "
                    f"max {_MAX_BATCH_SEGMENTS})",
                )
            total = 0
            for i, seg in enumerate(text):
                if not isinstance(seg, str):
                    raise AdapterValidationError(
                        self.name,
                        f"'text[{i}]' must be a string, got "
                        f"{type(seg).__name__}",
                    )
                total += len(seg)
            if total > _MAX_TEXT_CHARS:
                raise AdapterValidationError(
                    self.name,
                    f"'text' batch too long ({total} chars; "
                    f"max {_MAX_TEXT_CHARS})",
                )
        else:
            raise AdapterValidationError(
                self.name,
                f"'text' must be string or list of strings, got "
                f"{type(text).__name__}",
            )

        target_lang = params.get("target_lang")
        if not target_lang or not isinstance(target_lang, str):
            raise AdapterValidationError(
                self.name,
                "'target_lang' is required (ISO 639-1 code like 'en')",
            )
        # Accept 2-5 chars to cover regional variants (e.g. "en-GB").
        if len(target_lang) < 2 or len(target_lang) > 5:
            raise AdapterValidationError(
                self.name,
                f"'target_lang' must be 2-5 chars, got {target_lang!r}",
            )

        source_lang = params.get("source_lang")
        if source_lang is not None:
            if not isinstance(source_lang, str):
                raise AdapterValidationError(
                    self.name,
                    f"'source_lang' must be a string, got "
                    f"{type(source_lang).__name__}",
                )
            if len(source_lang) < 2 or len(source_lang) > 5:
                raise AdapterValidationError(
                    self.name,
                    f"'source_lang' must be 2-5 chars, "
                    f"got {source_lang!r}",
                )

    # ── Vendor-specific hooks (override in subclasses) ────────

    def _translate_url(self) -> str:
        raise NotImplementedError(
            f"{type(self).__name__}._translate_url must be implemented",
        )

    def _auth_headers(self) -> dict[str, str]:
        """Default: Bearer token. Override when the vendor uses
        a different scheme (DeepL uses ``DeepL-Auth-Key``)."""
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _build_translate_payload(
        self, params: dict[str, Any],
    ) -> Any:
        raise NotImplementedError(
            f"{type(self).__name__}._build_translate_payload must be implemented",
        )

    def _parse_translate_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"{type(self).__name__}._parse_translate_response must be implemented",
        )

    # ── HTTP ───────────────────────────────────────────────────

    def _http_post(
        self,
        url: str,
        body: Any,
        headers: dict[str, str],
        *,
        max_retries: int = 3,
    ) -> Any:
        """W962-65: inline retry preserving DeepL's 456 quota-
        exhausted status code (which the shared helper doesn't
        know about). Mirrors core/adapters/_http_retry.py."""
        if not _REQUESTS_AVAILABLE:
            raise AdapterUnavailable(
                self.name, "'requests' library not installed",
            )
        import time as _t
        form_encoded = (
            headers.get("Content-Type")
            == "application/x-www-form-urlencoded"
        )
        last_exc: Exception | None = None
        for attempt in range(1, max(1, max_retries) + 1):
            try:
                if form_encoded:
                    response = _requests.post(
                        url, data=body, headers=headers,
                        timeout=self.timeout,
                    )
                else:
                    response = _requests.post(
                        url, json=body, headers=headers,
                        timeout=self.timeout,
                    )
            except _requests.Timeout as exc:  # type: ignore[union-attr]
                last_exc = exc
                if attempt < max_retries:
                    _t.sleep(min(2 ** attempt, 8))
                    continue
                raise AdapterTimeout(
                    self.name, f"timeout after {self.timeout}s: {exc}",
                ) from exc
            except _requests.ConnectionError as exc:  # type: ignore[union-attr]
                last_exc = exc
                if attempt < max_retries:
                    _t.sleep(min(2 ** attempt, 8))
                    continue
                raise AdapterUnavailable(
                    self.name, f"connection error: {exc}",
                ) from exc
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                msg = str(exc).lower()
                if any(s in msg for s in (
                    "chunkedencoding", "ssl", "protocol",
                    "remote disconnected",
                )) and attempt < max_retries:
                    _t.sleep(min(2 ** attempt, 8))
                    continue
                raise AdapterError(
                    self.name,
                    f"http post failed: {type(exc).__name__}: {exc}",
                ) from exc

            status = getattr(response, "status_code", 0)
            if status >= 400:
                snippet = (getattr(response, "text", "") or "")[:200]
                if status in (401, 403):
                    raise AdapterAuthError(
                        self.name,
                        f"vendor rejected credentials ({status}): {snippet}",
                    )
                if status == 429:
                    retry_after = response.headers.get(
                        "Retry-After", "1",
                    )
                    try:
                        wait = float(retry_after)
                    except (TypeError, ValueError):
                        wait = 1.0
                    if attempt < max_retries:
                        _t.sleep(min(wait, 30))
                        continue
                    raise AdapterRateLimited(
                        self.name, f"rate limit (429): {snippet}",
                    )
                if status == 456:
                    # DeepL: quota-exhausted -- not retryable
                    raise AdapterQuotaExhausted(
                        self.name,
                        f"monthly character quota exhausted: {snippet}",
                    )
                if 500 <= status < 600:
                    if attempt < max_retries:
                        _t.sleep(min(2 ** attempt, 8))
                        continue
                    raise AdapterUnavailable(
                        self.name,
                        f"vendor 5xx ({status}): {snippet}",
                    )
                raise AdapterError(
                    self.name,
                    f"vendor returned {status}: {snippet}",
                )
            # 2xx success: fall out of the retry loop
            break
        else:
            raise AdapterError(
                self.name,
                f"exhausted retries: {last_exc}" if last_exc else "exhausted retries",
            )

        try:
            text = getattr(response, "text", "") or ""
            return response.json() if text else {}
        except ValueError as exc:
            raise AdapterError(
                self.name, f"invalid JSON response: {exc}",
            ) from exc
