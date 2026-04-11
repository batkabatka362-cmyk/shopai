"""Cognitive Module — 6 advanced brain capabilities.

C1: Deep Understanding — text + context + product similarity
C2: Associative Memory — similarity search + time decay + consolidation
C3: Reasoning Chain — if-then-therefore + hypothesis + counterfactual
C4: Self-Reflection — confidence calibration + bias detection + journal
C5: Failure Chain — root cause chains + near-miss + prevention
C6: Curiosity Engine — exploration drive + uncertainty + question generation
"""
from __future__ import annotations

import math
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("brain.cognitive")


# ═══════════════════════════════════════════════════════════
# C1: DEEP UNDERSTANDING
# ═══════════════════════════════════════════════════════════

class DeepUnderstanding:
    """Understands products, customers, and context beyond numbers."""

    # Common e-commerce stop words
    _STOP = {"the", "a", "an", "and", "or", "for", "with", "in", "on", "of", "to", "is", "it", "-", "&", ""}

    @staticmethod
    def extract_keywords(text: str, max_keywords: int = 5) -> list[str]:
        """Extract meaningful keywords from product text."""
        if not text:
            return []
        words = text.lower().replace("-", " ").replace("/", " ").split()
        keywords = [w.strip(".,!?()[]") for w in words
                     if len(w) > 2 and w.strip(".,!?()[]") not in DeepUnderstanding._STOP]
        # Deduplicate preserving order
        seen = set()
        result = []
        for k in keywords:
            if k not in seen:
                seen.add(k)
                result.append(k)
        return result[:max_keywords]

    @staticmethod
    def product_similarity(a: dict, b: dict) -> float:
        """Calculate similarity between two products (0-1)."""
        score = 0.0
        weights = 0.0

        # Category match (0.3 weight)
        cat_a = str(a.get("product_type", a.get("category", ""))).lower()
        cat_b = str(b.get("product_type", b.get("category", ""))).lower()
        if cat_a and cat_b:
            if cat_a == cat_b:
                score += 0.3
            elif cat_a in cat_b or cat_b in cat_a:
                score += 0.15
        weights += 0.3

        # Price range match (0.25 weight)
        pa = float(a.get("price", 0))
        pb = float(b.get("price", 0))
        if pa > 0 and pb > 0:
            ratio = min(pa, pb) / max(pa, pb)
            score += 0.25 * ratio
        weights += 0.25

        # Margin similarity (0.2 weight)
        ma = _margin(a)
        mb = _margin(b)
        if ma is not None and mb is not None:
            diff = abs(ma - mb)
            score += 0.2 * max(0, 1 - diff * 2)
        weights += 0.2

        # Keyword overlap (0.25 weight)
        kw_a = set(DeepUnderstanding.extract_keywords(
            a.get("name", a.get("title", ""))))
        kw_b = set(DeepUnderstanding.extract_keywords(
            b.get("name", b.get("title", ""))))
        if kw_a and kw_b:
            overlap = len(kw_a & kw_b) / max(len(kw_a | kw_b), 1)
            score += 0.25 * overlap
        weights += 0.25

        return round(score / max(weights, 0.01), 3)

    @staticmethod
    def explain_product(product: dict) -> dict[str, Any]:
        """Build a human-readable understanding of a product."""
        price = float(product.get("price", 0))
        cost = float(product.get("cost", 0))
        margin = _margin(product)
        name = product.get("name", product.get("title", "Unknown"))
        keywords = DeepUnderstanding.extract_keywords(name)

        insights = []
        if margin is not None:
            if margin > 0.6:
                insights.append("High margin — good profit potential")
            elif margin > 0.3:
                insights.append("Medium margin — standard")
            elif margin > 0:
                insights.append("Low margin — consider raising price")
            else:
                insights.append("NEGATIVE margin — losing money!")

        has_images = bool(product.get("images") or product.get("image") or product.get("image_url"))
        if not has_images:
            insights.append("No images — hurts conversion")

        inventory = int(product.get("inventory_quantity", 0))
        if inventory == 0:
            insights.append("Zero inventory — out of stock")
        elif inventory < 5:
            insights.append("Low inventory — restock soon")

        return {
            "name": name,
            "keywords": keywords,
            "price": price,
            "cost": cost,
            "margin": round(margin, 3) if margin is not None else None,
            "has_images": has_images,
            "inventory": inventory,
            "insights": insights,
            "health": "good" if len(insights) <= 1 else "needs_attention" if len(insights) <= 2 else "critical",
        }

    @staticmethod
    def find_similar(target: dict, products: list[dict],
                     min_similarity: float = 0.3, limit: int = 5) -> list[dict]:
        """Find products similar to target."""
        results = []
        for p in products:
            if str(p.get("id", "")) == str(target.get("id", "")):
                continue
            sim = DeepUnderstanding.product_similarity(target, p)
            if sim >= min_similarity:
                results.append({
                    "product_id": p.get("id"),
                    "name": p.get("name", p.get("title", "")),
                    "similarity": sim,
                    "price": float(p.get("price", 0)),
                })
        results.sort(key=lambda x: -x["similarity"])
        return results[:limit]


