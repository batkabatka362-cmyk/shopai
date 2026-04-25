"""BrandGuard — deterministic style-guide enforcer.

Every piece of content the AI ships (ad copy, email body,
blog post, product description) passes through this guard
before leaving the building. Rule-based, not LLM — §4a 95/5:
voice drift is a pure string check, no reason to burn a
token on it.

Surfaces + default rules:

  * ``ad_copy``         — max 300 chars, 0-2 exclamation marks,
                          no ALL-CAPS WORDS of 4+ chars,
                          forbidden words denied
  * ``email_subject``   — max 60 chars, 0 exclamation marks
  * ``email_body``      — max 3 exclamation marks, forbidden
                          words denied, required tagline soft
  * ``product_desc``    — min 40 chars (too short looks
                          placeholder), forbidden words denied
  * ``blog_article``    — min 200 chars, forbidden words,
                          caps rule
  * ``social_post``     — max 280 chars, 0-2 exclamation marks

Brand authors define:
  * ``voice``          — "calm_cozy" / "bold_energetic" /
                         "minimal_clinical" / custom string
  * ``forbidden_words``— deny list; case-insensitive
  * ``required_words`` — list that must appear somewhere
                         (soft — produces a warning, not a
                         fail, since "must appear in every
                         email body" is a heuristic, not law)
  * ``tagline``        — brand signoff; required_words for
                         email_body by default

Severity buckets:
  * ``error``   — content fails; caller must reject
  * ``warning`` — content passes with flag; log + ship

``BrandCheck.passed`` is True iff zero errors. Warnings
populate the ``issues`` list but don't block.
"""
from __future__ import annotations

import dataclasses
import re
from typing import Any, Iterable


# ── Constants ──────────────────────────────────────────────


_SURFACES = {
    "ad_copy", "email_subject", "email_body",
    "product_desc", "blog_article", "social_post",
}


# Per-surface structural caps. Overridable via BrandRules.
_DEFAULT_SURFACE_RULES: dict[str, dict[str, Any]] = {
    "ad_copy": {
        "max_chars": 300,
        "max_exclamations": 2,
        "no_allcaps_words": True,
    },
    "email_subject": {
        "max_chars": 60,
        "max_exclamations": 0,
        "no_allcaps_words": True,
    },
    "email_body": {
        "max_exclamations": 3,
        "require_tagline": True,
    },
    "product_desc": {
        "min_chars": 40,
    },
    "blog_article": {
        "min_chars": 200,
        "no_allcaps_words": True,
    },
    "social_post": {
        "max_chars": 280,
        "max_exclamations": 2,
    },
}


# Voice-specific hype words that read as spam in "calm" brands
# but are fine in "bold" ones. Checked only when voice is a
# low-energy preset.
_LOW_ENERGY_VOICES = {"calm", "calm_cozy", "minimal", "minimal_clinical"}
_HYPE_WORDS = frozenset({
    "crazy", "insane", "unbelievable", "shocking",
    "mind-blowing", "mindblowing", "rush", "hurry",
})


_ALLCAPS_WORD_RE = re.compile(r"\b[A-Z]{4,}\b")
_EXCLAMATION_RE = re.compile(r"!")


@dataclasses.dataclass(frozen=True)
class BrandIssue:
    """A single rule violation."""
    code: str          # e.g. "max_chars", "forbidden_word"
    severity: str      # "error" | "warning"
    reason: str
    context: str = ""  # excerpt showing the offender


@dataclasses.dataclass(frozen=True)
class BrandCheck:
    """Result of running BrandGuard.check_content()."""
    surface: str
    text_length: int
    passed: bool       # True iff zero errors
    issues: tuple[BrandIssue, ...]

    @property
    def errors(self) -> tuple[BrandIssue, ...]:
        return tuple(
            i for i in self.issues if i.severity == "error"
        )

    @property
    def warnings(self) -> tuple[BrandIssue, ...]:
        return tuple(
            i for i in self.issues if i.severity == "warning"
        )


