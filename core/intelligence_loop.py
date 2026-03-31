"""IntelligenceLoop — the BRAIN of ShopAI.

ONE connected loop: Data → Decision → Execution → Result → Learning → Better Decision

This is NOT separate modules — it's ONE flow where each stage
feeds into the next, and outcomes feed BACK into decisions.

The key insight:
  - Good data → smart decision → effective execution → real results → system learns → BETTER decisions
  - Bad data at ANY stage → everything downstream fails
  - Learning MUST flow back to decisions or system never improves
"""
from __future__ import annotations

import copy
import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id, safe_float, safe_int, safe_dict

logger = get_logger("intelligence_loop")


class IntelligenceLoop:
    """Complete closed intelligence loop. Every stage connects to the next."""

    # Scoring weight adjustments from learning (class-level, persists across instances)
    _weight_adjustments: dict[str, float] = {}

    def __init__(self) -> None:
        self._history: list[dict[str, Any]] = []

    def run(self, raw_data: dict[str, Any], goal: str = "maximize_profit") -> dict[str, Any]:
        """Run the FULL intelligence loop on any data.

        Stages:
          1. CLEAN   — validate, fix, score data quality
          2. ANALYZE — compute scores, detect patterns, assess opportunity
          3. DECIDE  — rank options, apply learning, set confidence
          4. PLAN    — create specific executable actions
          5. EXECUTE — format for target systems (Shopify, email, ads)
          6. TRACK   — record what was decided and why
          7. LEARN   — compare with past outcomes, adjust weights

        Every stage gets the output of ALL previous stages.
        Learning from stage 7 feeds back into stage 3 next time.
        """
        loop_id = generate_id("loop")
        start = time.monotonic()
        context = {"loop_id": loop_id, "goal": goal, "raw_data": raw_data}

        # Stage 1: CLEAN
        clean_result = self._stage_clean(raw_data)
        context["clean"] = clean_result

        if clean_result["quality_score"] < 20:
            return self._abort(loop_id, "Data quality too low", clean_result, start)

        # Stage 2: ANALYZE
        analysis = self._stage_analyze(clean_result["data"], goal)
        context["analysis"] = analysis

        # Stage 3: DECIDE (uses learning from past outcomes)
        decision = self._stage_decide(analysis, goal)
        context["decision"] = decision

        # Stage 4: PLAN
        plan = self._stage_plan(decision, clean_result["data"])
        context["plan"] = plan

        # Stage 5: EXECUTE (format for target systems)
        execution = self._stage_execute(plan, clean_result["data"])
        context["execution"] = execution

        # Stage 6: TRACK
        self._stage_track(loop_id, context)

        # Stage 7: LEARN
        learning = self._stage_learn(loop_id, decision)
        context["learning"] = learning

        elapsed = time.monotonic() - start

        result = {
            "loop_id": loop_id,
            "goal": goal,
            "elapsed_seconds": round(elapsed, 3),
            "data_quality": clean_result["quality_score"],
            "decision": {
                "action": decision["recommended_action"],
                "confidence": decision["confidence"],
                "reason": decision["reason"],
            },
            "plan": {
                "actions": len(plan["actions"]),
                "priority_1": [a for a in plan["actions"] if a["priority"] == 1],
            },
            "execution": {
                "ready_actions": len(execution["ready"]),
                "targets": list(set(a["target"] for a in execution["ready"])),
            },
            "learning": {
                "past_outcomes": learning["past_outcomes"],
                "adjusted": learning["adjustments_made"],
                "advice": learning["advice"],
            },
            "stages_completed": 7,
            "summary": self._summarize(decision, plan, execution, learning, elapsed),
        }

        self._history.append(result)
        return result

    # ── Stage 1: CLEAN ──────────────────────────────────────

    def _stage_clean(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Validate, fix types, remove noise, score quality."""
        data = copy.deepcopy(raw)
        fixes = []
        issues = []

        # Fix string prices at top level
        for key in list(data.keys()):
            if key.startswith("_"):
                continue
            val = data[key]

            # Fix string numbers
            if isinstance(val, str) and key.lower() in ("price", "cost", "revenue", "spend", "budget"):
                converted = safe_float(val, default=None)
                if converted is not None:
                    data[key] = converted
                    fixes.append(f"{key}: string→float")
                else:
                    issues.append(f"{key}: invalid number '{val}'")

            # Fix list items
            if isinstance(val, list):
                cleaned = []
                for item in val:
                    if isinstance(item, dict):
                        for k in ("price", "cost", "total", "spend"):
                            if k in item and isinstance(item[k], str):
                                converted = safe_float(item[k], default=None)
                                if converted is not None:
                                    item[k] = converted
                                    fixes.append(f"{key}[].{k}: string→float")
                        if item.get("name") or item.get("id") or item.get("title"):
                            cleaned.append(item)
                        else:
                            issues.append(f"{key}: item without name/id removed")
                    elif item is not None:
                        cleaned.append(item)
                data[key] = cleaned

            # Remove None/empty
            if val is None or val == "" or val == []:
                del data[key]
                fixes.append(f"{key}: removed empty")

        # Business logic validation
        biz_issues = []
        for key in ("products", "product_data"):
            items = data.get(key, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_price = safe_float(item.get("price"))
                item_cost = safe_float(item.get("cost"))
                item_name = item.get("name", item.get("title", "?"))

                if item_price < 0:
                    biz_issues.append(f"{item_name}: negative price ({item_price})")
                    issues.append(f"Negative price: {item_price}")
                if item_cost < 0:
                    biz_issues.append(f"{item_name}: negative cost ({item_cost})")
                    issues.append(f"Negative cost: {item_cost}")
                if item_cost > 0 and item_price > 0 and item_cost > item_price:
                    biz_issues.append(f"{item_name}: cost ({item_cost}) > price ({item_price})")
                    issues.append(f"Cost exceeds price: {item_cost} > {item_price}")

        # Quality score
        total_fields = len([k for k in data if not k.startswith("_")])
        non_empty = sum(1 for k, v in data.items() if not k.startswith("_") and v)
        has_products = bool(data.get("products") or data.get("product_data"))
        has_numbers = any(isinstance(v, (int, float)) for v in data.values())

        quality = 0
        if total_fields > 0:
            quality += min(40, non_empty / total_fields * 40)
        if has_products:
            quality += 30
        if has_numbers:
            quality += 15
        if not issues:
            quality += 15

        # Penalize for business logic violations
        if biz_issues:
            penalty = min(50, len(biz_issues) * 25)
            quality = max(0, quality - penalty)

        return {
            "data": data,
            "quality_score": round(quality),
            "quality_grade": "A" if quality >= 80 else "B" if quality >= 60 else "C" if quality >= 40 else "F",
            "fixes": fixes,
            "issues": issues,
            "fields": total_fields,
        }

    # ── Stage 2: ANALYZE ────────────────────────────────────

    def _stage_analyze(self, data: dict[str, Any], goal: str) -> dict[str, Any]:
        """Compute scores, detect patterns, assess opportunity."""
        analysis = {"goal": goal, "findings": []}

        # Product analysis
        products = data.get("products", data.get("product_data", []))
        if isinstance(products, list) and products:
            from core.step_logic.smart_executor import SmartExecutor
            se = SmartExecutor()
            scored = se._score_products(products)
            viable = [p for p in scored if p.get("viable")]
            top = sorted(scored, key=lambda p: p.get("total_score", 0), reverse=True)

            analysis["products"] = {
                "total": len(products),
                "viable": len(viable),
                "top_product": top[0] if top else {},
                "avg_score": round(sum(p.get("total_score", 0) for p in scored) / max(len(scored), 1), 2),
                "scored": scored,
            }

            if viable:
                analysis["findings"].append(f"{len(viable)}/{len(products)} products viable")
            if top and top[0].get("total_score", 0) > 8:
                analysis["findings"].append(f"Strong candidate: {top[0].get('name')} (score {top[0]['total_score']})")

        # Customer analysis — safe type conversion
        customers = data.get("customer_data", data.get("customers", []))
        if isinstance(customers, list) and customers:
            repeat = sum(1 for c in customers if isinstance(c, dict) and safe_int(c.get("orders")) > 1)
            at_risk = sum(1 for c in customers if isinstance(c, dict) and safe_int(c.get("days_since_last_order")) > 60)
            analysis["customers"] = {
                "total": len(customers),
                "repeat_rate": round(repeat / max(len(customers), 1) * 100, 1),
                "at_risk": at_risk,
            }
            if at_risk > 0:
                analysis["findings"].append(f"{at_risk} customers at churn risk")

        # Revenue analysis — safe type conversion
        orders = data.get("orders", data.get("order_data", []))
        if isinstance(orders, list) and orders:
            revenue = sum(safe_float(o.get("total", o.get("amount", o.get("total_price", 0)))) for o in orders if isinstance(o, dict))
            aov = revenue / max(len(orders), 1)
            analysis["revenue"] = {"total": round(revenue, 2), "orders": len(orders), "aov": round(aov, 2)}
            if aov < 30:
                analysis["findings"].append(f"Low AOV ${aov:.2f} — upsell/bundle opportunity")

        analysis["opportunity_score"] = self._calc_opportunity(analysis)
        return analysis

    # ── Stage 3: DECIDE ─────────────────────────────────────

    def _stage_decide(self, analysis: dict[str, Any], goal: str) -> dict[str, Any]:
        """Rank options, apply learning from past outcomes, set confidence."""

        past_advice = self._get_past_learning(goal)

        opp_score = analysis.get("opportunity_score", 50)
        products = analysis.get("products", {})
        customers = analysis.get("customers", {})
        findings = analysis.get("findings", [])

        # Decision logic based on goal
        if goal == "maximize_profit":
            if products.get("viable", 0) > 0:
                top = safe_dict(products.get("top_product"))
                action = f"Launch {top.get('name', 'top product')} — score {top.get('total_score', 0)}"
                confidence = "high" if safe_float(top.get("total_score")) > 7 else "medium"
            else:
                action = "No viable products — improve margins or find new products"
                confidence = "low"

        elif goal == "grow_customers":
            if customers.get("at_risk", 0) > 0:
                action = f"Retain {customers['at_risk']} at-risk customers with win-back campaign"
                confidence = "high"
            elif customers.get("repeat_rate", 0) < 30:
                action = "Low repeat rate — launch loyalty program"
                confidence = "medium"
            else:
                action = "Customer base healthy — focus on acquisition"
                confidence = "medium"

        elif goal == "increase_aov":
            revenue = analysis.get("revenue", {})
            if safe_float(revenue.get("aov")) < 50:
                action = f"AOV ${safe_float(revenue.get('aov')):.2f} — implement bundle offers and upsells"
                confidence = "high"
            else:
                action = "AOV acceptable — test premium product line"
                confidence = "medium"
        else:
            action = f"Analyze and optimize for: {goal}"
            confidence = "medium"

        # Apply past learning adjustments
        if past_advice.get("avoid_below_score"):
            threshold = past_advice["avoid_below_score"]
            top_score = safe_float(safe_dict(products.get("top_product")).get("total_score"), 10)
            if top_score < threshold:
                action = f"CAUTION: Past data shows scores below {threshold} fail. " + action
                confidence = "low"

        reason_parts = findings[:3]
        if past_advice.get("success_rate"):
            reason_parts.append(f"Past success rate: {past_advice['success_rate']:.0%}")

        return {
            "recommended_action": action,
            "confidence": confidence,
            "reason": " | ".join(reason_parts) if reason_parts else "Standard analysis",
            "opportunity_score": opp_score,
            "goal": goal,
            "past_learning_applied": bool(past_advice.get("success_rate")),
        }

    # ── Stage 4: PLAN ───────────────────────────────────────

    def _stage_plan(self, decision: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        """Create specific, executable actions from decision."""
        actions = []
        confidence = decision.get("confidence", "medium")

        products = data.get("products", data.get("product_data", []))
        customers = data.get("customer_data", data.get("customers", []))

        if isinstance(products, list) and products:
            actions.append({
                "type": "pricing_analysis", "priority": 1,
                "description": "Run pricing intelligence on all products",
                "target": "pricing_engine",
                "data_needed": "products",
            })
            actions.append({
                "type": "seo_audit", "priority": 2,
                "description": "Audit product pages for SEO issues",
                "target": "seo_engine",
                "data_needed": "products",
            })
            actions.append({
                "type": "content_check", "priority": 2,
                "description": "Generate/improve product descriptions",
                "target": "content_engine",
                "data_needed": "products",
            })

        if isinstance(customers, list) and customers:
            actions.append({
                "type": "segment_customers", "priority": 1,
                "description": "Segment customers by RFM and detect churn risks",
                "target": "customer_engine",
                "data_needed": "customers",
            })

        # Goal-specific actions
        recommended = decision.get("recommended_action", "").lower()
        if "launch" in recommended:
            actions.append({
                "type": "product_launch", "priority": 1,
                "description": "Execute product launch workflow",
                "target": "workflow_engine",
                "data_needed": "products",
            })

        if "win-back" in recommended:
            actions.append({
                "type": "win_back_email", "priority": 1,
                "description": "Create and send win-back email campaign",
                "target": "email_engine",
                "data_needed": "customers",
            })

        if "bundle" in recommended or "upsell" in recommended:
            actions.append({
                "type": "bundle_strategy", "priority": 1,
                "description": "Create bundle/upsell offers to increase AOV",
                "target": "pricing_engine",
                "data_needed": "products",
            })

        # Deprioritize if low confidence
        if confidence == "low":
            for a in actions:
                a["priority"] = max(a["priority"], 2)
            actions.append({
                "type": "gather_more_data", "priority": 1,
                "description": "Low confidence — collect more data before major actions",
                "target": "data_engine",
                "data_needed": "all",
            })

        actions.sort(key=lambda a: a["priority"])
        return {"actions": actions, "total": len(actions)}

    # ── Stage 5: EXECUTE ────────────────────────────────────

    def _stage_execute(self, plan: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        """Format actions for target systems — ready to send."""
        ready = []
        products = data.get("products", data.get("product_data", []))
        products_valid = isinstance(products, list) and products and isinstance(products[0], dict)

        for action in plan["actions"]:
            target = action["target"]
            formatted = {
                "action_type": action["type"],
                "priority": action["priority"],
                "target": target,
                "description": action["description"],
                "status": "ready",
            }

            try:
                if target == "pricing_engine" and products_valid:
                    formatted["payload"] = {"engine": "pricing", "data": {"products": products[:10]}}

                elif target == "email_engine":
                    from core.intelligence.email_intelligence import EmailIntelligence
                    flow = EmailIntelligence().build_automation_flow("win_back")
                    formatted["payload"] = {"flow": flow["name"], "emails": len(flow["emails"])}
                    formatted["estimated_impact"] = flow.get("estimated_recovery", "3-8%")

                elif target == "seo_engine" and products_valid:
                    from core.intelligence.seo_intelligence import SEOIntelligence
                    p0 = products[0]
                    audit = SEOIntelligence().audit_page({
                        "title": p0.get("name", ""),
                        "keyword": p0.get("category", "product"),
                    })
                    formatted["payload"] = {"audit_score": audit["score"], "issues": audit["issue_count"]}

                elif target == "content_engine" and products_valid:
                    from core.intelligence.content_generator import ContentGenerator
                    desc = ContentGenerator().product_description(products[0])
                    formatted["payload"] = {"headline": desc["headline"][:60], "bullets": len(desc["bullet_points"])}

            except Exception as exc:
                formatted["payload_error"] = str(exc)

            ready.append(formatted)

        return {"ready": ready, "total": len(ready)}

    # ── Stage 6: TRACK ──────────────────────────────────────

    def _stage_track(self, loop_id: str, context: dict[str, Any]) -> None:
        """Record the decision for future learning."""
        try:
            from core.learning.outcome_tracker import OutcomeTracker
            ot = OutcomeTracker()
            decision = context.get("decision", {})
            analysis = context.get("analysis", {})
            ot.record_decision(loop_id, "intelligence_loop", {
                "goal": context.get("goal"),
                "action": decision.get("recommended_action", ""),
                "confidence": decision.get("confidence", ""),
                "opportunity_score": decision.get("opportunity_score", 0),
                "data_quality": context.get("clean", {}).get("quality_score", 0),
                "viable_products": analysis.get("products", {}).get("viable", 0),
                "avg_score": analysis.get("products", {}).get("avg_score", 0),
            })
        except Exception:
            pass

    # ── Stage 7: LEARN ──────────────────────────────────────

    def _stage_learn(self, loop_id: str, decision: dict[str, Any]) -> dict[str, Any]:
        """Check past outcomes, generate learning, adjust future decisions."""
        try:
            from core.learning.outcome_tracker import OutcomeTracker
            ot = OutcomeTracker()
            patterns = ot.get_winning_patterns("intelligence_loop")

            adjustments = []
            success_rate = patterns.get("success_rate", 0.5)

            if success_rate < 0.4:
                adjustments.append("Low success rate — system needs strategy adjustment")
            if success_rate > 0.7:
                adjustments.append("High success rate — continue current approach")

            # Apply weight adjustments from patterns
            for p in patterns.get("patterns", []):
                if p.get("pattern") == "score_range":
                    avg_success_score = safe_float(p.get("avg", p.get("min", 0)))
                    if avg_success_score > 7:
                        IntelligenceLoop._weight_adjustments["margin"] = 0.30
                        adjustments.append(f"Boosted margin weight — high scores ({avg_success_score:.1f}) correlate with success")
                    elif avg_success_score < 4:
                        IntelligenceLoop._weight_adjustments["demand"] = 0.30
                        adjustments.append("Boosted demand weight — margin alone not enough")

            advice_result = ot.should_proceed("intelligence_loop", decision)

            return {
                "past_outcomes": patterns.get("with_outcomes", 0),
                "success_rate": patterns.get("success_rate", 0),
                "adjustments_made": len(adjustments) > 0,
                "adjustments": adjustments,
                "advice": advice_result.get("reasons", ["No past data — first run"]),
                "patterns": patterns.get("patterns", []),
                "weight_adjustments": dict(IntelligenceLoop._weight_adjustments),
            }
        except Exception:
            return {"past_outcomes": 0, "adjustments_made": False, "advice": ["Learning system initializing"]}

    # ── Helpers ──────────────────────────────────────────────

    def _get_past_learning(self, goal: str) -> dict[str, Any]:
        """Get accumulated learning from past runs."""
        try:
            from core.learning.outcome_tracker import OutcomeTracker
            patterns = OutcomeTracker().get_winning_patterns("intelligence_loop")
            result = {"success_rate": patterns.get("success_rate", 0)}
            for p in patterns.get("patterns", []):
                if "avoid" in p.get("detail", "").lower():
                    import re
                    nums = re.findall(r'[\d.]+', p.get("detail", ""))
                    if nums:
                        result["avoid_below_score"] = safe_float(nums[-1])
            return result
        except Exception:
            return {}

    @staticmethod
    def _calc_opportunity(analysis: dict) -> int:
        """Calculate overall opportunity score 0-100."""
        score = 50
        products = analysis.get("products", {})
        if products.get("viable", 0) > 0:
            score += 20
        if safe_float(products.get("avg_score")) > 7:
            score += 10
        customers = analysis.get("customers", {})
        if safe_float(customers.get("repeat_rate")) > 30:
            score += 10
        if safe_int(customers.get("at_risk")) > 0:
            score -= 5
        revenue = analysis.get("revenue", {})
        if safe_float(revenue.get("aov")) > 50:
            score += 10
        return max(0, min(100, score))

    @staticmethod
    def _summarize(decision, plan, execution, learning, elapsed) -> str:
        lines = [
            f"Decision: {decision['recommended_action'][:80]}",
            f"Confidence: {decision['confidence']}",
            f"Actions: {plan['total']} planned, {len(execution['ready'])} ready",
        ]
        if learning.get("past_outcomes", 0) > 0:
            lines.append(f"Learning: {learning['past_outcomes']} past outcomes, success rate {learning.get('success_rate', 0):.0%}")
        lines.append(f"Time: {elapsed:.3f}s")
        return "\n".join(lines)

    def _abort(self, loop_id, reason, clean_result, start_time):
        elapsed = time.monotonic() - start_time
        return {
            "loop_id": loop_id, "status": "aborted", "reason": reason,
            "data_quality": clean_result["quality_score"],
            "data_issues": clean_result["issues"],
            "elapsed_seconds": round(elapsed, 3),
            "stages_completed": 1,
            "summary": f"ABORTED: {reason}. Fix data quality first.",
        }

    def get_history(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(self._history[-limit:])