# ═══════════════════════════════════════════════════════════
# C2: ASSOCIATIVE MEMORY
# ═══════════════════════════════════════════════════════════

class AssociativeMemory:
    """Memory with similarity search and time decay."""

    @staticmethod
    def feature_similarity(a: dict, b: dict) -> float:
        """Cosine-like similarity between two feature dicts."""
        all_keys = set(list(a.keys()) + list(b.keys()))
        if not all_keys:
            return 0.0

        dot = 0.0
        norm_a = 0.0
        norm_b = 0.0
        for k in all_keys:
            va = _to_float(a.get(k))
            vb = _to_float(b.get(k))
            dot += va * vb
            norm_a += va * va
            norm_b += vb * vb

        if norm_a == 0 or norm_b == 0:
            return 0.0
        return round(dot / (math.sqrt(norm_a) * math.sqrt(norm_b)), 3)

    @staticmethod
    def time_decay(timestamp: float, half_life_days: float = 14.0) -> float:
        """Exponential time decay. Returns 0-1 weight."""
        age_days = (time.time() - timestamp) / 86400
        if age_days <= 0:
            return 1.0
        return math.exp(-0.693 * age_days / half_life_days)

    @staticmethod
    def search_similar(query_features: dict, memories: list[dict],
                       top_k: int = 10, decay: bool = True) -> list[dict]:
        """Search memories by feature similarity with time decay."""
        scored = []
        for m in memories:
            features = m.get("features", {})
            if not isinstance(features, dict):
                continue
            sim = AssociativeMemory.feature_similarity(query_features, features)
            if decay:
                ts = m.get("timestamp", time.time())
                weight = AssociativeMemory.time_decay(ts)
                final = sim * 0.7 + weight * 0.3
            else:
                final = sim
            scored.append({**m, "_similarity": round(sim, 3), "_final": round(final, 3)})

        scored.sort(key=lambda x: -x["_final"])
        return scored[:top_k]

    @staticmethod
    def consolidate(memories: list[dict], threshold: float = 0.8) -> list[dict]:
        """Consolidate similar memories — strengthen strong ones, merge weak."""
        if len(memories) < 2:
            return memories

        groups: list[list[dict]] = []
        used = set()
        for i, m in enumerate(memories):
            if i in used:
                continue
            group = [m]
            for j, other in enumerate(memories[i+1:], i+1):
                if j in used:
                    continue
                fi = m.get("features", {})
                fj = other.get("features", {})
                if isinstance(fi, dict) and isinstance(fj, dict):
                    if AssociativeMemory.feature_similarity(fi, fj) >= threshold:
                        group.append(other)
                        used.add(j)
            used.add(i)
            groups.append(group)

        consolidated = []
        for group in groups:
            best = max(group, key=lambda m: m.get("score", 0))
            best["_consolidated_from"] = len(group)
            consolidated.append(best)

        return consolidated


# ═══════════════════════════════════════════════════════════
# C3: REASONING CHAIN
# ═══════════════════════════════════════════════════════════

