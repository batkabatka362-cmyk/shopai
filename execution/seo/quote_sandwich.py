"""Quote-sandwich formatter — Princeton GEO pattern.

Wave E-2 of IMPLEMENTATION_PLAN_2026. Research from Princeton's
"Generative Engine Optimization" (Nov 2024, updated 2026) showed
that claims bracketed by an authoritative quote + follow-up
citation get cited by LLMs (ChatGPT, Perplexity, Gemini) at
roughly +40% vs. the bare claim. The mechanism is attention-
window: an LLM ranking passages for retrieval scores the
sandwich higher because the surrounding quote provides
"quotability signal" — a verbatim chunk with an attribution
hook the LLM can point at.

This module ships the pattern as a pure formatter. Callers
pick the attribution they want (expert quote, research
citation, reviewer testimonial) and get back an HTML fragment
that slots into a product description ``body_html`` or
``schema:description``.

Single public entry point:

    from execution.seo.quote_sandwich import wrap_claim

    html = wrap_claim(
        claim="Slow-feeder bowls cut bloat incidence by 40%.",
        quote=(
            "Dogs that eat from slow-feeder bowls ingest food "
            "over 5× longer, reducing the pathway to GDV."
        ),
        source_name="Dr. Elena Martinez, DVM",
        citation="American Veterinary Medical Association, 2024",
        source_type="expert",
    )

Returns an HTML fragment that reads naturally, carries the
quote + attribution + follow-up citation, and is safe to
embed in Shopify ``body_html``. No LLM call — string
templating only.

Pure stdlib + html.escape. Thread-safe (no state).
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Any


_ALLOWED_SOURCE_TYPES = frozenset({
    "expert",
    "research",
    "reviewer",
    "generic",
})


@dataclass
class Sandwich:
    """Structured quote-sandwich payload.

    Separates the three parts so callers can inspect before
    rendering (e.g. to add their own formatting, snippet
    markers, or structured-data triples).
    """

    claim: str
    quote: str
    source_name: str
    source_type: str
    citation: str = ""
    citation_url: str = ""
    _html_fragment: str = field(default="", repr=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "quote": self.quote,
            "source_name": self.source_name,
            "source_type": self.source_type,
            "citation": self.citation,
            "citation_url": self.citation_url,
            "html": self._html_fragment,
        }


def _normalize_source_type(raw: str) -> str:
    s = (raw or "").strip().lower()
    if s not in _ALLOWED_SOURCE_TYPES:
        return "generic"
    return s


def _lead_in(source_type: str, source_name: str) -> str:
    """Choose the lead-in verb that precedes the quote.
    Expert/research quotes use factual verbs; reviewer
    testimonials lean more colloquial."""
    if not source_name:
        source_name = "industry research"
    if source_type == "expert":
        return f"According to {source_name}:"
    if source_type == "research":
        return f"Research from {source_name} finds:"
    if source_type == "reviewer":
        return f"As one customer put it:"
    return f"{source_name} notes:"


def _citation_fragment(
    citation: str, citation_url: str,
) -> str:
    if not citation:
        return ""
    safe_text = html.escape(citation)
    if citation_url:
        safe_url = html.escape(
            citation_url, quote=True,
        )
        return (
            f'<cite><a href="{safe_url}" '
            'rel="nofollow">'
            f'{safe_text}</a></cite>'
        )
    return f"<cite>{safe_text}</cite>"


def wrap_claim(
    *,
    claim: str,
    quote: str,
    source_name: str = "",
    source_type: str = "expert",
    citation: str = "",
    citation_url: str = "",
) -> Sandwich:
    """Wrap ``claim`` in a Princeton-style quote sandwich.

    Returns a :class:`Sandwich` — the ``.html`` attribute (via
    :meth:`as_dict`) holds the ready-to-embed fragment; the
    other fields are inspectable for callers that want to
    render differently (markdown, JSON-LD description, llms.txt).

    Raises:
      ValueError: if ``claim`` or ``quote`` is empty.
    """
    if not claim or not claim.strip():
        raise ValueError("claim must be non-empty")
    if not quote or not quote.strip():
        raise ValueError("quote must be non-empty")
    claim = claim.strip()
    quote = quote.strip()
    source_name = (source_name or "").strip()
    source_type = _normalize_source_type(source_type)
    citation = (citation or "").strip()
    citation_url = (citation_url or "").strip()

    lead = _lead_in(source_type, source_name)
    # Open + close quotation marks — curly for nicer rendering
    quote_html = (
        f"“{html.escape(quote)}”"
    )
    claim_html = html.escape(claim)
    cite = _citation_fragment(citation, citation_url)

    parts: list[str] = []
    parts.append(
        f'<blockquote class="shopai-quote-sandwich">'
        f'<p>{html.escape(lead)} {quote_html}</p>'
        f'</blockquote>'
    )
    parts.append(f'<p>{claim_html}</p>')
    if cite:
        parts.append(
            f'<p class="shopai-citation">{cite}</p>',
        )
    fragment = "".join(parts)
    return Sandwich(
        claim=claim,
        quote=quote,
        source_name=source_name,
        source_type=source_type,
        citation=citation,
        citation_url=citation_url,
        _html_fragment=fragment,
    )


def wrap_many(
    claims: list[dict[str, Any]],
) -> list[Sandwich]:
    """Convenience: wrap a batch of claim dicts in one call.
    Each dict accepts the same kwargs as :func:`wrap_claim`.
    Malformed entries are skipped (no partial state)."""
    out: list[Sandwich] = []
    for raw in claims or []:
        if not isinstance(raw, dict):
            continue
        try:
            out.append(wrap_claim(**raw))
        except (TypeError, ValueError):
            continue
    return out
