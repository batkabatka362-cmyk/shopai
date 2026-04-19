"""Bundle recommender — co-purchase pattern mining.

Upsell/cross-sell is one of the highest-ROI features a store can
ship, but it requires knowing which products *co-purchase*. A
hardcoded "also bought" list goes stale; a learning pipeline
keeps it live.

BundleRecommender ingests order rows (order_id + list_of_skus)
and produces item-set affinities using the Apriori-lite pattern:

  • support(A)      — fraction of orders containing A
  • support(A+B)    — fraction containing both
  • lift(A→B)       — support(A+B) / (support(A) × support(B))
  • confidence(A→B) — support(A+B) / support(A)

Any (A, B) with confidence ≥ min_confidence AND lift ≥ min_lift
AND support ≥ min_support becomes a rule. Rules are ranked by
lift × confidence so the top candidates are surfaced first.

APIs:

  ingest(orders)
  recommend_for_sku(sku, top_k=5)   → list[(target_sku, lift, conf)]
  recommend_for_cart(skus, top_k=5) → items to add given a cart
  top_bundles(top_k=10)             → strongest mined rules
  rules() / stats()

Pure stdlib. Deterministic. Works over the full history or a
rolling window.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Iterable


@dataclass
class BundleRule:
    antecedent: str                 # source SKU (A)
    consequent: str                 # target SKU (B)
    support_a: float
    support_b: float
    support_ab: float
    lift: float
    confidence: float

    def score(self) -> float:
        return self.lift * self.confidence

    def as_dict(self) -> dict[str, Any]:
        return {
            "antecedent": self.antecedent,
            "consequent": self.consequent,
            "support_a": round(self.support_a, 4),
            "support_b": round(self.support_b, 4),
            "support_ab": round(self.support_ab, 4),
            "lift": round(self.lift, 3),
            "confidence": round(self.confidence, 3),
            "score": round(self.score(), 3),
        }


# ── Recommender ─────────────────────────────────────────────

class BundleRecommender:
    def __init__(
        self,
        min_support: float = 0.01,
        min_confidence: float = 0.2,
        min_lift: float = 1.2,
    ) -> None:
        self._min_support = float(min_support)
        self._min_confidence = float(min_confidence)
        self._min_lift = float(min_lift)
        self._single_counts: dict[str, int] = defaultdict(int)
        self._pair_counts: dict[tuple[str, str], int] = defaultdict(int)
        self._order_count: int = 0

    # ── Ingest ─────────────────────────────────────────────

    def ingest(
        self, orders: Iterable[dict[str, Any] | list[str]],
    ) -> int:
        n = 0
        for row in orders:
            if isinstance(row, dict):
                skus = list(row.get("skus") or row.get("items") or [])
            else:
                skus = list(row)
            # dedup within the same order
            skus = sorted({str(s) for s in skus if s})
            if not skus:
                continue
            self._order_count += 1
            for sku in skus:
                self._single_counts[sku] += 1
            for a, b in combinations(skus, 2):
                self._pair_counts[(a, b)] += 1
            n += 1
        return n

    def reset(self) -> None:
        self._single_counts.clear()
        self._pair_counts.clear()
        self._order_count = 0

    # ── Rule mining ────────────────────────────────────────

    def rules(self) -> list[BundleRule]:
        if self._order_count == 0:
            return []
        out: list[BundleRule] = []
        total = float(self._order_count)
        for (a, b), count_ab in self._pair_counts.items():
            support_ab = count_ab / total
            if support_ab < self._min_support:
                continue
            sa = self._single_counts.get(a, 0) / total
            sb = self._single_counts.get(b, 0) / total
            if sa <= 0 or sb <= 0:
                continue
            lift = support_ab / (sa * sb)
            if lift < self._min_lift:
                continue
            # Emit both directions
            conf_ab = support_ab / sa if sa > 0 else 0.0
            conf_ba = support_ab / sb if sb > 0 else 0.0
            if conf_ab >= self._min_confidence:
                out.append(BundleRule(
                    antecedent=a, consequent=b,
                    support_a=sa, support_b=sb, support_ab=support_ab,
                    lift=lift, confidence=conf_ab,
                ))
            if conf_ba >= self._min_confidence:
                out.append(BundleRule(
                    antecedent=b, consequent=a,
                    support_a=sb, support_b=sa, support_ab=support_ab,
                    lift=lift, confidence=conf_ba,
                ))
        out.sort(key=lambda r: -r.score())
        return out

    def top_bundles(self, top_k: int = 10) -> list[BundleRule]:
        return self.rules()[:top_k]

    # ── Lookups ────────────────────────────────────────────

    def recommend_for_sku(
        self, sku: str, top_k: int = 5,
    ) -> list[BundleRule]:
        return [
            r for r in self.rules()
            if r.antecedent == sku
        ][:top_k]

    def recommend_for_cart(
        self, cart_skus: Iterable[str], top_k: int = 5,
    ) -> list[BundleRule]:
        """Candidates to add given a non-empty cart. Excludes items
        already in the cart; if a target rule fires from multiple
        antecedents, the best score wins."""
        cart = {s for s in cart_skus if s}
        if not cart:
            return []
        best: dict[str, BundleRule] = {}
        for r in self.rules():
            if r.antecedent not in cart:
                continue
            if r.consequent in cart:
                continue
            prev = best.get(r.consequent)
            if prev is None or r.score() > prev.score():
                best[r.consequent] = r
        out = list(best.values())
        out.sort(key=lambda r: -r.score())
        return out[:top_k]

    # ── Introspection ─────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        return {
            "orders": self._order_count,
            "unique_skus": len(self._single_counts),
            "pair_observations": sum(self._pair_counts.values()),
            "mined_rules": len(self.rules()),
        }