@dataclasses.dataclass
class BrandRules:
    """Loaded brand ruleset. Usually built via
    ``BrandGuard.from_metafields`` but constructible directly
    for tests."""
    voice: str = "neutral"
    forbidden_words: frozenset[str] = dataclasses.field(
        default_factory=frozenset,
    )
    required_words: frozenset[str] = dataclasses.field(
        default_factory=frozenset,
    )
    tagline: str = ""
    # Optional per-surface override — dict[surface_name ->
    # dict of overrides to merge onto _DEFAULT_SURFACE_RULES].
    surface_overrides: dict[str, dict[str, Any]] = (
        dataclasses.field(default_factory=dict)
    )


class BrandGuard:
    """Stateless rule enforcer. Build one per session from
    the live brand metafields; hold it for the session's
    lifetime (brand rules rarely change mid-session)."""

    def __init__(self, rules: BrandRules) -> None:
        self._rules = rules

    @classmethod
    def from_metafields(
        cls, metafields: Iterable[dict[str, Any]] | None,
    ) -> "BrandGuard":
        """Parse the ``shopai.brand`` + ``shopai.seo_defaults``
        metafields (as stored by store_configurator._setup_brand)
        into a BrandRules. Accepts the list shape Shopify
        returns from ``metafields.json`` directly."""
        voice = "neutral"
        forbidden: set[str] = set()
        required: set[str] = set()
        tagline = ""
        overrides: dict[str, dict[str, Any]] = {}
        for mf in metafields or ():
            if not isinstance(mf, dict):
                continue
            ns = str(mf.get("namespace") or "")
            key = str(mf.get("key") or "")
            value_raw = mf.get("value")
            if ns != "shopai" or key != "brand":
                continue
            parsed = _parse_value(value_raw)
            if not isinstance(parsed, dict):
                continue
            voice = str(parsed.get("voice") or voice).lower()
            tagline = str(parsed.get("tagline") or tagline)
            forbidden = _as_str_set(parsed.get("forbidden_words"))
            required = _as_str_set(parsed.get("required_words"))
            ov = parsed.get("surface_overrides")
            if isinstance(ov, dict):
                for k, v in ov.items():
                    if isinstance(v, dict):
                        overrides[str(k)] = v
        return cls(BrandRules(
            voice=voice,
            forbidden_words=frozenset(
                w.lower() for w in forbidden
            ),
            required_words=frozenset(
                w.lower() for w in required
            ),
            tagline=tagline,
            surface_overrides=overrides,
        ))

    # ── Public check ──────────────────────────────────

    def check_content(
        self, text: str, *, surface: str,
    ) -> BrandCheck:
        """Run all applicable rules. Returns a BrandCheck —
        ``passed`` is False iff any error-severity issue
        fired."""
        if surface not in _SURFACES:
            raise ValueError(
                f"surface must be one of {sorted(_SURFACES)} "
                f"(got {surface!r})",
            )
        body = str(text or "")
        issues: list[BrandIssue] = []

        surface_rules = dict(_DEFAULT_SURFACE_RULES.get(surface, {}))
        surface_rules.update(
            self._rules.surface_overrides.get(surface, {}),
        )

        max_chars = surface_rules.get("max_chars")
        min_chars = surface_rules.get("min_chars")
        max_excl = surface_rules.get("max_exclamations")
        no_caps = surface_rules.get("no_allcaps_words", False)
        require_tagline = surface_rules.get(
            "require_tagline", False,
        )

        if max_chars is not None and len(body) > int(max_chars):
            issues.append(BrandIssue(
                code="max_chars",
                severity="error",
                reason=(
                    f"{surface} exceeds {max_chars} chars "
                    f"(got {len(body)})"
                ),
                context=body[-40:],
            ))
        if min_chars is not None and len(body) < int(min_chars):
            issues.append(BrandIssue(
                code="min_chars",
                severity="error",
                reason=(
                    f"{surface} under {min_chars} chars "
                    f"(got {len(body)}) — reads as placeholder"
                ),
            ))

        if max_excl is not None:
            count = len(_EXCLAMATION_RE.findall(body))
            if count > int(max_excl):
                issues.append(BrandIssue(
                    code="max_exclamations",
                    severity="error",
                    reason=(
                        f"{count} exclamation marks exceeds "
                        f"cap {max_excl}"
                    ),
                ))

        if no_caps:
            hits = _ALLCAPS_WORD_RE.findall(body)
            if hits:
                issues.append(BrandIssue(
                    code="allcaps_word",
                    severity="error",
                    reason=(
                        "ALL-CAPS words read as shouting: "
                        + ", ".join(hits[:3])
                    ),
                    context=", ".join(hits[:5]),
                ))

        # Forbidden words — case-insensitive word-boundary check.
        if self._rules.forbidden_words:
            lower = body.lower()
            for word in self._rules.forbidden_words:
                if not word:
                    continue
                pattern = re.compile(
                    rf"\b{re.escape(word)}\b",
                )
                if pattern.search(lower):
                    issues.append(BrandIssue(
                        code="forbidden_word",
                        severity="error",
                        reason=f"'{word}' is on the deny list",
                        context=word,
                    ))

        # Low-energy voice ↔ hype-word mismatch.
        if self._rules.voice in _LOW_ENERGY_VOICES:
            lower = body.lower()
            for hype in _HYPE_WORDS:
                if re.search(rf"\b{re.escape(hype)}\b", lower):
                    issues.append(BrandIssue(
                        code="voice_mismatch",
                        severity="error",
                        reason=(
                            f"'{hype}' reads as hype — "
                            f"brand voice is "
                            f"'{self._rules.voice}'"
                        ),
                    ))

        # Required tagline — warning when absent from an
        # email_body if the rule is enabled AND a tagline is
        # set on the brand. Tagline required but missing
        # doesn't fail the check — brand pages without
        # taglines should still ship.
        if (
            require_tagline
            and self._rules.tagline
            and (
                self._rules.tagline.lower() not in body.lower()
            )
        ):
            issues.append(BrandIssue(
                code="missing_tagline",
                severity="warning",
                reason=(
                    f"tagline '{self._rules.tagline}' not "
                    "present — email footer may look off-brand"
                ),
            ))

        # Required words — warning-level: the brand wants
        # these to appear (e.g. "wellness", "cozy") but we
        # don't hard-fail since they're a guideline.
        if self._rules.required_words:
            lower = body.lower()
            missing = [
                w for w in self._rules.required_words
                if w not in lower
            ]
            if missing and len(missing) == len(
                self._rules.required_words,
            ):
                # None of the required words present — stronger
                # signal that this content is off-brand.
                issues.append(BrandIssue(
                    code="missing_required_words",
                    severity="warning",
                    reason=(
                        "none of the required words present: "
                        + ", ".join(sorted(missing)[:5])
                    ),
                ))

        errors = [i for i in issues if i.severity == "error"]
        return BrandCheck(
            surface=surface,
            text_length=len(body),
            passed=(len(errors) == 0),
            issues=tuple(issues),
        )


# ── Helpers ───────────────────────────────────────────


def _parse_value(raw: Any) -> Any:
    """Shopify metafields store JSON as a string. Try json
    first; fall back to the raw value if it's already a
    dict (tests / in-memory use)."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        import json
        try:
            return json.loads(raw)
        except ValueError:
            return {}
    return {}


def _as_str_set(value: Any) -> set[str]:
    if isinstance(value, list):
        return {
            str(v).strip().lower()
            for v in value
            if v
        }
    if isinstance(value, str):
        # Allow comma-separated convenience.
        return {
            p.strip().lower()
            for p in value.split(",") if p.strip()
        }
    return set()
