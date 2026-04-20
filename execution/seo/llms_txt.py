"""llms.txt + markdown-mirror generators for AI crawlers.

Wave E-1 of IMPLEMENTATION_PLAN_2026. Anthropic, Perplexity and
OpenAI crawlers honor ``/llms.txt`` (short index) and
``/llms-full.txt`` (full content) when deciding what to include
in LLM training + live retrieval. Google explicitly says it is
NOT a ranking signal, but for agentic shopping channels and
citation rates this is a free lift.

Additionally we emit **markdown mirrors** — one ``.md`` file per
product at ``/products/{slug}.md`` — because LLM crawlers
ingest markdown more cleanly than the HTML theme layer.

Pure stdlib. Deterministic given the product list.

Sources:
  * llmstxt.org
  * predictadigital.com.au/blog/llms-txt-mcp-schema-geo-2026
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMTxtIndex:
    """Result of building ``llms.txt``."""
    store_name: str
    store_url: str
    short_txt: str
    full_txt: str
    product_mirrors: tuple[tuple[str, str], ...]  # (path, body)

    def as_dict(self) -> dict[str, Any]:
        return {
            "store_name": self.store_name,
            "store_url": self.store_url,
            "short_txt_chars": len(self.short_txt),
            "full_txt_chars": len(self.full_txt),
            "mirror_count": len(self.product_mirrors),
        }


def _truncate_sentence(text: str, max_chars: int) -> str:
    if not text:
        return ""
    clean = " ".join(str(text).split())
    if len(clean) <= max_chars:
        return clean
    cut = clean[:max_chars]
    last_period = cut.rfind(".")
    if last_period >= int(max_chars * 0.5):
        return cut[:last_period + 1]
    return cut.rsplit(" ", 1)[0] + "…"


def build_markdown_mirror(
    product: dict[str, Any],
    *,
    store_url: str,
) -> tuple[str, str]:
    """Return (relative_path, body) for a single product's
    markdown mirror. LLM crawlers prefer this over HTML."""
    handle = str(
        product.get("handle")
        or product.get("slug")
        or product.get("title", ""),
    ).lower().replace(" ", "-")
    title = str(product.get("title", "Product"))
    price = product.get("price")
    description = str(product.get("description", "")).strip()
    url = (
        f"{store_url.rstrip('/')}/products/{handle}"
        if store_url else handle
    )
    lines = [f"# {title}", ""]
    if price is not None:
        lines.append(f"Price: ${float(price):.2f}")
        lines.append("")
    lines.append(f"Canonical URL: {url}")
    lines.append("")
    if description:
        lines.append("## Overview")
        lines.append("")
        lines.append(description)
        lines.append("")
    faqs = product.get("faqs") or []
    if faqs:
        lines.append("## FAQ")
        lines.append("")
        for q in faqs:
            question = str(q.get("q", "")).strip()
            answer = str(q.get("a", "")).strip()
            if question and answer:
                lines.append(f"**Q: {question}**")
                lines.append(f"A: {answer}")
                lines.append("")
    highlights = product.get("highlights") or []
    if highlights:
        lines.append("## Highlights")
        lines.append("")
        for h in highlights:
            lines.append(f"- {str(h).strip()}")
        lines.append("")
    return f"products/{handle}.md", "\n".join(lines)


def build_llms_txt(
    *,
    store_name: str,
    store_url: str,
    products: list[dict[str, Any]],
    summary: str = "",
    include_full: bool = True,
) -> LLMTxtIndex:
    """Build ``llms.txt`` (short index), ``llms-full.txt`` (full
    product summaries) and one ``.md`` mirror per product.

    Short txt follows llmstxt.org convention: H1 title, blockquote
    summary, H2 sections with title + URL + 30-50 word blurb.
    """
    if not store_name:
        raise ValueError("store_name required")
    store_url = (store_url or "").rstrip("/")

    # Build mirrors first — we reference them from llms.txt
    mirrors: list[tuple[str, str]] = []
    full_lines: list[str] = []
    for p in products or []:
        path, body = build_markdown_mirror(
            p, store_url=store_url,
        )
        mirrors.append((path, body))
        if include_full:
            full_lines.append(body)
            full_lines.append("")
            full_lines.append("---")
            full_lines.append("")

    # llms.txt
    short: list[str] = []
    short.append(f"# {store_name}")
    short.append("")
    if summary:
        short.append(f"> {summary}")
        short.append("")
    short.append(f"Canonical: {store_url}")
    short.append("")
    short.append("## Products")
    short.append("")
    for p in products or []:
        title = str(p.get("title", "Product"))
        handle = str(
            p.get("handle")
            or p.get("title", ""),
        ).lower().replace(" ", "-")
        product_url = (
            f"{store_url}/products/{handle}"
            if store_url else handle
        )
        blurb = _truncate_sentence(
            str(p.get("description", "")), 180,
        )
        short.append(
            f"- [{title}]({product_url}) — {blurb}"
            if blurb else f"- [{title}]({product_url})"
        )
    short.append("")
    short.append("## Policies")
    short.append("")
    short.append(
        f"- [Privacy]({store_url}/policies/privacy-policy)"
    )
    short.append(
        f"- [Returns]({store_url}/policies/refund-policy)"
    )
    short.append(
        f"- [Shipping]({store_url}/policies/shipping-policy)"
    )

    full_txt = (
        f"# {store_name} — Full Product Catalog\n\n"
        + "\n".join(full_lines)
    ) if include_full else ""

    return LLMTxtIndex(
        store_name=store_name,
        store_url=store_url,
        short_txt="\n".join(short) + "\n",
        full_txt=full_txt,
        product_mirrors=tuple(mirrors),
    )
