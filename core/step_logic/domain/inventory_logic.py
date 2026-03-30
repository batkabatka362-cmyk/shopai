"""InventoryLogic — deep business logic for inventory/supply chain engines."""
from __future__ import annotations

import math
from typing import Any


class InventoryLogic:
    """Real inventory and supply chain computations."""

    INVENTORY_ENGINES = {
        "inventory", "stock_prediction", "demand_forecasting", "supply_chain",
        "warehouse_optimization", "inventory_optimization", "inventory_alerts",
        "inventory_forecasting", "safety_stock", "reorder_point", "eoq_calculator",
        "abc_analysis", "cycle_counting", "demand_planning", "demand_sensing",
    }

    def applies_to(self, engine_name: str) -> bool:
        return engine_name in self.INVENTORY_ENGINES

    def analyze(self, data: dict[str, Any]) -> dict[str, Any]:
        result = {}
        items = self._get_items(data)

        if items:
            result["inventory_analysis"] = self._analyze_inventory(items)
            result["abc_classification"] = self._abc_classify(items)
            result["stockout_risks"] = self._detect_stockout_risks(items)
            result["overstock_items"] = self._detect_overstock(items)
            result["score"] = self._inventory_health(result)
            result["decision"] = "approve" if result["score"] >= 5 else "reject"
            result["reason"] = self._inventory_reason(result)

        return result

    def execute(self, data: dict[str, Any]) -> dict[str, Any]:
        result = {}
        items = self._get_items(data)

        if items:
            result["reorder_recommendations"] = self._recommend_reorders(items)
            result["safety_stock_levels"] = self._calculate_safety_stock(items)
            result["eoq_calculations"] = self._calculate_eoq(items)
            result["inventory_health"] = self._health_summary(items)
            result["generated"] = True

        return result

    def _analyze_inventory(self, items: list[dict]) -> dict:
        stocks = [int(i.get("stock", i.get("quantity", 0))) for i in items]
        values = [float(i.get("stock", 0)) * float(i.get("cost", i.get("price", 0))) for i in items]

        return {
            "total_skus": len(items),
            "total_units": sum(stocks),
            "total_value": round(sum(values), 2),
            "avg_stock": round(sum(stocks) / len(stocks), 1) if stocks else 0,
            "zero_stock": sum(1 for s in stocks if s == 0),
            "low_stock": sum(1 for s in stocks if 0 < s < 10),
        }

    def _abc_classify(self, items: list[dict]) -> dict:
        valued = []
        for i in items:
            revenue = float(i.get("revenue", 0)) or float(i.get("stock", 0)) * float(i.get("price", 0))
            valued.append({"name": i.get("name", "unknown"), "revenue": revenue})

        valued.sort(key=lambda x: x["revenue"], reverse=True)
        total = sum(v["revenue"] for v in valued) or 1

        cumulative = 0
        a_items, b_items, c_items = [], [], []
        for v in valued:
            cumulative += v["revenue"]
            pct = cumulative / total * 100
            if pct <= 80:
                a_items.append(v["name"])
            elif pct <= 95:
                b_items.append(v["name"])
            else:
                c_items.append(v["name"])

        return {"A": a_items, "B": b_items, "C": c_items, "A_count": len(a_items), "B_count": len(b_items), "C_count": len(c_items)}

    def _detect_stockout_risks(self, items: list[dict]) -> list[dict]:
        risks = []
        for i in items:
            stock = int(i.get("stock", i.get("quantity", 0)))
            daily_sales = float(i.get("daily_sales", i.get("velocity", 0)))
            lead_time = int(i.get("lead_time", i.get("lead_time_days", 7)))

            if daily_sales > 0:
                days_left = stock / daily_sales
                if days_left < lead_time * 1.5:
                    risks.append({
                        "name": i.get("name", "unknown"),
                        "stock": stock,
                        "days_of_supply": round(days_left, 1),
                        "lead_time": lead_time,
                        "urgency": "critical" if days_left < lead_time else "warning",
                    })
        return risks

    def _detect_overstock(self, items: list[dict]) -> list[dict]:
        overstock = []
        for i in items:
            stock = int(i.get("stock", i.get("quantity", 0)))
            daily_sales = float(i.get("daily_sales", i.get("velocity", 0)))
            if daily_sales > 0 and stock / daily_sales > 90:
                overstock.append({
                    "name": i.get("name", "unknown"),
                    "stock": stock,
                    "days_of_supply": round(stock / daily_sales, 0),
                    "excess_units": int(stock - daily_sales * 60),
                })
        return overstock

    def _recommend_reorders(self, items: list[dict]) -> list[dict]:
        recs = []
        for i in items:
            stock = int(i.get("stock", i.get("quantity", 0)))
            daily_sales = float(i.get("daily_sales", i.get("velocity", 1)))
            lead_time = int(i.get("lead_time", i.get("lead_time_days", 7)))
            safety = int(daily_sales * 3)
            rop = math.ceil(daily_sales * lead_time + safety)

            if stock <= rop:
                order_qty = max(int(daily_sales * 30), rop - stock + safety)
                recs.append({
                    "name": i.get("name", "unknown"),
                    "current_stock": stock,
                    "reorder_point": rop,
                    "recommended_qty": order_qty,
                    "urgency": "immediate" if stock < safety else "soon",
                })
        return recs

    def _calculate_safety_stock(self, items: list[dict]) -> list[dict]:
        results = []
        for i in items:
            daily_sales = float(i.get("daily_sales", i.get("velocity", 1)))
            lead_time = int(i.get("lead_time", 7))
            service_level_z = 1.65  # 95% service level
            demand_std = daily_sales * 0.3  # Assume 30% variability

            safety = math.ceil(service_level_z * demand_std * math.sqrt(lead_time))
            results.append({"name": i.get("name", "unknown"), "safety_stock": safety, "service_level": "95%"})
        return results

    def _calculate_eoq(self, items: list[dict]) -> list[dict]:
        results = []
        for i in items:
            annual_demand = float(i.get("daily_sales", 1)) * 365
            order_cost = float(i.get("order_cost", 25))
            holding_cost = float(i.get("holding_cost", float(i.get("cost", 10)) * 0.25))

            if holding_cost > 0:
                eoq = round(math.sqrt(2 * annual_demand * order_cost / holding_cost))
                orders_per_year = math.ceil(annual_demand / max(eoq, 1))
                results.append({
                    "name": i.get("name", "unknown"),
                    "eoq": eoq,
                    "orders_per_year": orders_per_year,
                    "annual_demand": round(annual_demand),
                })
        return results

    def _health_summary(self, items: list[dict]) -> dict:
        total = len(items)
        zero = sum(1 for i in items if int(i.get("stock", 0)) == 0)
        low = sum(1 for i in items if 0 < int(i.get("stock", 0)) < 10)
        return {
            "total_skus": total,
            "in_stock": total - zero,
            "out_of_stock": zero,
            "low_stock": low,
            "health_pct": round((total - zero - low) / total * 100, 1) if total else 0,
        }

    def _inventory_health(self, analysis: dict) -> float:
        score = 7.0
        inv = analysis.get("inventory_analysis", {})
        if inv.get("zero_stock", 0) > 0: score -= 2
        if inv.get("low_stock", 0) > 3: score -= 1
        risks = analysis.get("stockout_risks", [])
        if any(r.get("urgency") == "critical" for r in risks): score -= 2
        return max(round(score, 1), 0)

    def _inventory_reason(self, analysis: dict) -> str:
        inv = analysis.get("inventory_analysis", {})
        risks = len(analysis.get("stockout_risks", []))
        return f"{inv.get('total_skus', 0)} SKUs, {inv.get('zero_stock', 0)} OOS, {risks} stockout risks"

    @staticmethod
    def _get_items(data: dict) -> list[dict]:
        for key in ("inventory_data", "products", "product_data", "items", "stock_data"):
            val = data.get(key, [])
            if isinstance(val, list) and val: return val
            if isinstance(val, dict): return [val]
        return []
