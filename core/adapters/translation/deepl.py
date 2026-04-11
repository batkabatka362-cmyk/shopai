"""DeepL translation adapter.

DeepL is Wave 1's primary translator. It produces noticeably
better e-commerce copy than Google Translate and has a generous
free tier (500 000 characters/month) that covers small-to-mid
shops for free.

Two hosts, one env var
----------------------
DeepL splits its API into two hosts:

    * ``api-free.deepl.com``  — free tier
    * ``api.deepl.com``       — paid tier

The only way to tell them apart is the key suffix: free keys
end in ``:fx``. Operators should not have to set a second env
var just to pick the right host, so we auto-detect from the key
and expose the chosen host via the ``base_url`` property. The
side-effect is that key rotation from free → paid works
transparently on the next request.

Auth: ``Authorization: DeepL-Auth-Key <key>``.

Payload: DeepL's ``/v2/translate`` endpoint accepts both JSON
and form-encoded bodies. We use form-encoded because DeepL's
quirky "repeat the key" batch syntax (``text=foo&text=bar``) is
simpler to build with ``requests``' list-valued form dict than
with JSON.

Cost: paid DeepL is ~$25/1M characters → 0.000025 per char.
"""
from __future__ import annotations

from typing import Any

from ..errors import AdapterError
from ._base import TranslationBaseAdapter


class DeepLAdapter(TranslationBaseAdapter):
    """DeepL — high-quality text translation."""

    name = "deepl"
    config_alias = "deepl"
    priority = 80

    # DeepL paid pricing: $25 per 1M characters. Free tier is
    # $0 until the monthly quota runs out, but we still report
    # the paid rate so the budget advisor's forecast is
    # conservative.
    cost_per_call: float = 0.0
    cost_per_char: float = 0.000025

    timeout: float = 30.0

    # Hosts. Keep both as class-level constants so tests can
    # monkeypatch them if needed.
    _HOST_FREE = "https://api-free.deepl.com"
    _HOST_PAID = "https://api.deepl.com"

    # DeepL ignores unknown formality values on models that
    # don't support them, but it raises on outright-invalid
    # strings. Constrain to the documented set.
    _VALID_FORMALITY = {
        "default",
        "more",
        "less",
        "prefer_more",
        "prefer_less",
    }

    # ── Host selection ────────────────────────────────────────

    @property
    def base_url(self) -> str:  # type: ignore[override]
        """Auto-pick free vs paid host from the key suffix.

        DeepL's contract: free-tier keys end in ``:fx``; paid
        keys do not. We fall back to the paid host when the
        adapter isn't configured so calls still produce a
        deterministic URL in error messages / tests.
        """
        try:
            key = self._api_key()
        except Exception:  # noqa: BLE001
            return self._HOST_PAID
        if key.endswith(":fx"):
            return self._HOST_FREE
        return self._HOST_PAID

    # ── URL + auth ────────────────────────────────────────────

    def _translate_url(self) -> str:
        return f"{self.base_url}/v2/translate"

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"DeepL-Auth-Key {self._api_key()}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

    # ── Payload ───────────────────────────────────────────────

    def _build_translate_payload(
        self, params: dict[str, Any],
    ) -> list[tuple[str, str]]:
        """Build DeepL's form-encoded body.

        DeepL's batch syntax repeats the ``text`` key, which the
        ``requests`` library encodes correctly when we pass a
        list of ``(key, value)`` tuples. Using a dict would
        collapse duplicate keys.
        """
        text = params.get("text", "")
        if isinstance(text, str):
            segments = [text]
        else:
            segments = [str(t) for t in text]

        body: list[tuple[str, str]] = [
            ("text", seg) for seg in segments
        ]

        # DeepL requires uppercase language codes (e.g. "DE",
        # "EN-GB"). Regional variants stay as-is after upper().
        target_lang = str(params["target_lang"]).upper()
        body.append(("target_lang", target_lang))

        source_lang = params.get("source_lang")
        if source_lang:
            body.append(("source_lang", str(source_lang).upper()))

        formality = params.get("formality")
        if formality:
            formality_str = str(formality).lower()
            if formality_str in self._VALID_FORMALITY:
                body.append(("formality", formality_str))

        preserve = params.get("preserve_formatting")
        if preserve is not None:
            body.append(
                ("preserve_formatting", "1" if preserve else "0"),
            )

        split_sentences = params.get("split_sentences")
        if split_sentences is not None:
            # DeepL accepts "0", "1", or "nonewlines".
            body.append(("split_sentences", str(split_sentences)))

        tag_handling = params.get("tag_handling")
        if tag_handling:
            body.append(("tag_handling", str(tag_handling)))

        return body

    # ── Response ──────────────────────────────────────────────

    def _parse_translate_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                f"unexpected DeepL response type: {type(raw).__name__}",
            )

        translations_raw = raw.get("translations")
        if not isinstance(translations_raw, list):
            raise AdapterError(
                self.name,
                "DeepL response missing 'translations' list",
            )

        translations: list[dict[str, Any]] = []
        total_chars = 0
        for entry in translations_raw:
            if not isinstance(entry, dict):
                continue
            text = entry.get("text", "") or ""
            detected = (
                entry.get("detected_source_language")
                or entry.get("detected_source")
                or ""
            )
            translations.append(
                {
                    "text": text,
                    "detected_source": (
                        str(detected).lower() if detected else ""
                    ),
                },
            )
            total_chars += len(text) if isinstance(text, str) else 0

        target_lang = str(params.get("target_lang", "")).lower()

        # Prefer billed characters from the *input* text — DeepL
        # bills by input length, not output length.
        input_chars = self._count_chars(params.get("text", ""))

        return {
            "translations": translations,
            "target_lang": target_lang,
            "characters": input_chars or total_chars,
        }
