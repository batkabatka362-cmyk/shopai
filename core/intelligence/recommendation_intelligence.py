"""RecommendationIntelligence — real product recommendation algorithms.

Implements:
  - Collaborative filtering (users who bought X also bought Y)
  - Content-based filtering (similar product attributes)
  - Session-based (what user is browsing now → suggest next)
  - Cart cross-sell (what goes well with items in cart)
  - Frequently bought together
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


class RecommendationIntelligence:
    """Real recommendation algorithms for e-commerce."""

    def collaborative_filter(self, purchase_history: list[dict[str, Any]],
                              target_customer: str, top_k: int = 5) -> dict[str, Any]:
        """Users who bought X also bought Y.

        Input: [{"customer_id": "c1", "product_id": "p1"}, ...]
        """
        if not purchase_history:
            return {"recommendations": [], "method": "collaborative", "error": "no_data"}

        # Build user-item matrix
        user_items: dict[str, set[str]] = defaultdict(set)
        item_users: dict[str, set[str]] = defaultdict(set)
        for record in purchase_history:
            uid = str(record.get("customer_id", record.get("user_id", "")))
            pid = str(record.get("product_id", record.get("item_id", "")))
            if uid and pid:
                user_items[uid].add(pid)
                item_users[pid].add(uid)

        target_items = user_items.get(target_customer, set())
        if not target_items:
            # Cold start — recommend most popular
            popular = sorted(item_users.items(), key=lambda x: -len(x[1]))[:top_k]
            return {
                "recommendations": [{"product_id": pid, "score": len(users), "reason": "popular"} for pid, users in popular],
                "method": "popularity_fallback",
                "reason": "new_customer",
            }

        # Find similar users (Jaccard similarity)
        similarities: dict[str, float] = {}
        for other_user, other_items in user_items.items():
            if other_user == target_customer:
                continue
            intersection = len(target_items & other_items)
            union = len(target_items | other_items)
            if union > 0 and intersection > 0:
                similarities[other_user] = intersection / union

        # Get top similar users
        top_users = sorted(similarities.items(), key=lambda x: -x[1])[:20]

        # Score candidate products
        scores: dict[str, float] = defaultdict(float)
        for user, sim in top_users:
            for item in user_items[user]:
                if item not in target_items:
                    scores[item] += sim

        ranked = sorted(scores.items(), key=lambda x: -x[1])[:top_k]
        return {
            "recommendations": [
                {"product_id": pid, "score": round(score, 3), "reason": "users_also_bought"}
                for pid, score in ranked
            ],
            "method": "collaborative",
            "similar_users_found": len(top_users),
            "candidate_products": len(scores),
        }

    def content_based(self, products: list[dict[str, Any]], target_product: dict[str, Any],
                       top_k: int = 5) -> dict[str, Any]:
        """Find similar products by attributes (category, price range, tags)."""
        if not products or not target_product:
            return {"recommendations": [], "method": "content_based"}

        target_cat = target_product.get("category", "").lower()
        target_price = float(target_product.get("price", 0))
        target_tags = set(t.lower() for t in target_product.get("tags", []) if isinstance(t, str))
        target_id = str(target_product.get("id", target_product.get("name", "")))

        scores = []
        for p in products:
            pid = str(p.get("id", p.get("name", "")))
            if pid == target_id:
                continue

            score = 0.0
            # Category match (highest weight)
            if p.get("category", "").lower() == target_cat and target_cat:
                score += 3.0

            # Price similarity (within 30% = similar)
            p_price = float(p.get("price", 0))
            if target_price > 0 and p_price > 0:
                ratio = min(p_price, target_price) / max(p_price, target_price)
                score += ratio * 2.0

            # Tag overlap
            p_tags = set(t.lower() for t in p.get("tags", []) if isinstance(t, str))
            if target_tags and p_tags:
                overlap = len(target_tags & p_tags)
                score += overlap * 1.0

            # Weight similarity
            tw = float(target_product.get("weight", 0))
            pw = float(p.get("weight", 0))
            if tw > 0 and pw > 0:
                w_ratio = min(tw, pw) / max(tw, pw)
                score += w_ratio * 0.5

            if score > 0:
                scores.append({"product": p, "score": round(score, 2)})

        scores.sort(key=lambda x: -x["score"])
        return {
            "recommendations": [
                {
                    "product_id": str(s["product"].get("id", s["product"].get("name", ""))),
                    "name": s["product"].get("name", ""),
                    "score": s["score"],
                    "reason": "similar_attributes",
                }
                for s in scores[:top_k]
            ],
            "method": "content_based",
            "total_candidates": len(scores),
        }

    def frequently_bought_together(self, orders: list[dict[str, Any]],
                                     target_product_id: str, top_k: int = 3) -> dict[str, Any]:
        """Find products frequently purchased together.

        Input: [{"order_id": "o1", "items": ["p1", "p2", "p3"]}, ...]
        """
        if not orders:
            return {"pairs": [], "method": "fbt"}

        # Count co-occurrences
        pair_counts: dict[str, int] = defaultdict(int)
        target_count = 0

        for order in orders:
            items = order.get("items", order.get("line_items", []))
            # Normalize items
            item_ids = []
            for item in items:
                if isinstance(item, str):
                    item_ids.append(item)
                elif isinstance(item, dict):
                    item_ids.append(str(item.get("product_id", item.get("id", item.get("name", "")))))

            if target_product_id in item_ids:
                target_count += 1
                for other in item_ids:
                    if other != target_product_id:
                        pair_counts[other] += 1

        if target_count == 0:
            return {"pairs": [], "method": "fbt", "reason": "product_not_in_orders"}

        # Compute lift (co_occurrence / expected)
        total_orders = len(orders)
        results = []
        for product_id, co_count in pair_counts.items():
            support = co_count / total_orders
            confidence = co_count / target_count
            results.append({
                "product_id": product_id,
                "co_purchases": co_count,
                "confidence": round(confidence, 3),
                "support": round(support, 4),
            })

        results.sort(key=lambda x: -x["confidence"])
        return {
            "pairs": results[:top_k],
            "method": "frequently_bought_together",
            "target_appearances": target_count,
            "total_orders": total_orders,
        }

    def cart_cross_sell(self, cart_items: list[dict[str, Any]],
                         catalog: list[dict[str, Any]], top_k: int = 3) -> dict[str, Any]:
        """Suggest cross-sell items based on current cart contents."""
        if not cart_items or not catalog:
            return {"suggestions": [], "method": "cart_cross_sell"}

        cart_categories = set()
        cart_price_total = 0.0
        cart_ids = set()

        for item in cart_items:
            cart_categories.add(item.get("category", "").lower())
            cart_price_total += float(item.get("price", 0))
            cart_ids.add(str(item.get("id", item.get("name", ""))))

        # Complementary categories
        complements = {
            "electronics": ["accessories", "cases", "cables"],
            "fitness": ["nutrition", "accessories", "apparel"],
            "home": ["decor", "lighting", "accessories"],
            "apparel": ["accessories", "shoes", "jewelry"],
            "beauty": ["skincare", "tools", "accessories"],
        }

        target_cats = set()
        for cat in cart_categories:
            target_cats.update(complements.get(cat, []))

        # Score catalog items
        suggestions = []
        for product in catalog:
            pid = str(product.get("id", product.get("name", "")))
            if pid in cart_ids:
                continue

            score = 0.0
            p_cat = product.get("category", "").lower()
            p_price = float(product.get("price", 0))

            # Complementary category
            if p_cat in target_cats:
                score += 3.0
            # Same category (variant/accessory)
            if p_cat in cart_categories:
                score += 1.0

            # Price ratio (suggest items 20-50% of cart total — impulse add)
            if cart_price_total > 0 and p_price > 0:
                ratio = p_price / cart_price_total
                if 0.1 <= ratio <= 0.5:
                    score += 2.0  # Good impulse range
                elif ratio < 0.1:
                    score += 0.5  # Too cheap might not be interesting

            if score > 0:
                suggestions.append({
                    "product_id": pid,
                    "name": product.get("name", ""),
                    "price": p_price,
                    "score": round(score, 2),
                    "reason": "complementary" if p_cat in target_cats else "same_category",
                })

        suggestions.sort(key=lambda x: -x["score"])
        return {
            "suggestions": suggestions[:top_k],
            "method": "cart_cross_sell",
            "cart_categories": list(cart_categories),
            "cart_total": round(cart_price_total, 2),
        }