class ReasoningChain:
    """Multi-step logical reasoning with hypothesis testing."""

    @staticmethod
    def if_then(condition: dict, action: str, products: list[dict],
                rules: list[dict]) -> dict[str, Any]:
        """If-Then-Therefore reasoning.

        Example: IF margin < 0.2 THEN raise price THEREFORE profit increases
        """
        matching = []
        for p in products:
            match = True
            for k, v in condition.items():
                pval = p.get(k)
                if pval is None:
                    match = False
                    break
                if isinstance(v, (int, float)):
                    if float(pval) > v:  # condition is max threshold
                        match = False
                elif str(pval) != str(v):
                    match = False
            if match:
                matching.append(p)

        # Check if rules support this
        supporting_rules = [r for r in rules if action in str(r.get("content", {}))]

        return {
            "condition": condition,
            "action": action,
            "matching_products": len(matching),
            "supported_by_rules": len(supporting_rules),
            "confidence": min(0.9, 0.3 + len(supporting_rules) * 0.15 + min(len(matching), 5) * 0.05),
            "therefore": "likely_positive" if supporting_rules else "uncertain",
        }

    @staticmethod
    def hypothesis(statement: str, evidence_for: list[str],
                   evidence_against: list[str]) -> dict[str, Any]:
        """Test a hypothesis with evidence."""
        total = len(evidence_for) + len(evidence_against)
        if total == 0:
            return {"hypothesis": statement, "verdict": "no_evidence", "confidence": 0.0}

        support_ratio = len(evidence_for) / total
        if support_ratio > 0.7:
            verdict = "supported"
        elif support_ratio < 0.3:
            verdict = "rejected"
        else:
            verdict = "inconclusive"

        return {
            "hypothesis": statement,
            "evidence_for": len(evidence_for),
            "evidence_against": len(evidence_against),
            "support_ratio": round(support_ratio, 2),
            "verdict": verdict,
            "confidence": round(abs(support_ratio - 0.5) * 2, 2),
        }

    @staticmethod
    def counterfactual(actual_action: str, actual_score: float,
                       alternative_action: str, memory_scores: dict) -> dict[str, Any]:
        """What if we had done something different?"""
        alt_scores = memory_scores.get(alternative_action, [])
        if not alt_scores:
            return {
                "question": "What if {} instead of {}?".format(alternative_action, actual_action),
                "answer": "no_data",
                "regret": 0.0,
            }

        avg_alt = sum(alt_scores) / len(alt_scores)
        regret = avg_alt - actual_score

        return {
            "question": "What if {} instead of {}?".format(alternative_action, actual_action),
            "actual_score": actual_score,
            "alternative_avg": round(avg_alt, 2),
            "regret": round(regret, 2),
            "answer": "better" if regret > 0.5 else "worse" if regret < -0.5 else "similar",
            "lesson": "Consider {} next time".format(alternative_action) if regret > 0.5 else "Good choice",
        }


# ═══════════════════════════════════════════════════════════
# C4: SELF-REFLECTION
# ═══════════════════════════════════════════════════════════

class SelfReflection:
    """Decision quality assessment and bias detection."""

    def __init__(self) -> None:
        self._journal: list[dict[str, Any]] = []
        self._confidence_history: list[tuple[float, float]] = []  # (predicted, actual)
        self._action_counts: dict[str, int] = {}

    def record_decision(self, action: str, confidence: float,
                        actual_score: float) -> None:
        """Record a decision for reflection."""
        self._journal.append({
            "action": action,
            "confidence": confidence,
            "actual_score": actual_score,
            "timestamp": time.time(),
        })
        self._confidence_history.append((confidence, actual_score / 5.0))
        self._action_counts[action] = self._action_counts.get(action, 0) + 1

    def calibration_check(self) -> dict[str, Any]:
        """Check if confidence predictions match actual outcomes."""
        if len(self._confidence_history) < 5:
            return {"status": "insufficient_data", "entries": len(self._confidence_history)}

        total_error = 0.0
        overconfident = 0
        underconfident = 0
        for predicted, actual in self._confidence_history[-50:]:
            error = predicted - actual
            total_error += abs(error)
            if error > 0.2:
                overconfident += 1
            elif error < -0.2:
                underconfident += 1

        n = len(self._confidence_history[-50:])
        avg_error = total_error / n
        return {
            "avg_error": round(avg_error, 3),
            "overconfident_pct": round(overconfident / n * 100),
            "underconfident_pct": round(underconfident / n * 100),
            "well_calibrated_pct": round((n - overconfident - underconfident) / n * 100),
            "diagnosis": "overconfident" if overconfident > n * 0.4
                         else "underconfident" if underconfident > n * 0.4
                         else "well_calibrated",
            "entries": n,
        }

    def detect_bias(self) -> dict[str, Any]:
        """Detect action selection biases."""
        if not self._action_counts:
            return {"biases": [], "total_decisions": 0}

        total = sum(self._action_counts.values())
        biases = []

        for action, count in self._action_counts.items():
            pct = count / total
            if pct > 0.5 and total >= 10:
                biases.append({
                    "type": "over_selection",
                    "action": action,
                    "frequency": round(pct * 100),
                    "recommendation": "Explore alternatives to {}".format(action),
                })
            if pct < 0.05 and total >= 20:
                biases.append({
                    "type": "under_exploration",
                    "action": action,
                    "frequency": round(pct * 100),
                    "recommendation": "Try {} more often".format(action),
                })

        return {"biases": biases, "total_decisions": total, "unique_actions": len(self._action_counts)}

    def reflect(self) -> dict[str, Any]:
        """Full self-reflection report."""
        calibration = self.calibration_check()
        biases = self.detect_bias()

        # Recent decision quality
        recent = self._journal[-10:]
        avg_score = sum(d["actual_score"] for d in recent) / max(len(recent), 1) if recent else 0

        return {
            "calibration": calibration,
            "biases": biases,
            "recent_avg_score": round(avg_score, 2),
            "total_decisions_reflected": len(self._journal),
            "top_action": max(self._action_counts, key=self._action_counts.get) if self._action_counts else "none",
        }


