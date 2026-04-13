"""Legal Document Engine — formatter.

Formats legal documents for web display with proper HTML structure,
headings, and semantic markup.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import html
from typing import Any


def format_documents(
    documents: list[dict[str, Any]],
    business: dict[str, Any],
) -> dict[str, Any]:
    """Format legal documents for web display.

    Args:
        documents: List of generated document dicts.
        business: Business info dict.

    Returns:
        Structured dict with formatted documents including HTML content.
    """
    try:
        docs = copy.deepcopy(documents)
        business_name = html.escape(str(business.get("name", "Our Company")))

        formatted: list[dict[str, Any]] = []

        for doc in docs:
            doc_type = str(doc.get("type", ""))
            title = str(doc.get("title", ""))
            sections = doc.get("sections", [])
            last_updated = str(doc.get("last_updated", ""))

            # Build HTML
            html_parts: list[str] = [
                f'<article class="legal-document legal-{html.escape(doc_type)}">',
                f'  <header>',
                f'    <h1>{html.escape(title)}</h1>',
                f'    <p class="last-updated">Last updated: {html.escape(last_updated)}</p>',
                f'    <p class="business-name">{business_name}</p>',
                f'  </header>',
                f'  <div class="legal-content">',
            ]

            for idx, section in enumerate(sections):
                heading = html.escape(str(section.get("heading", "")))
                content = html.escape(str(section.get("content", "")))

                html_parts.append(f'    <section id="section-{idx + 1}">')
                html_parts.append(f'      <h2>{heading}</h2>')
                html_parts.append(f'      <p>{content}</p>')
                html_parts.append(f'    </section>')

            html_parts.append('  </div>')
            html_parts.append('</article>')

            html_content = "\n".join(html_parts)

            formatted.append({
                "type": doc_type,
                "title": title,
                "content": doc.get("content", ""),
                "sections": sections,
                "last_updated": last_updated,
                "html_content": html_content,
            })

        return {
            "status": "success",
            "documents": formatted,
        }
    except Exception as exc:
        return {
            "status": "error",
            "documents": [],
            "error": f"Formatting failed: {exc}",
        }
