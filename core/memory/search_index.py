"""Search index — TF-IDF full-text search over arbitrary documents.

ShopAI stores thousands of memories, product descriptions, policy
rules, knowledge-base facts. Looking something up by substring
match is slow and noisy. A proper inverted index + TF-IDF scoring
returns ranked results in milliseconds.

SearchIndex offers:

  add(doc_id, text, metadata)
  remove(doc_id)
  search(query, top_k=10, min_score=0.0) → list[Hit]
  suggest(prefix, top_k=10)    → id suggestions by term prefix
  stats()

Tokeniser lowercases, strips punctuation, and optionally stems
via a lightweight Porter-lite suffix trim so 'running' and 'runs'
match 'run'. Stop-words are filtered. TF-IDF scoring: log(1 + tf)
× log(N / df).

Pure stdlib (re + math). Deterministic. No external deps.
Integrates naturally with v7-D5 ontology + v16-D6 memory
compressor for full-text lookups over the whole knowledge base.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable


_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "in", "on",
    "at", "for", "to", "from", "is", "are", "was", "were",
    "be", "been", "being", "it", "its", "this", "that",
    "these", "those", "with", "without", "as", "by",
    "if", "then", "so", "not", "no",
}


@dataclass
class Hit:
    doc_id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    snippet: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "score": round(self.score, 4),
            "metadata": self.metadata,
            "snippet": self.snippet,
        }


# ── Tokeniser ──────────────────────────────────────────────

def _stem(word: str) -> str:
    """Tiny Porter-lite: strip a few common suffixes."""
    for suffix in ("ingly", "ing", "edly", "ed", "ies", "es",
                    "ly", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[:-len(suffix)]
    return word


def _tokenise(text: str) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    for token in _WORD_RE.findall(text.lower()):
        if token in _STOPWORDS or len(token) < 2:
            continue
        out.append(_stem(token))
    return out


# ── Index ──────────────────────────────────────────────────

class SearchIndex:
    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}
        self._doc_texts: dict[str, str] = {}
        self._postings: dict[str, dict[str, int]] = defaultdict(
            dict,
        )   # term → {doc_id: tf}
        self._doc_lengths: dict[str, int] = {}

    # ── Mutation ───────────────────────────────────────────

    def add(
        self, doc_id: str, text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        doc_id = doc_id.strip()
        if not doc_id:
            raise ValueError("doc_id required")
        # Remove any prior version
        if doc_id in self._docs:
            self.remove(doc_id)
        tokens = _tokenise(text or "")
        if not tokens:
            return
        tf: dict[str, int] = defaultdict(int)
        for t in tokens:
            tf[t] += 1
        for term, count in tf.items():
            self._postings[term][doc_id] = count
        self._docs[doc_id] = dict(metadata or {})
        self._doc_texts[doc_id] = text or ""
        self._doc_lengths[doc_id] = len(tokens)

    def remove(self, doc_id: str) -> bool:
        doc_id = doc_id.strip()
        if doc_id not in self._docs:
            return False
        for term, postings in list(self._postings.items()):
            if doc_id in postings:
                del postings[doc_id]
                if not postings:
                    del self._postings[term]
        self._docs.pop(doc_id, None)
        self._doc_texts.pop(doc_id, None)
        self._doc_lengths.pop(doc_id, None)
        return True

    # ── Query ──────────────────────────────────────────────

    def search(
        self, query: str, top_k: int = 10, min_score: float = 0.0,
    ) -> list[Hit]:
        terms = _tokenise(query or "")
        if not terms or not self._docs:
            return []
        n = len(self._docs)
        scores: dict[str, float] = defaultdict(float)
        for term in set(terms):
            postings = self._postings.get(term)
            if not postings:
                continue
            df = len(postings)
            idf = math.log((n / df) + 1)
            for doc_id, tf in postings.items():
                tf_weight = math.log(1 + tf)
                scores[doc_id] += tf_weight * idf
        hits = [
            Hit(
                doc_id=doc_id, score=score,
                metadata=self._docs.get(doc_id, {}),
                snippet=self._snippet(doc_id, terms),
            )
            for doc_id, score in scores.items()
            if score >= min_score
        ]
        hits.sort(key=lambda h: -h.score)
        return hits[:top_k]

    def suggest(self, prefix: str, top_k: int = 10) -> list[str]:
        prefix = prefix.lower().strip()
        if not prefix:
            return []
        matched_docs: set[str] = set()
        for term, postings in self._postings.items():
            if term.startswith(prefix):
                matched_docs.update(postings.keys())
        return sorted(matched_docs)[:top_k]

    # ── Helpers ────────────────────────────────────────────

    def _snippet(
        self, doc_id: str, query_terms: list[str],
    ) -> str:
        text = self._doc_texts.get(doc_id, "")
        if not text:
            return ""
        lower = text.lower()
        for term in query_terms:
            pos = lower.find(term)
            if pos >= 0:
                start = max(0, pos - 30)
                end = min(len(text), pos + len(term) + 30)
                return ("…" if start > 0 else "") + text[start:end] + \
                       ("…" if end < len(text) else "")
        return text[:80]

    # ── Introspection ─────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        return {
            "doc_count": len(self._docs),
            "term_count": len(self._postings),
            "avg_doc_length": (
                sum(self._doc_lengths.values())
                / max(1, len(self._doc_lengths))
            ),
        }
