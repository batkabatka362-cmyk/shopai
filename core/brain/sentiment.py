"""Sentiment + intent analyser — parse customer text for signal.

Customers leave signal everywhere: reviews, Shopify order notes,
support emails, Instagram DMs. ShopAI had no parser so every
message landed in memory as opaque text. This module does:

  sentiment(text) → score ∈ [-1, +1] with label
  intent(text)    → one of {complaint, question, request, praise,
                              purchase_intent, unsubscribe, other}
  urgency(text)   → 0-3 (higher = reply faster)
  emotion(text)    → primary emotion label (anger, joy, sadness,
                     surprise, fear, neutral)
  analyse(text)   → all four in one pass

Rule-based, dictionary-driven — zero LLM cost, <1 ms per message.
Dictionaries are conservative + explicit so the tagger is
auditable and easy to extend. An optional LLM re-tag pass can
land later for ambiguous cases.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal


Intent = Literal[
    "complaint", "question", "request", "praise",
    "purchase_intent", "unsubscribe", "other",
]

Emotion = Literal[
    "anger", "joy", "sadness", "surprise", "fear", "neutral",
]


_POS_WORDS = {
    "love", "great", "amazing", "awesome", "fantastic", "excellent",
    "perfect", "wonderful", "best", "beautiful", "happy", "satisfied",
    "recommend", "thanks", "thank", "incredible", "outstanding",
}
_NEG_WORDS = {
    "hate", "awful", "terrible", "worst", "broken", "bad", "poor",
    "disappointed", "angry", "refund", "scam", "fake", "damaged",
    "rude", "unacceptable", "waste", "ripoff", "lousy",
}
_INTENSIFIERS = {"very", "really", "super", "extremely", "absolutely"}
_NEGATIONS = {"not", "no", "never", "none", "without"}


_COMPLAINT_WORDS = {
    "broken", "damaged", "refund", "return", "not working",
    "doesnt work", "wrong", "missing", "late", "scam",
}
_QUESTION_MARKERS = ("?", "how do", "can i", "when will", "is it",
                     "do you", "what is", "where is", "why is")
_REQUEST_MARKERS = ("please", "could you", "can you", "would you",
                    "send me", "change my", "update my")
_PRAISE_MARKERS = ("love it", "love this", "great product", "amazing",
                   "five stars", "5 stars", "highly recommend")
_BUY_INTENT = ("buy", "purchase", "order", "checkout", "add to cart",
               "how much", "price")
_UNSUBSCRIBE = ("unsubscribe", "stop emailing", "remove me",
                "take me off", "opt out")


_EMOTION_LEXICON = {
    "anger":    ("furious", "angry", "hate", "pissed", "outraged",
                 "annoyed", "frustrated"),
    "joy":      ("happy", "love", "joy", "delighted", "thrilled",
                 "glad", "excited"),
    "sadness":  ("sad", "sorry", "disappointed", "regret", "upset",
                 "unhappy"),
    "surprise": ("wow", "unbelievable", "shocked", "amazed",
                 "surprised"),
    "fear":     ("worried", "scared", "afraid", "nervous", "anxious"),
}


_URGENCY_WORDS = {
    "urgent": 3, "asap": 3, "immediately": 3, "refund": 3,
    "broken": 3, "today": 2, "wrong": 2, "missing": 2,
    "damaged": 2, "soon": 1, "quick": 1, "please": 0,
}


@dataclass
class Analysis:
    text: str
    sentiment_score: float        # -1..+1
    sentiment_label: str           # negative | neutral | positive
    intent: Intent
    urgency: int                   # 0-3
    emotion: Emotion
    matched_keywords: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "sentiment_score": round(self.sentiment_score, 3),
            "sentiment_label": self.sentiment_label,
            "intent": self.intent,
            "urgency": self.urgency,
            "emotion": self.emotion,
            "matched_keywords": self.matched_keywords,
        }


# ── Public API ──────────────────────────────────────────────

def analyse(text: str) -> Analysis:
    """One-shot analysis. Safe on empty strings."""
    if not text:
        return Analysis(
            text="", sentiment_score=0.0, sentiment_label="neutral",
            intent="other", urgency=0, emotion="neutral",
        )
    t = text.lower()
    score, matched = _sentiment_score(t)
    return Analysis(
        text=text,
        sentiment_score=score,
        sentiment_label=_label_for(score),
        intent=_intent(t),
        urgency=_urgency(t),
        emotion=_emotion(t),
        matched_keywords=matched,
    )


def sentiment(text: str) -> float:
    return analyse(text).sentiment_score


def intent(text: str) -> Intent:
    return analyse(text).intent


def urgency(text: str) -> int:
    return analyse(text).urgency


def emotion(text: str) -> Emotion:
    return analyse(text).emotion


# ── Internals ───────────────────────────────────────────────

_WORD_RE = re.compile(r"[a-z']+")


def _tokenise(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def _sentiment_score(text: str) -> tuple[float, list[str]]:
    tokens = _tokenise(text)
    if not tokens:
        return 0.0, []
    score = 0.0
    matched: list[str] = []
    i = 0
    for token in tokens:
        # Check preceding token for negation/intensifier
        prev = tokens[i - 1] if i > 0 else ""
        weight = 1.0
        if prev in _INTENSIFIERS:
            weight = 1.5
        if prev in _NEGATIONS:
            weight = -1.0
        if token in _POS_WORDS:
            score += 1.0 * weight
            matched.append(token)
        elif token in _NEG_WORDS:
            score -= 1.0 * weight
            matched.append(token)
        i += 1
    # Normalise to [-1, 1] via tanh-like squashing
    if score == 0:
        return 0.0, matched
    import math
    return math.tanh(score / 3.0), matched


def _label_for(score: float) -> str:
    if score > 0.2:
        return "positive"
    if score < -0.2:
        return "negative"
    return "neutral"


def _intent(text: str) -> Intent:
    if any(kw in text for kw in _UNSUBSCRIBE):
        return "unsubscribe"
    if any(kw in text for kw in _COMPLAINT_WORDS):
        return "complaint"
    if any(kw in text for kw in _BUY_INTENT):
        return "purchase_intent"
    if any(kw in text for kw in _PRAISE_MARKERS):
        return "praise"
    if any(kw in text for kw in _REQUEST_MARKERS):
        return "request"
    if any(text.strip().startswith(q) or q in text
           for q in _QUESTION_MARKERS):
        return "question"
    return "other"


def _urgency(text: str) -> int:
    best = 0
    for word, score in _URGENCY_WORDS.items():
        if word in text:
            best = max(best, score)
    return best


def _emotion(text: str) -> Emotion:
    scores: dict[str, int] = {e: 0 for e in _EMOTION_LEXICON}
    for emotion_name, words in _EMOTION_LEXICON.items():
        for w in words:
            if w in text:
                scores[emotion_name] += 1
    top = max(scores, key=lambda k: scores[k])
    return "neutral" if scores[top] == 0 else top   # type: ignore[return-value]
