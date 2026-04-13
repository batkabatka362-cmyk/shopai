"""Negotiation — multi-agent proposal/vote/resolve workflow."""

from __future__ import annotations

import copy
import threading
import uuid
from datetime import datetime, timezone

from utils.helpers import safe_float


class Negotiation:
    """Facilitates structured negotiations between agents.

    Supports strategies: majority, unanimous, weighted.

    Thread-safe: a single internal lock guards all mutations of
    the negotiation table so concurrent propose/vote/resolve
    calls from multiple cycles can't observe partial state.
    """

    STRATEGIES = ("majority", "unanimous", "weighted")
    VALID_VOTES = ("accept", "reject", "abstain")

    def __init__(self) -> None:
        # negotiation_id -> negotiation record
        self._negotiations: dict[str, dict] = {}
        self._lock = threading.Lock()

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
        # Defensive deep-copy of the proposal so caller mutation
        # after propose() can't bleed into the stored record.
        proposal_copy = copy.deepcopy(proposal) if isinstance(proposal, dict) else {"raw": proposal}
        record = {
            "id": neg_id,
            "proposer": proposer,
            "proposal": proposal_copy,
            "recipients": list(recipients) if recipients else [],
            "strategy": "majority",  # default, can be overridden via negotiate()
            "votes": {},  # agent_id -> {vote, reason, weight, timestamp}
            "status": "open",
            "result": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "resolved_at": None,
        }
        with self._lock:
            self._negotiations[neg_id] = record
        return neg_id

    def vote(
        self,
        negotiation_id: str,
        agent_id: str,
        vote: str,
        reason: str = "",
        weight: float = 1.0,
    ) -> None:
        """Cast a vote on an open negotiation.

        `weight` is used by the weighted strategy. Defaults to 1.0
        for plain accept/reject votes. The previous version
        abused the `reason` field as a numeric weight, which was
        semantically wrong (reason should be human-readable text)
        and made it impossible to attach BOTH a real reason AND a
        weight to a vote. Now they're separate parameters.
        """
        if vote not in self.VALID_VOTES:
            raise ValueError(f"Invalid vote '{vote}'. Must be one of {self.VALID_VOTES}")

        with self._lock:
            if negotiation_id not in self._negotiations:
                raise KeyError(f"Unknown negotiation: {negotiation_id}")

            neg = self._negotiations[negotiation_id]
            if neg.get("status") != "open":
                raise RuntimeError(
                    f"Negotiation {negotiation_id} is already {neg.get('status')}"
                )

            recipients = neg.get("recipients") or []
            if agent_id not in recipients and agent_id != neg.get("proposer"):
                raise ValueError(
                    f"Agent {agent_id} is not a participant in this negotiation"
                )

            neg["votes"][agent_id] = {
                "vote": vote,
                "reason": reason,
                "weight": safe_float(weight, default=1.0) or 1.0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def resolve(self, negotiation_id: str) -> dict:
        """Resolve a negotiation based on its strategy. Returns the result."""
        with self._lock:
            if negotiation_id not in self._negotiations:
                raise KeyError(f"Unknown negotiation: {negotiation_id}")

            neg = self._negotiations[negotiation_id]
            if neg.get("status") != "open":
                return copy.deepcopy(neg)

            strategy = neg.get("strategy", "majority")
            votes = neg.get("votes") or {}
            recipients = neg.get("recipients") or []

            if strategy == "majority":
                result = self._resolve_majority(votes)
            elif strategy == "unanimous":
                result = self._resolve_unanimous(votes, recipients)
            elif strategy == "weighted":
                result = self._resolve_weighted(votes)
            else:
                raise ValueError(f"Unknown strategy: {strategy}")

            neg["status"] = "resolved"
            neg["result"] = result
            neg["resolved_at"] = datetime.now(timezone.utc).isoformat()
            return copy.deepcopy(neg)

    def negotiate(
        self,
        agents: list[str],
        proposal: dict,
        strategy: str = "majority",
    ) -> dict:
        """High-level helper: create a proposal, auto-accept from all agents, resolve.

        Programmatic negotiation can pre-supply votes via the
        proposal dict under key ``votes`` (a dict mapping agent_id
        → vote string). For weighted strategy, weights can be
        supplied under key ``weights`` (agent_id → float). If no
        votes are provided, all agents auto-accept.
        """
        if strategy not in self.STRATEGIES:
            raise ValueError(f"Unknown strategy '{strategy}'. Must be one of {self.STRATEGIES}")

        agents = list(agents) if agents else []
        proposer = agents[0] if agents else "system"
        recipients = agents[1:] if len(agents) > 1 else []

        neg_id = self.propose(proposer, proposal, recipients)
        with self._lock:
            neg = self._negotiations[neg_id]
            neg["strategy"] = strategy

        # Cast votes (from proposal dict or auto-accept)
        proposal_dict = proposal if isinstance(proposal, dict) else {}
        provided_votes = proposal_dict.get("votes") or {}
        provided_weights = proposal_dict.get("weights") or {}
        for agent_id in agents:
            v = provided_votes.get(agent_id, "accept")
            reason = provided_votes.get(f"{agent_id}_reason", "")
            weight = safe_float(provided_weights.get(agent_id), default=1.0) or 1.0
            # Ensure the agent is listed as participant
            with self._lock:
                rec = self._negotiations[neg_id]
                if agent_id not in rec["recipients"] and agent_id != rec["proposer"]:
                    rec["recipients"].append(agent_id)
            self.vote(neg_id, agent_id, v, reason=reason, weight=weight)

        return self.resolve(neg_id)

    def get_status(self, negotiation_id: str) -> dict:
        """Return a deep-copy of the current state of a negotiation."""
        with self._lock:
            if negotiation_id not in self._negotiations:
                raise KeyError(f"Unknown negotiation: {negotiation_id}")
            return copy.deepcopy(self._negotiations[negotiation_id])

    # ------------------------------------------------------------------
    # Resolution strategies
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_majority(votes: dict) -> dict:
        """Accept if more accept than reject (abstains ignored).

        Defensive `.get("vote")` so a malformed vote record
        (missing field) doesn't crash the resolution.
        """
        accept_count = sum(1 for v in votes.values() if v.get("vote") == "accept")
        reject_count = sum(1 for v in votes.values() if v.get("vote") == "reject")
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
        all_voted = all(agent_id in votes for agent_id in recipients) if recipients else False
        all_accept = all(
            v.get("vote") == "accept" for v in votes.values()
        ) if votes else False
        return {
            "accepted": all_voted and all_accept,
            "method": "unanimous",
            "all_voted": all_voted,
            "votes_cast": len(votes),
            "expected_votes": len(recipients),
        }

    @staticmethod
    def _resolve_weighted(votes: dict) -> dict:
        """Weighted resolution.

        The previous version abused `vote.reason` as a numeric
        weight (parsing the human-readable text via float()),
        which mixed two semantically distinct fields and made it
        impossible to attach both a real reason AND a weight to
        a vote. Now `vote.weight` is a first-class field set by
        Negotiation.vote() and Negotiation.negotiate(); the
        reason field is back to being free-form text.
        """
        accept_weight = 0.0
        reject_weight = 0.0
        for v in votes.values():
            weight = safe_float(v.get("weight"), default=1.0) or 1.0
            choice = v.get("vote")
            if choice == "accept":
                accept_weight += weight
            elif choice == "reject":
                reject_weight += weight

        total = accept_weight + reject_weight
        accepted = accept_weight > reject_weight if total > 0 else False
        return {
            "accepted": accepted,
            "method": "weighted",
            "accept_weight": round(accept_weight, 4),
            "reject_weight": round(reject_weight, 4),
        }