# ═══════════════════════════════════════════════════════════
# C5: FAILURE CHAIN ANALYSIS
# ═══════════════════════════════════════════════════════════

class FailureChainAnalysis:
    """Deep failure analysis with root cause chains."""

    def __init__(self) -> None:
        self._chains: list[dict[str, Any]] = []
        self._near_misses: list[dict[str, Any]] = []

    def analyze_chain(self, failure: dict, context: list[dict]) -> dict[str, Any]:
        """Trace a failure back through its cause chain."""
        chain = [failure]
        root = failure

        # Look for preceding events that may have caused this
        failure_time = failure.get("timestamp", time.time())
        for event in sorted(context, key=lambda x: x.get("timestamp", 0), reverse=True):
            event_time = event.get("timestamp", 0)
            if event_time >= failure_time:
                continue
            if event_time < failure_time - 3600:
                break  # Only look 1 hour back

            # Check if this event is related
            if event.get("category") == failure.get("category"):
                if event.get("score", 5) <= 2.5:
                    chain.append(event)
                    root = event

        chain.reverse()
        self._chains.append({"chain": chain, "root": root, "depth": len(chain)})

        return {
            "chain_depth": len(chain),
            "root_cause": root.get("action", root.get("category", "unknown")),
            "root_score": root.get("score", 0),
            "intermediate_steps": len(chain) - 1,
            "prevention": "Address {} first".format(root.get("action", "root issue")),
        }

    def detect_near_miss(self, score: float, threshold: float = 2.5) -> dict[str, Any] | None:
        """Detect near-miss: score barely above failure threshold."""
        if threshold < score <= threshold + 0.5:
            near_miss = {
                "score": score,
                "margin": round(score - threshold, 2),
                "warning": "Almost failed — score {:.1f} barely above {:.1f}".format(score, threshold),
                "timestamp": time.time(),
            }
            self._near_misses.append(near_miss)
            return near_miss
        return None

    def generate_prevention_rules(self) -> list[dict[str, Any]]:
        """Generate preventive rules from failure chains."""
        rules = []
        # Group chains by root cause
        root_causes: dict[str, int] = {}
        for chain_data in self._chains:
            root = chain_data["root"].get("action", "unknown")
            root_causes[root] = root_causes.get(root, 0) + 1

        for cause, count in root_causes.items():
            if count >= 2:
                rules.append({
                    "type": "prevention",
                    "trigger": cause,
                    "action": "pre_check",
                    "rule": "Before {}: verify prerequisites ({} past failures)".format(cause, count),
                    "priority": "high" if count >= 3 else "medium",
                })

        return rules

    def get_stats(self) -> dict[str, Any]:
        return {
            "chains_analyzed": len(self._chains),
            "near_misses": len(self._near_misses),
            "avg_chain_depth": round(
                sum(c["depth"] for c in self._chains) / max(len(self._chains), 1), 1),
        }


# ═══════════════════════════════════════════════════════════
# C6: CURIOSITY ENGINE
# ═══════════════════════════════════════════════════════════

