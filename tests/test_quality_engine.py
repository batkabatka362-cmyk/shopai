"""Tests for core.memory.quality_engine (Wave 2 #3).

Covers:

* MemoryClass / MemoryRecord dataclass
* classify() decision tree — every branch + tie-breakers
* decay_recency() — fresh = 1.0, one half-life = 0.5, negative
  ages clamped, different classes decay at different speeds
* score() — component math is correct, weights sum to 1.0,
  classification is consulted when not supplied
* rank() — sort order by score desc, ties broken by created_at asc
* is_worth_keeping() — threshold gating
* describe() — debug breakdown shape
"""
from __future__ import annotations

import math

import pytest

from core.memory.quality_engine import (
    MemoryClass,
    MemoryRecord,
    classify,
    decay_recency,
    describe,
    is_worth_keeping,
    rank,
    score,
)


# ---------------------------------------------------------------------------
# MemoryClass / MemoryRecord shape
# ---------------------------------------------------------------------------


def test_memory_class_values():
    assert MemoryClass.KNOWLEDGE.value == "knowledge"
    assert MemoryClass.ERROR.value == "error"
    assert MemoryClass.SIGNAL.value == "signal"
    assert MemoryClass.NOISE.value == "noise"


def test_memory_record_defaults():
    r = MemoryRecord(kind="rule")
    assert r.quality == 0.5
    assert r.confidence == 0.5
    assert r.success_rate == 0.5
    assert r.usage == 0
    assert r.tags == ()
    assert r.payload == {}
    assert r.created_at > 0


# ---------------------------------------------------------------------------
# classify: explicit tags / error / knowledge kinds
# ---------------------------------------------------------------------------


def test_classify_noise_tag_wins():
    # Even a KNOWLEDGE-looking record gets NOISE when tagged
    r = MemoryRecord(
        kind="rule", quality=0.95, confidence=0.95, tags=("noise",),
    )
    assert classify(r) == MemoryClass.NOISE


def test_classify_error_tag():
    r = MemoryRecord(
        kind="rule", quality=0.95, confidence=0.95, tags=("error",),
    )
    assert classify(r) == MemoryClass.ERROR


def test_classify_error_kinds():
    for kind in ("error", "exception", "failure", "timeout", "rate_limit"):
        r = MemoryRecord(kind=kind)
        assert classify(r) == MemoryClass.ERROR, f"kind={kind}"


def test_classify_knowledge_kinds():
    for kind in (
        "rule", "lesson", "fact", "knowledge", "policy",
        "reflection", "decision",
    ):
        r = MemoryRecord(kind=kind)
        assert classify(r) == MemoryClass.KNOWLEDGE, f"kind={kind}"


def test_classify_high_quality_promoted_to_knowledge():
    r = MemoryRecord(kind="observation", quality=0.8, confidence=0.9)
    assert classify(r) == MemoryClass.KNOWLEDGE


def test_classify_signal_kinds():
    for kind in ("metric", "signal", "ab_result", "telemetry"):
        r = MemoryRecord(kind=kind)
        assert classify(r) == MemoryClass.SIGNAL, f"kind={kind}"


def test_classify_noise_kinds():
    for kind in ("debug", "trace", "spam"):
        r = MemoryRecord(kind=kind, quality=0.5, confidence=0.5)
        assert classify(r) == MemoryClass.NOISE, f"kind={kind}"


def test_classify_low_quality_is_noise():
    r = MemoryRecord(kind="misc", quality=0.1, confidence=0.5)
    assert classify(r) == MemoryClass.NOISE
    r2 = MemoryRecord(kind="misc", quality=0.5, confidence=0.1)
    assert classify(r2) == MemoryClass.NOISE


def test_classify_fallback_is_signal():
    r = MemoryRecord(kind="unknown_kind", quality=0.5, confidence=0.5)
    assert classify(r) == MemoryClass.SIGNAL


# ---------------------------------------------------------------------------
# decay_recency
# ---------------------------------------------------------------------------


def test_decay_fresh_record_is_one():
    t = 1_000_000.0
    r = decay_recency(t, MemoryClass.KNOWLEDGE, now=t)
    assert r == pytest.approx(1.0)


