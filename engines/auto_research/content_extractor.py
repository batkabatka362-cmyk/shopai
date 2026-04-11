"""Content Extractor — pulls usable text from raw search results.

Responsibility: transform ``RawSearchResult`` items into
``ExtractedContent`` by cleaning, normalising, and enriching the text.
In production this would fetch full page content; here it works with
the snippet already available.

Model note: no model usage — deterministic text processing.
"""
from __future__ import annotations

import copy
import re
import time
from typing import Any

from .types import RawSearchResult, ExtractedContent


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_content(raw_results: list[RawSearchResult]) -> list[ExtractedContent]:
    """Extract clean content from raw search results.

    Never mutates *raw_results* — works on a deep copy.
    Skips results whose snippet is empty or too short to be useful.
    """
    safe_results: list[RawSearchResult] = copy.deepcopy(raw_results)

    extracted: list[ExtractedContent] = []
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for result in safe_results:
        text = _clean_text(result.get("snippet", ""))
        if not text or len(text.split()) < 5:
            continue

        # Combine title context with snippet for richer extraction
        title = _clean_text(result.get("title", ""))
        combined = f"{title}. {text}" if title else text

        extracted.append(
            ExtractedContent(
                source_url=result.get("url", ""),
                source_title=title,
                text=combined,
                word_count=len(combined.split()),
                extracted_at=now_iso,
            )
        )

    return extracted


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    """Normalise whitespace, strip HTML remnants, and trim."""
    if not text:
        return ""

    # Remove common HTML artefacts
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    # Remove non-printable characters
    text = re.sub(r"[^\x20-\x7E\u00A0-\uFFFF]", "", text)
    return text.strip()