class CuriosityEngine:
    """Active exploration and question generation."""

    def __init__(self) -> None:
        self._explored: dict[str, int] = {}  # action → times explored
        self._uncertainties: list[dict[str, Any]] = []
        self._questions: list[str] = []

    def exploration_score(self) -> float:
        """How much are we exploring? 0=stuck, 1=very curious."""
        if not self._explored:
            return 0.5
        total = sum(self._explored.values())
        unique = len(self._explored)
        if total == 0:
            return 0.5
        # Entropy-based exploration score
        entropy = 0.0
        for count in self._explored.values():
            p = count / total
            if p > 0:
                entropy -= p * math.log2(p)
        max_entropy = math.log2(max(unique, 2))
        return round(entropy / max(max_entropy, 0.01), 3)

    def record_exploration(self, action: str) -> None:
        self._explored[action] = self._explored.get(action, 0) + 1

    def suggest_exploration(self, available_actions: list[str]) -> dict[str, Any]:
        """Suggest which action to try for exploration."""
        if not available_actions:
            return {"action": "none", "reason": "no_options"}

        # Find least-explored action
        min_explored = float("inf")
        least_explored = available_actions[0]
        for action in available_actions:
            count = self._explored.get(action, 0)
            if count < min_explored:
                min_explored = count
                least_explored = action

        never_tried = [a for a in available_actions if a not in self._explored]

        return {
            "suggest": never_tried[0] if never_tried else least_explored,
            "reason": "never_tried" if never_tried else "least_explored",
            "never_tried": never_tried,
            "exploration_score": self.exploration_score(),
        }

    def track_uncertainty(self, topic: str, confidence: float) -> None:
        """Track what we're uncertain about."""
        if confidence < 0.5:
            self._uncertainties.append({
                "topic": topic,
                "confidence": confidence,
                "timestamp": time.time(),
            })

    def generate_questions(self, products: list[dict],
                           rules: list[dict]) -> list[str]:
        """Generate curious questions about the store."""
        questions = []

        # Products without sales
        no_sales = [p for p in products if int(p.get("inventory_quantity", 0)) == int(p.get("inventory_quantity", 0))]
        if no_sales:
            questions.append("Why are {} products not selling?".format(len(no_sales)))

        # Low margin products
        low_margin = [p for p in products if _margin(p) is not None and _margin(p) < 0.2]
        if low_margin:
            questions.append("Can we improve margins on {} low-margin products?".format(len(low_margin)))

        # No images
        no_images = [p for p in products
                     if not (p.get("images") or p.get("image") or p.get("image_url"))]
        if no_images:
            questions.append("Would adding images to {} products increase conversions?".format(len(no_images)))

        # Rules with low success
        for r in rules:
            if r.get("use_count", 0) > 5 and r.get("success_count", 0) == 0:
                questions.append("Why does rule '{}' never succeed?".format(
                    str(r.get("content", {}))[:40]))

        # Price optimization
        prices = [float(p.get("price", 0)) for p in products if p.get("price")]
        if prices:
            spread = max(prices) / max(min(prices), 0.01)
            if spread > 5:
                questions.append("Is the {:.0f}x price spread intentional?".format(spread))

        self._questions = questions
        return questions

    def get_stats(self) -> dict[str, Any]:
        return {
            "exploration_score": self.exploration_score(),
            "actions_explored": len(self._explored),
            "uncertainties": len(self._uncertainties),
            "questions": len(self._questions),
        }


# ═══════════════════════════════════════════════════════════
# UNIFIED COGNITIVE MODULE
# ═══════════════════════════════════════════════════════════