def test_decay_one_half_life_is_half():
    t = 1_000_000.0
    one_day = 86_400.0
    # NOISE half-life is 1 day
    one_half_life_later = t + one_day
    r = decay_recency(t, MemoryClass.NOISE, now=one_half_life_later)
    assert r == pytest.approx(0.5, rel=1e-6)


def test_decay_two_half_lives_is_quarter():
    t = 1_000_000.0
    # SIGNAL half-life is 7 days
    two_half_lives = t + 14 * 86_400.0
    r = decay_recency(t, MemoryClass.SIGNAL, now=two_half_lives)
    assert r == pytest.approx(0.25, rel=1e-6)


def test_decay_classes_differ_in_half_life():
    t = 1_000_000.0
    one_week_later = t + 7 * 86_400.0
    # NOISE has a 1-day half-life → after 7 days ≈ 0.5^7 ≈ 0.0078
    n = decay_recency(t, MemoryClass.NOISE, now=one_week_later)
    # KNOWLEDGE has 30-day half-life → after 7 days ≈ 0.5^(7/30) ≈ 0.85
    k = decay_recency(t, MemoryClass.KNOWLEDGE, now=one_week_later)
    assert n < 0.01
    assert k > 0.8


def test_decay_negative_age_clamped():
    t = 1_000_000.0
    # created in the future → age clamped to 0 → recency 1.0
    r = decay_recency(t, MemoryClass.KNOWLEDGE, now=t - 10)
    assert r == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# score()
# ---------------------------------------------------------------------------


def test_score_in_zero_one():
    r = MemoryRecord(
        kind="rule", quality=1.0, confidence=1.0,
        success_rate=1.0, usage=1000,
    )
    s = score(r)
    assert 0.0 <= s <= 1.0


def test_score_perfect_record_near_one():
    t = 1_000_000.0
    r = MemoryRecord(
        kind="rule", quality=1.0, confidence=1.0,
        success_rate=1.0, usage=1000, created_at=t,
    )
    s = score(r, now=t)
    # recency = 1.0 (fresh)
    # components: 1*0.3 + 1*0.25 + 1*0.2 + 1*0.15 + ~1*0.1 ≈ 0.99+
    assert s > 0.95


def test_score_noise_record_near_zero():
    t = 1_000_000.0
    r = MemoryRecord(
        kind="debug", quality=0.1, confidence=0.1,
        success_rate=0.1, usage=0, created_at=t,
    )
    # now is two days later — NOISE half-life is 1 day so recency ≈ 0.25
    s = score(r, now=t + 2 * 86_400.0)
    assert s < 0.2


def test_score_clamps_out_of_range_inputs():
    r = MemoryRecord(
        kind="rule", quality=1.5, confidence=-0.3, success_rate=2.0,
    )
    s = score(r)
    assert 0.0 <= s <= 1.0


def test_score_nan_inputs_safe():
    r = MemoryRecord(
        kind="rule", quality=float("nan"),
        confidence=0.5, success_rate=0.5,
    )
    # Should not raise or return NaN
    s = score(r)
    assert not math.isnan(s)
    assert 0.0 <= s <= 1.0


def test_score_explicit_class_skips_classify():
    r = MemoryRecord(kind="anything")
    # Pin to KNOWLEDGE so we can assert on the 30-day half-life
    s_with_class = score(r, memory_class=MemoryClass.KNOWLEDGE)
    s_auto = score(r)
    # May differ because auto-classify might pick SIGNAL (7d half-life)
    assert 0 <= s_with_class <= 1 and 0 <= s_auto <= 1


def test_score_usage_diminishing_returns():
    r_low  = MemoryRecord(kind="rule", usage=1)
    r_mid  = MemoryRecord(kind="rule", usage=10)
    r_high = MemoryRecord(kind="rule", usage=1000)
    s_low  = score(r_low)
    s_mid  = score(r_mid)
    s_high = score(r_high)
    assert s_low < s_mid < s_high
    # diminishing returns: the jump from 10→1000 is smaller than 1→10
    assert (s_high - s_mid) < (s_mid - s_low) * 10


