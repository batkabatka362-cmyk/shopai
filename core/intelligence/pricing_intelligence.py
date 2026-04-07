"""PricingIntelligence — real e-commerce pricing computation.

Not placeholder — actual algorithms:
  - Demand curve estimation from sales history
  - Optimal price calculation (maximize revenue or profit)
  - Competitor price response strategy
  - A/B price test analysis with statistical significance
  - Price sensitivity by customer segment
  - LLM-backed pricing recommendations (NEW)

The deterministic algorithms always run. The LLM layer is OPTIONAL
and called via `recommend_with_llm()` — when no LLM is wired, the
heuristic computations are returned with a "no LLM" note.
"""
from __future__ import annotations

import math
from typing import Any, Optional


class PricingIntelligence:
    """Real pricing algorithms for e-commerce."""

    def __init__(self, *, llm: Any = None) -> None:
        self._llm = llm

    def compute_demand_curve(self, sales_history: list[dict[str, Any]]) -> dict[str, Any]:
        """Estimate demand curve from historical price-quantity data.

        Input: [{"price": 29.99, "units_sold": 150, "period": "2024-01"}, ...]
        Output: demand curve parameters, optimal price point, elasticity
        """
        if not sales_history or len(sales_history) < 3:
            return {"error": "Need at least 3 price-quantity data points"}

        prices = [float(s.get("price", 0)) for s in sales_history if s.get("price")]
        quantities = [float(s.get("units_sold", s.get("quantity", 0))) for s in sales_history if s.get("price")]

        if len(prices) < 3 or len(prices) != len(quantities):
            return {"error": "Insufficient price-quantity pairs"}

        # Log-linear demand estimation: ln(Q) = a - b*ln(P)
        # This gives constant elasticity model
        ln_prices = [math.log(max(p, 0.01)) for p in prices]
        ln_quantities = [math.log(max(q, 0.01)) for q in quantities]

        n = len(ln_prices)
        sum_x = sum(ln_prices)
        sum_y = sum(ln_quantities)
        sum_xy = sum(x * y for x, y in zip(ln_prices, ln_quantities))
        sum_x2 = sum(x * x for x in ln_prices)

        denom = n * sum_x2 - sum_x * sum_x
        if abs(denom) < 1e-10:
            return {"error": "Cannot estimate — prices too similar"}

        b = (n * sum_xy - sum_x * sum_y) / denom  # elasticity coefficient
        a = (sum_y - b * sum_x) / n

        # Elasticity
        elasticity = b  # For log-linear model, b IS the elasticity

        # R-squared (goodness of fit)
        mean_y = sum_y / n
        ss_tot = sum((y - mean_y) ** 2 for y in ln_quantities)
        ss_res = sum((y - (a + b * x)) ** 2 for x, y in zip(ln_prices, ln_quantities))
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

        # Optimal price (maximize revenue = P * Q)
        # For log-linear: Revenue = P * exp(a) * P^b = exp(a) * P^(1+b)
        # dR/dP = 0 when (1+b)*P^b = 0, but if b < -1: P_opt doesn't exist (always decrease price)
        # If -1 < b < 0: optimal is to increase price (inelastic)
        # Practical: use current best-performing price
        revenue_by_price = [(p, p * q) for p, q in zip(prices, quantities)]
        best_price, best_revenue = max(revenue_by_price, key=lambda x: x[1])

        # Price sensitivity zones
        avg_price = sum(prices) / len(prices)
        zones = {
            "sweet_spot": round(best_price, 2),
            "discount_floor": round(avg_price * 0.7, 2),
            "premium_ceiling": round(avg_price * 1.5, 2),
        }

        return {
            "elasticity": round(elasticity, 3),
            "elasticity_type": "elastic" if abs(elasticity) > 1 else "inelastic",
            "intercept": round(a, 4),
            "r_squared": round(r_squared, 4),
            "model_fit": "good" if r_squared > 0.7 else "moderate" if r_squared > 0.4 else "poor",
            "optimal_price": round(best_price, 2),
            "max_revenue_observed": round(best_revenue, 2),
            "price_sensitivity_zones": zones,
            "data_points": n,
            "price_range": [round(min(prices), 2), round(max(prices), 2)],
            "quantity_range": [round(min(quantities)), round(max(quantities))],
            "interpretation": self._interpret_elasticity(elasticity),
        }

    def optimal_price_for_profit(self, cost: float, prices: list[float], quantities: list[float]) -> dict[str, Any]:
        """Find price that maximizes PROFIT (not just revenue)."""
        if not prices or len(prices) != len(quantities):
            return {"error": "Need matching price-quantity arrays"}

        profits = [(p, (p - cost) * q, q) for p, q in zip(prices, quantities)]
        best = max(profits, key=lambda x: x[1])

        return {
            "optimal_price": round(best[0], 2),
            "expected_units": round(best[2]),
            "expected_profit": round(best[1], 2),
            "expected_revenue": round(best[0] * best[2], 2),
            "margin_at_optimal": round((best[0] - cost) / best[0] * 100, 1),
            "cost": cost,
            "profit_by_price": [
                {"price": round(p, 2), "profit": round(pr, 2), "units": round(q)}
                for p, pr, q in sorted(profits, key=lambda x: -x[1])[:5]
            ],
        }

    def competitor_response(self, our_price: float, our_cost: float,
                            competitors: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyze competitive position and suggest response strategy."""
        if not competitors:
            return {"position": "no_data", "strategy": "maintain"}

        comp_prices = [float(c.get("price", 0)) for c in competitors if c.get("price")]
        if not comp_prices:
            return {"position": "no_data", "strategy": "maintain"}

        avg_comp = sum(comp_prices) / len(comp_prices)
        min_comp = min(comp_prices)
        max_comp = max(comp_prices)
        our_margin = (our_price - our_cost) / our_price * 100 if our_price > 0 else 0

        # Price index (100 = at parity)
        price_index = round(our_price / avg_comp * 100, 1) if avg_comp > 0 else 100

        # Strategy
        if price_index < 85:
            strategy = "value_leader"
            action = "Maintain low price — you're the value option"
        elif price_index < 95:
            strategy = "competitive"
            action = "Slight premium possible — strong value position"
        elif price_index < 105:
            strategy = "at_parity"
            action = "Differentiate on value-adds, not price"
        elif price_index < 120:
            strategy = "premium"
            action = "Justify premium with quality/brand — or consider price reduction"
        else:
            strategy = "overpriced"
            action = f"Price {price_index - 100:.0f}% above market — risk of losing customers"

        # Undercutting analysis
        undercut_price = round(min_comp * 0.95, 2)
        undercut_margin = round((undercut_price - our_cost) / undercut_price * 100, 1) if undercut_price > 0 else 0

        return {
            "our_price": our_price,
            "competitor_avg": round(avg_comp, 2),
            "competitor_min": round(min_comp, 2),
            "competitor_max": round(max_comp, 2),
            "competitor_count": len(comp_prices),
            "price_index": price_index,
            "position": strategy,
            "our_margin_pct": round(our_margin, 1),
            "recommended_action": action,
            "undercut_price": undercut_price,
            "undercut_margin": undercut_margin,
            "undercut_viable": undercut_margin >= 15,
        }

    def ab_test_analysis(self, variant_a: dict[str, Any], variant_b: dict[str, Any]) -> dict[str, Any]:
        """Analyze A/B price test results with statistical significance.

        Input: {"price": 29.99, "visitors": 1000, "conversions": 50, "revenue": 1499.50}
        """
        conv_a = int(variant_a.get("conversions", 0))
        vis_a = int(variant_a.get("visitors", 1))
        conv_b = int(variant_b.get("conversions", 0))
        vis_b = int(variant_b.get("visitors", 1))

        rate_a = conv_a / vis_a if vis_a > 0 else 0
        rate_b = conv_b / vis_b if vis_b > 0 else 0

        # Revenue per visitor
        rpv_a = float(variant_a.get("revenue", 0)) / vis_a if vis_a > 0 else 0
        rpv_b = float(variant_b.get("revenue", 0)) / vis_b if vis_b > 0 else 0

        # Z-test for conversion rate difference
        pooled_rate = (conv_a + conv_b) / (vis_a + vis_b) if (vis_a + vis_b) > 0 else 0
        se = math.sqrt(pooled_rate * (1 - pooled_rate) * (1/max(vis_a, 1) + 1/max(vis_b, 1))) if pooled_rate > 0 else 0
        z_score = (rate_a - rate_b) / se if se > 0 else 0

        # Approximate p-value (two-tailed)
        # Using normal approximation
        abs_z = abs(z_score)
        if abs_z > 3.29: p_value = 0.001
        elif abs_z > 2.58: p_value = 0.01
        elif abs_z > 1.96: p_value = 0.05
        elif abs_z > 1.65: p_value = 0.10
        else: p_value = 0.20

        significant = p_value < 0.05
        lift = ((rate_b - rate_a) / rate_a * 100) if rate_a > 0 else 0

        winner = "B" if rpv_b > rpv_a and significant else "A" if rpv_a > rpv_b and significant else "no_winner"

        return {
            "variant_a": {
                "price": variant_a.get("price"),
                "conversion_rate": round(rate_a * 100, 2),
                "revenue_per_visitor": round(rpv_a, 4),
                "total_revenue": variant_a.get("revenue", 0),
            },
            "variant_b": {
                "price": variant_b.get("price"),
                "conversion_rate": round(rate_b * 100, 2),
                "revenue_per_visitor": round(rpv_b, 4),
                "total_revenue": variant_b.get("revenue", 0),
            },
            "lift_pct": round(lift, 2),
            "z_score": round(z_score, 3),
            "p_value": p_value,
            "significant": significant,
            "confidence": f"{(1 - p_value) * 100:.0f}%",
            "winner": winner,
            "recommendation": self._ab_recommendation(winner, variant_a, variant_b, significant),
            "sample_size_adequate": (vis_a + vis_b) >= 1000,
        }

    @staticmethod
    def _interpret_elasticity(e: float) -> str:
        if abs(e) < 0.5: return "Very inelastic — large price changes cause small demand changes. Strong pricing power."
        if abs(e) < 1.0: return "Inelastic — demand relatively insensitive to price. Can increase prices."
        if abs(e) < 1.5: return "Unit elastic — price and demand change proportionally. Price carefully."
        if abs(e) < 2.5: return "Elastic — customers are price sensitive. Compete on price or differentiate."
        return "Very elastic — small price changes cause large demand swings. Price-driven market."

    @staticmethod
    def _ab_recommendation(winner: str, a: dict, b: dict, sig: bool) -> str:
        if not sig:
            return "No statistically significant difference. Run test longer or with more traffic."
        if winner == "B":
            return f"Implement variant B (${b.get('price')}) — higher revenue per visitor with {'>95%' if sig else '<95%'} confidence."
        if winner == "A":
            return f"Keep variant A (${a.get('price')}) — performs better with statistical significance."
        return "Results inconclusive. Consider testing different price points."

    # ── LLM-backed pricing recommendation ─────────────────────

    def recommend_with_llm(
        self,
        product: dict[str, Any],
        *,
        recent_sales: Optional[list[dict]] = None,
        competitor_prices: Optional[list[float]] = None,
    ) -> dict[str, Any]:
        """Ask the LLM for a concrete pricing recommendation.

        Combines:
            - the deterministic competitor_response analysis
            - the LLM's reasoning over the same numbers + product context

        Returns:
            {
                "heuristic": <competitor_response output>,
                "llm": {action, new_price, delta_pct, reasoning,
                        confidence, risks} or {"error": ...},
                "source": "llm" | "heuristic_only",
            }

        When no LLM is wired, returns the heuristic result with
        source="heuristic_only" so callers always get an answer.
        """
        from utils.finance import margin_pct

        price = float(product.get("price", 0) or 0)
        cost = float(product.get("cost", 0) or 0)
        margin = margin_pct(price, cost, require_cost=False)

        # Always run the heuristic
        comp_dicts = [
            {"price": p} for p in (competitor_prices or [])
        ]
        heuristic = self.competitor_response(price, cost, comp_dicts)

        result: dict[str, Any] = {
            "heuristic": heuristic,
            "llm": None,
            "source": "heuristic_only",
        }

        llm = self._get_llm()
        if llm is None:
            return result
        try:
            if not llm.is_available():
                return result
        except Exception:  # noqa: BLE001
            return result

        try:
            from core.system.prompt_library import get_prompt
        except Exception:  # noqa: BLE001
            return result

        template = get_prompt("decision.pricing_recommendation")
        if template is None:
            return result

        rendered = template.render(
            product_name=product.get("name", product.get("title", "Unknown")),
            price=price,
            cost=cost,
            margin_pct=round(margin, 1),
            recent_sales=len(recent_sales or []),
            competitor_prices=", ".join(
                f"${p:.2f}" for p in (competitor_prices or [])
            ) or "(none)",
        )

        try:
            structured = llm.ask_structured(
                role=template.role,
                prompt=rendered.user,
                system_prompt=rendered.system,
                schema_hint=template.schema_hint,
            )
        except Exception as exc:  # noqa: BLE001
            result["llm"] = {"error": str(exc)[:200]}
            return result

        if not getattr(structured, "ok", False):
            result["llm"] = {"error": structured.error or "unparseable"}
            return result

        data = structured.data or {}
        # Normalize the LLM response shape
        try:
            llm_response = {
                "action": str(data.get("action", "hold")),
                "new_price": float(data.get("new_price", price)),
                "delta_pct": float(data.get("delta_pct", 0)),
                "reasoning": str(data.get("reasoning", ""))[:500],
                "confidence": max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
                "risks": list(data.get("risks", []))[:5],
            }
            result["llm"] = llm_response
            result["source"] = "llm"
        except (TypeError, ValueError) as exc:
            result["llm"] = {"error": f"normalization failed: {exc}"}
        return result

    def _get_llm(self) -> Any:
        """Lazily resolve the LLM adapter."""
        if self._llm is not None:
            return self._llm
        try:
            from core.system.llm_adapter import get_llm
            return get_llm()
        except Exception:  # noqa: BLE001
            return None
