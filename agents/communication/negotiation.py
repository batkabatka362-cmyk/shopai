"""Negotiation — multi-agent proposal/vote/resolve workflow."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


class Negotiation:
    """Facilitates structured negotiations between agents.

    Supports strategies: majority, unanimous, weighted.
    """

    STRATEGIES = ("majority", "unanimous", "weighted")
    VALID_VOTES = ("accept", "reject", "abstain")

    def __init__(self) -> None:
        # negotiation_id -> negotiation record
        self._negotiations: dict[str, dict] = {}

    @staticmethod
    def _new_id() -> str:
        return f"neg-{uuid.uuid4().hex[:12]}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def propose(
        self, proposer: str, proposal: dict, recipients: list[str]
    ) -> str:
        """Create a new negotiation proposal. Returns the negotiation_id."""
        neg_id = self._new_id()
        self._negotiations[neg_id] = {
            "id": neg_id,
            "proposer": proposer,
            "proposal": dict(proposal),
            "recipients": list(recipients),
            "strategy": "majority",  # default, can be overridden via negotiate()
            "votes": {},  # agent_id -> {vote, reason, timestamp}
            "status": "open",
            "result": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "resolved_at": None,
        }
        return neg_id

    def vote(
        self,
        negotiation_id: str,
        agent_id: str,
        vote: str,
        reason: str = "",
    ) -> None:
        """Cast a vote on an open negotiation."""
        if negotiation_id not in self._negotiations:
            raise KeyError(f"Unknown negotiation: {negotiation_id}")

        neg = self._negotiations[negotiation_id]
        if neg["status"] != "open":
            raise RuntimeError(f"Negotiation {negotiation_id} is already {neg['status']}")

        if vote not in self.VALID_VOTES:
            raise ValueError(f"Invalid vote '{vote}'. Must be one of {self.VALID_VOTES}")

        if agent_id not in neg["recipients"] and agent_id != neg["proposer"]:
            raise ValueError(f"Agent {agent_id} is not a participant in this negotiation")

        neg["votes"][agent_id] = {
            "vote": vote,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def resolve(self, negotiation_id: str) -> dict:
        """Resolve a negotiation based on its strategy. Returns the result."""
        if negotiation_id not in self._negotiations:
            raise KeyError(f"Unknown negotiation: {negotiation_id}")

        neg = self._negotiations[negotiation_id]
        if neg["status"] != "open":
            return dict(neg)

        strategy = neg["strategy"]
        votes = neg["votes"]

        if strategy == "majority":
            result = self._resolve_majority(votes)
        elif strategy == "unanimous":
            result = self._resolve_unanimous(votes, neg["recipients"])
        elif strategy == "weighted":
            result = self._resolve_weighted(votes)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        neg["status"] = "resolved"
        neg["result"] = result
        neg["resolved_at"] = datetime.now(timezone.utc).isoformat()
        return dict(neg)

    def negotiate(
        self,
        agents: list[str],
        proposal: dict,
        strategy: str = "majority",
    ) -> dict:
        """High-level helper: create a proposal, auto-accept from all agents, resolve.

        Useful for programmatic negotiation where votes are pre-determined
        in the proposal under key ``votes`` (a dict mapping agent_id -> vote string).
        If no votes are provided, all agents auto-accept.
        """
        if strategy not in self.STRATEGIES:
            raise ValueError(f"Unknown strategy '{strategy}'. Must be one of {self.STRATEGIES}")

        proposer = agents[0] if agents else "system"
        recipients = agents[1:] if len(agents) > 1 else list(agents)

        neg_id = self.propose(proposer, proposal, recipients)
        neg = self._negotiations[neg_id]
        neg["strategy"] = strategy

        # Cast votes (from proposal dict or auto-accept)
        provided_votes = proposal.get("votes", {})
        for agent_id in agents:
            v = provided_votes.get(agent_id, "accept")
            reason = provided_votes.get(f"{agent_id}_reason", "")
            # Ensure the agent is listed as participant
            if agent_id not in neg["recipients"] and agent_id != neg["proposer"]:
                neg["recipients"].append(agent_id)
            self.vote(neg_id, agent_id, v, reason)

        return self.resolve(neg_id)

    def get_status(self, negotiation_id: str) -> dict:
        """Return the current state of a negotiation."""
        if negotiation_id not in self._negotiations:
            raise KeyError(f"Unknown negotiation: {negotiation_id}")
        return dict(self._negotiations[negotiation_id])

    # ------------------------------------------------------------------
    # Resolution strategies
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_majority(votes: dict) -> dict:
        """Accept if more accept than reject (abstains ignored)."""
        accept_count = sum(1 for v in votes.values() if v["vote"] == "accept")
        reject_count = sum(1 for v in votes.values() if v["vote"] == "reject")
        total_cast = accept_count + reject_count

        accepted = accept_count > reject_count if total_cast > 0 else False
        return {
            "accepted": accepted,
            "method": "majority",
            "accept_count": accept_count,
            "reject_count": reject_count,
            "abstain_count": len(votes) - accept_count - reject_count,
        }

    @staticmethod
    def _resolve_unanimous(votes: dict, recipients: list[str]) -> dict:
        """Accept only if every recipient has voted accept."""
        all_voted = all(
            agent_id in votes for agent_id in recipients
        )
        all_accept = all(
            v["vote"] == "accept" for v in votes.values()
        )
        return {
            "accepted": all_voted and all_accept,
            "method": "unanimous",
            "all_voted": all_voted,
            "votes_cast": len(votes),
            "expected_votes": len(recipients),
        }

    @staticmethod
    def _resolve_weighted(votes: dict) -> dict:
        """Weighted resolution: each vote may carry a weight (default 1).

        Weight is taken from vote reason if it is a numeric string, otherwise 1.
        """
        accept_weight = 0.0
        reject_weight = 0.0
        for v in votes.values():
            try:
                weight = float(v["reason"]) if v["reason"] else 1.0
            except (ValueError, TypeError):
                weight = 1.0
            if v["vote"] == "accept":
                accept_weight += weight
            elif v["vote"] == "reject":
                reject_weight += weight

        total = accept_weight + reject_weight
        accepted = accept_weight > reject_weight if total > 0 else False
        return {
            "accepted": accepted,
            "method": "weighted",
            "accept_weight": accept_weight,
            "reject_weight": reject_weight,
        }