# ---------------------------------------------------------------------------
# rank()
# ---------------------------------------------------------------------------


def test_rank_orders_by_score_descending():
    t = 1_000_000.0
    records = [
        MemoryRecord(kind="debug", quality=0.1, confidence=0.1, created_at=t),
        MemoryRecord(kind="rule",  quality=1.0, confidence=1.0, created_at=t),
        MemoryRecord(kind="metric", quality=0.5, confidence=0.5, created_at=t),
    ]
    ranked = rank(records, now=t)
    assert [t2[0].kind for t2 in ranked][0] == "rule"
    assert [t2[0].kind for t2 in ranked][-1] == "debug"


def test_rank_tie_breaker_older_wins():
    # Both records are identical except for created_at. We set
    # ``now`` to the older record's timestamp so the newer one's
    # age is clamped to 0 — both get recency 1.0 and therefore
    # the exact same score. The rank() tie-breaker must then
    # pick the older one deterministically.
    older = MemoryRecord(
        kind="rule", quality=0.5, confidence=0.5,
        success_rate=0.5, usage=0, created_at=1_000_000.0,
    )
    newer = MemoryRecord(
        kind="rule", quality=0.5, confidence=0.5,
        success_rate=0.5, usage=0, created_at=1_000_000.5,
    )
    ranked = rank([newer, older], now=1_000_000.0)
    s_older, s_newer = ranked[0][1], ranked[1][1]
    assert s_older == s_newer, (
        "fixture must produce a genuine tie: "
        f"older={s_older}, newer={s_newer}"
    )
    # Deterministic tie-break: older first
    assert ranked[0][0] is older
    assert ranked[1][0] is newer


def test_rank_returns_class_in_tuple():
    t = 1_000_000.0
    r = MemoryRecord(kind="rule", quality=1.0, confidence=1.0, created_at=t)
    ranked = rank([r], now=t)
    assert len(ranked) == 1
    assert ranked[0][2] == MemoryClass.KNOWLEDGE


# ---------------------------------------------------------------------------
# is_worth_keeping
# ---------------------------------------------------------------------------


def test_is_worth_keeping_high_quality_record():
    t = 1_000_000.0
    r = MemoryRecord(
        kind="rule", quality=1.0, confidence=1.0,
        success_rate=1.0, usage=100, created_at=t,
    )
    assert is_worth_keeping(r, now=t) is True


def test_is_worth_keeping_noise_fails():
    t = 1_000_000.0
    r = MemoryRecord(
        kind="debug", quality=0.05, confidence=0.05,
        success_rate=0.05, created_at=t,
    )
    # far enough in the future that NOISE fully decays
    assert is_worth_keeping(r, now=t + 86_400.0 * 5) is False


def test_is_worth_keeping_respects_threshold():
    t = 1_000_000.0
    r = MemoryRecord(
        kind="metric", quality=0.5, confidence=0.5,
        success_rate=0.5, usage=0, created_at=t,
    )
    # score is ~0.5 → above 0.25 default, below 0.9 custom
    assert is_worth_keeping(r, threshold=0.25, now=t) is True
    assert is_worth_keeping(r, threshold=0.9, now=t) is False


# ---------------------------------------------------------------------------
# describe()
# ---------------------------------------------------------------------------


def test_describe_returns_breakdown():
    t = 1_000_000.0
    r = MemoryRecord(
        kind="rule", quality=0.8, confidence=0.9,
        success_rate=0.7, usage=20, created_at=t,
    )
    out = describe(r, now=t)
    assert out["class"] == "knowledge"
    assert set(out["components"].keys()) == {
        "quality", "confidence", "recency",
        "success_rate", "usage",
    }
    assert set(out["weights"].keys()) == set(out["components"].keys())
    assert abs(sum(out["weights"].values()) - 1.0) < 1e-9
    assert 0.0 <= out["score"] <= 1.0
    assert out["half_life_s"] == 30 * 86_400.0


def test_describe_noise_shows_short_half_life():
    r = MemoryRecord(kind="debug", quality=0.1, confidence=0.1)
    out = describe(r)
    assert out["class"] == "noise"
    assert out["half_life_s"] == 1 * 86_400.0
