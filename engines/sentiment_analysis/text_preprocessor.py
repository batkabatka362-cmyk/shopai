"""Sentiment Analysis Engine — text preprocessor.

Cleans and tokenizes raw text inputs. Removes noise, normalizes
whitespace, strips HTML, and produces cleaned tokens for analysis.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import re
from typing import Any


# ---------------------------------------------------------------------------
# Stop words to filter from tokens
# ---------------------------------------------------------------------------

_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "it", "in", "on", "at", "to", "for", "of", "and",
    "or", "but", "not", "with", "this", "that", "was", "are", "were", "been",
    "be", "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "i", "me", "my", "we", "our", "you",
    "your", "he", "she", "they", "them", "his", "her", "its", "so", "if",
    "as", "by", "from", "up", "about", "into", "over", "after", "very",
    "just", "also", "than", "then", "when", "what", "which", "who", "how",
})

# HTML tag pattern
_HTML_RE = re.compile(r"<[^>]+>")

# URL pattern
_URL_RE = re.compile(r"https?://\S+|www\.\S+")

# Multiple whitespace
_MULTI_SPACE_RE = re.compile(r"\s+")


def preprocess_texts(
    texts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Clean and tokenize raw text inputs.

    Args:
        texts: List of TextInput dicts with source, text, date fields.

    Returns:
        Structured dict with processed texts.
    """
    try:
        texts = copy.deepcopy(texts)
        processed: list[dict[str, Any]] = []

        for idx, text_input in enumerate(texts):
            text_id = str(text_input.get("id", f"text_{idx}"))
            original = str(text_input.get("text", ""))
            source = str(text_input.get("source", "unknown"))
            date = str(text_input.get("date", ""))

            # Clean the text
            cleaned = _clean_text(original)

            # Tokenize
            tokens = _tokenize(cleaned)

            processed.append({
                "id": text_id,
                "original": original,
                "cleaned": cleaned,
                "tokens": tokens,
                "source": source,
                "date": date,
            })

        return {
            "status": "success",
            "processed_texts": processed,
            "total": len(processed),
        }
    except Exception as exc:
        return {
            "status": "error",
            "processed_texts": [],
            "error": f"Text preprocessing failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    """Clean raw text by removing HTML, URLs, and normalizing whitespace."""
    # Remove HTML tags
    text = _HTML_RE.sub(" ", text)

    # Remove URLs
    text = _URL_RE.sub(" ", text)

    # Normalize whitespace
    text = _MULTI_SPACE_RE.sub(" ", text).strip()

    return text


def _tokenize(text: str) -> list[str]:
    """Tokenize cleaned text into meaningful words."""
    # Split on non-alphanumeric characters
    words = re.findall(r"[a-zA-Z']+", text.lower())

    # Filter stop words and short words
    tokens = [
        w for w in words
        if w not in _STOP_WORDS and len(w) > 2
    ]

    return tokens