class CognitiveModule:
    """Unified access to all 6 cognitive capabilities."""

    def __init__(self) -> None:
        self.understanding = DeepUnderstanding()
        self.memory = AssociativeMemory()
        self.reasoning = ReasoningChain()
        self.reflection = SelfReflection()
        self.failure_analysis = FailureChainAnalysis()
        self.curiosity = CuriosityEngine()

    def think_deep(self, products: list[dict], memories: list[dict],
                   rules: list[dict]) -> dict[str, Any]:
        """Run all cognitive capabilities and produce a deep analysis."""

        # C1: Understand each product
        product_insights = [self.understanding.explain_product(p) for p in products[:10]]
        critical = [p for p in product_insights if p["health"] == "critical"]

        # C2: Find similar product clusters
        clusters = []
        if len(products) >= 2:
            for p in products[:5]:
                similar = self.understanding.find_similar(p, products)
                if similar:
                    clusters.append({
                        "product": p.get("name", p.get("title", "")),
                        "similar": [s["name"] for s in similar[:2]],
                    })

        # C3: Reasoning — always generate hypotheses
        hypotheses = []
        good = [p for p in product_insights if p["health"] == "good"]
        needs_attn = [p for p in product_insights if p["health"] != "good"]

        if critical:
            hypotheses.append(self.reasoning.hypothesis(
                "Critical products need immediate attention",
                evidence_for=[p["name"] for p in critical],
                evidence_against=[p["name"] for p in good],
            ))

        # Image hypothesis — always relevant if products lack images
        no_images = [p for p in product_insights if not p.get("has_images")]
        if no_images:
            hypotheses.append(self.reasoning.hypothesis(
                "Adding images will improve conversion rates",
                evidence_for=["{}% products have no images".format(
                    round(len(no_images) / max(len(product_insights), 1) * 100))],
                evidence_against=["no A/B test data yet"] if not rules else [],
            ))

        # Pricing hypothesis
        margins = [p["margin"] for p in product_insights if p.get("margin") is not None]
        if margins:
            low_margin = [p["name"] for p in product_insights
                          if p.get("margin") is not None and p["margin"] < 0.2]
            high_margin = [p["name"] for p in product_insights
                           if p.get("margin") is not None and p["margin"] > 0.5]
            if low_margin:
                hypotheses.append(self.reasoning.hypothesis(
                    "Low-margin products should be repriced or removed",
                    evidence_for=low_margin,
                    evidence_against=high_margin[:2],
                ))

        # Rule effectiveness hypothesis
        if rules:
            used_rules = [r for r in rules if r.get("use_count", 0) > 5]
            success_rules = [r for r in used_rules if r.get("success_count", 0) > 0]
            failed_rules = [r for r in used_rules if r.get("success_count", 0) == 0]
            if used_rules:
                hypotheses.append(self.reasoning.hypothesis(
                    "Learned rules are improving decisions",
                    evidence_for=["rule used {} times with success".format(
                        r.get("use_count", 0)) for r in success_rules[:3]],
                    evidence_against=["rule used {} times, 0 success".format(
                        r.get("use_count", 0)) for r in failed_rules[:3]],
                ))

        # C4: Reflection
        reflection = self.reflection.reflect()

        # C5: Near-miss check on recent memories
        near_misses = 0
        for m in memories[-20:]:
            nm = self.failure_analysis.detect_near_miss(m.get("score", 3.0))
            if nm:
                near_misses += 1

        # C6: Curiosity
        questions = self.curiosity.generate_questions(products, rules)
        exploration = self.curiosity.suggest_exploration(
            ["keep_price", "raise_price", "lower_price", "add_images", "promote"])

        return {
            "understanding": {
                "products_analyzed": len(product_insights),
                "critical": len(critical),
                "clusters": len(clusters),
            },
            "reasoning": {
                "hypotheses": len(hypotheses),
                "hypothesis_list": hypotheses,
                "top_hypothesis": hypotheses[0] if hypotheses else None,
            },
            "reflection": reflection,
            "failure_analysis": {
                "near_misses": near_misses,
                "chains": self.failure_analysis.get_stats(),
            },
            "curiosity": {
                "questions": questions[:5],
                "exploration": exploration,
            },
        }

    def get_stats(self) -> dict[str, Any]:
        return {
            "reflection": self.reflection.reflect(),
            "failure_chains": self.failure_analysis.get_stats(),
            "curiosity": self.curiosity.get_stats(),
        }


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════

def _margin(product: dict):
    from utils.finance import margin as _margin
    price = float(product.get("price", 0))
    cost = float(product.get("cost", 0))
    m = _margin(price, cost, default=-1.0)
    return m if m >= 0 else None

def _to_float(val) -> float:
    if isinstance(val, bool):
        return 1.0 if val else 0.0
    if isinstance(val, (int, float)):
        return float(val)
    return 0.0


# Singleton
_instance: CognitiveModule | None = None

def get_cognitive_module() -> CognitiveModule:
    global _instance
    if _instance is None:
        _instance = CognitiveModule()
    return _instance
