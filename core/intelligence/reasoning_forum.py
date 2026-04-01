"""ReasoningForum — structured multi-perspective debate on decisions.

product_agent: "Price $34.99" (margin focus)
marketing_agent: "Price $24.99" (conversion focus)
analytics_agent: "Price $29.99" (demand curve optimal)

3-round debate → evidence → counter-argument → final position → consensus.
Transcript saved for learning.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id

logger = get_logger("intelligence.reasoning_forum")

# Debate perspectives (virtual agents with different priorities)
PERSPECTIVES = {
    "profit_agent": {
        "priority": "margin_and_profitability",
        "bias": {"margin": 1.5, "revenue": 1.2, "risk": 0.8},
        "style": "Conservative, focuses on sustainable profit",
    },
    "growth_agent": {
        "priority": "customer_acquisition_and_growth",
        "bias": {"conversion": 1.5, "traffic": 1.3, "margin": 0.7},
        "style": "Aggressive, focuses on market share",
    },
    "customer_agent": {
        "priority": "customer_satisfaction_and_retention",
        "bias": {"retention": 1.5, "satisfaction": 1.3, "margin": 0.8},
        "style": "Empathetic, focuses on long-term relationships",
    },
    "risk_agent": {
        "priority": "risk_minimization",
        "bias": {"risk": 1.5, "stability": 1.3, "growth": 0.6},
        "style": "Cautious, focuses on downside protection",
    },
    "data_agent": {
        "priority": "data_driven_decisions",
        "bias": {"data_quality": 1.5, "confidence": 1.3, "speed": 0.7},
        "style": "Analytical, only trusts strong evidence",
    },
}


class ReasoningForum:
    """Structured multi-perspective debate for important decisions.

    Usage:
        forum = ReasoningForum()
        result = forum.debate(
            decision={"action": "raise price to $35", "confidence": 65},
            context={"margin": 25, "competitor_price": 38, "churn_risk": 15},
            options=[option_a, option_b, option_c],
        )
    """

    def __init__(self) -> None:
        self._transcripts: list[dict[str, Any]] = []

    def debate(
        self,
        decision: dict[str, Any],
        context: dict[str, Any],
        options: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run a 3-round debate on a decision.

        Round 1: Each perspective states position + evidence
        Round 2: Counter-arguments
        Round 3: Final position (may be adjusted)
        """
        debate_id = generate_id("debate")
        action = decision.get("action", "unknown")

        # Round 1: Initial positions
        round1 = {}
        for name, config in PERSPECTIVES.items():
            position = self._generate_position(name, config, decision, context, options)
            round1[name] = position

        # Round 2: Counter-arguments (each agent responds to strongest opposition)
        round2 = {}
        for name in PERSPECTIVES:
            opponents = {k: v for k, v in round1.items() if k != name}
            strongest_opponent = max(opponents.items(), key=lambda x: abs(x[1].get("score_adjustment", 0)))
            counter = self._generate_counter(name, round1[name], strongest_opponent[0], strongest_opponent[1], context)
            round2[name] = counter

        # Round 3: Final positions
        round3 = {}
        for name in PERSPECTIVES:
            final = self._generate_final(name, round1[name], round2[name], context)
            round3[name] = final

        # Consensus
        consensus = self._build_consensus(round3, decision, options)

        # Save transcript
        transcript = {
            "debate_id": debate_id,
            "decision": action,
            "round1": round1,
            "round2": round2,
            "round3": round3,
            "consensus": consensus,
        }
        self._transcripts.append(transcript)
        if len(self._transcripts) > 100:
            self._transcripts = self._transcripts[-100:]

        return {
            "debate_id": debate_id,
            "rounds": 3,
            "participants": list(PERSPECTIVES.keys()),
            "consensus": consensus,
            "dissent": [
                {"agent": name, "position": pos["final_position"], "reason": pos.get("reason", "")}
                for name, pos in round3.items()
                if pos.get("agrees_with_consensus") is False
            ],
            "transcript_summary": self._summarize(round1, round2, round3),
        }

    def quick_vote(
        self,
        proposal: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Quick yes/no vote from all perspectives (no full debate)."""
        votes = {}
        for name, config in PERSPECTIVES.items():
            vote, reason = self._quick_evaluate(name, config, proposal, context)
            votes[name] = {"vote": vote, "reason": reason}

        yes_count = sum(1 for v in votes.values() if v["vote"] == "yes")
        no_count = sum(1 for v in votes.values() if v["vote"] == "no")

        return {
            "proposal": proposal,
            "votes": votes,
            "yes": yes_count,
            "no": no_count,
            "result": "approved" if yes_count > no_count else "rejected",
            "margin": f"{yes_count}-{no_count}",
        }

    def get_transcripts(self, limit: int = 5) -> list[dict[str, Any]]:
        return self._transcripts[-limit:]

    def _generate_position(self, agent_name, config, decision, context, options):
        """Generate initial position for an agent."""
        priority = config["priority"]
        bias = config["bias"]
        action = decision.get("action", "")
        confidence = decision.get("confidence_score", 50)

        # Score the decision from this perspective
        score = 50  # neutral
        reasons = []

        margin = context.get("margin", 50)
        churn = context.get("churn_risk", 0)
        data_quality = context.get("data_quality", 50)
        competitor = context.get("competitor_price", 0)

        if "profit" in agent_name:
            if margin > 30:
                score += 15
                reasons.append(f"Good margin ({margin}%)")
            elif margin < 15:
                score -= 20
                reasons.append(f"Thin margin ({margin}%) — risky")

        elif "growth" in agent_name:
            if "price" in action.lower() and "increase" in action.lower():
                score -= 15
                reasons.append("Price increase may reduce conversion")
            if churn > 20:
                score -= 10
                reasons.append(f"High churn ({churn}%) — focus on retention first")

        elif "customer" in agent_name:
            if churn > 15:
                score -= 15
                reasons.append(f"Churn at {churn}% — customers are already leaving")
            if "discount" in action.lower() or "gift" in action.lower():
                score += 10
                reasons.append("Customer-friendly action")

        elif "risk" in agent_name:
            if confidence < 60:
                score -= 20
                reasons.append(f"Low confidence ({confidence}/100) — too risky")
            if competitor > 0 and "price" in action.lower():
                score -= 10
                reasons.append("Competitor context makes pricing changes risky")

        elif "data" in agent_name:
            if data_quality < 50:
                score -= 25
                reasons.append(f"Data quality only {data_quality}/100 — insufficient")
            elif data_quality > 75:
                score += 15
                reasons.append(f"Strong data quality ({data_quality}/100)")

        position = "support" if score >= 55 else "oppose" if score <= 45 else "neutral"

        return {
            "position": position,
            "score": score,
            "score_adjustment": score - 50,
            "reasons": reasons if reasons else [f"No strong signal for {priority}"],
            "priority": priority,
        }

    def _generate_counter(self, agent_name, own_position, opponent_name, opponent_position, context):
        """Generate counter-argument to strongest opponent."""
        if own_position["position"] == opponent_position["position"]:
            return {"counter": "Agrees with " + opponent_name, "adjusted": False}

        counter_reasons = []
        if own_position["position"] == "support" and opponent_position["position"] == "oppose":
            counter_reasons.append(f"Disagree with {opponent_name}: {opponent_position['reasons'][0] if opponent_position['reasons'] else 'no clear reason'}")
            counter_reasons.append(f"My priority ({own_position['priority']}) outweighs their concern")
        elif own_position["position"] == "oppose":
            counter_reasons.append(f"Despite {opponent_name}'s support, the risks are too high")

        return {
            "counter_to": opponent_name,
            "counter_reasons": counter_reasons,
            "adjusted": False,
            "new_score": own_position["score"],
        }

    def _generate_final(self, agent_name, round1, round2, context):
        """Generate final position after hearing all arguments."""
        score = round2.get("new_score", round1["score"])

        # Slight adjustment toward center after hearing debate
        if score > 60:
            score -= 3
        elif score < 40:
            score += 3

        final_position = "support" if score >= 55 else "oppose" if score <= 45 else "neutral"
        changed = final_position != round1["position"]

        return {
            "initial_position": round1["position"],
            "final_position": final_position,
            "changed": changed,
            "final_score": score,
            "reason": round1["reasons"][0] if round1["reasons"] else "No strong signal",
        }

    def _build_consensus(self, round3, decision, options):
        """Build consensus from final positions."""
        support = sum(1 for p in round3.values() if p["final_position"] == "support")
        oppose = sum(1 for p in round3.values() if p["final_position"] == "oppose")
        neutral = sum(1 for p in round3.values() if p["final_position"] == "neutral")

        avg_score = sum(p["final_score"] for p in round3.values()) / max(len(round3), 1)

        if support > oppose + neutral:
            verdict = "proceed"
            strength = "strong" if support >= 4 else "moderate"
        elif oppose > support + neutral:
            verdict = "reject"
            strength = "strong" if oppose >= 4 else "moderate"
        else:
            verdict = "inconclusive"
            strength = "weak"

        # Mark agreement
        for name, pos in round3.items():
            pos["agrees_with_consensus"] = (
                (verdict == "proceed" and pos["final_position"] == "support")
                or (verdict == "reject" and pos["final_position"] == "oppose")
                or verdict == "inconclusive"
            )

        return {
            "verdict": verdict,
            "strength": strength,
            "support": support,
            "oppose": oppose,
            "neutral": neutral,
            "avg_score": round(avg_score, 1),
            "confidence_adjustment": round(avg_score - 50, 1),
        }

    def _quick_evaluate(self, agent_name, config, proposal, context):
        margin = context.get("margin", 50)
        churn = context.get("churn_risk", 0)
        confidence = context.get("confidence", 50)

        if "profit" in agent_name:
            return ("yes" if margin > 20 else "no", f"Margin {'adequate' if margin > 20 else 'too thin'}")
        if "growth" in agent_name:
            return ("yes" if churn < 20 else "no", f"Churn {'acceptable' if churn < 20 else 'too high'}")
        if "customer" in agent_name:
            return ("yes" if churn < 25 else "no", f"Customer health {'good' if churn < 25 else 'poor'}")
        if "risk" in agent_name:
            return ("yes" if confidence > 60 else "no", f"Confidence {'sufficient' if confidence > 60 else 'insufficient'}")
        if "data" in agent_name:
            dq = context.get("data_quality", 50)
            return ("yes" if dq > 60 else "no", f"Data quality {'strong' if dq > 60 else 'weak'}")
        return ("yes", "Default approval")

    def _summarize(self, r1, r2, r3):
        lines = []
        for name in PERSPECTIVES:
            initial = r1[name]["position"]
            final = r3[name]["final_position"]
            changed = "→ " + final if initial != final else ""
            lines.append(f"{name}: {initial} {changed} ({r1[name]['reasons'][0] if r1[name]['reasons'] else '?'})")
        return "\n".join(lines)
