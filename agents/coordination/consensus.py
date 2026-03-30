"""Consensus — voting and ranking algorithms for multi-agent agreement."""

from __future__ import annotations

from collections import Counter


class Consensus:
    """Provides multiple consensus methods for agents to collectively decide."""

    METHODS = ("simple_majority", "ranked_choice", "weighted_vote", "borda_count")

    def reach_consensus(
        self,
        agents: list[str],
        options: list[dict],
        method: str = "ranked_choice",
        votes: dict | None = None,
        rankings: dict | None = None,
        weights: dict | None = None,
    ) -> dict:
        """High-level entry point: reach consensus among agents.

        Parameters
        ----------
        agents:
            List of participating agent ids.
        options:
            List of option dicts (must have an ``id`` key).
        method:
            One of ``simple_majority``, ``ranked_choice``, ``weighted_vote``,
            ``borda_count``.
        votes:
            For simple_majority / weighted_vote — mapping agent_id -> option_id.
        rankings:
            For ranked_choice / borda_count — mapping agent_id -> [option_id, ...] (best first).
        weights:
            For weighted_vote — mapping agent_id -> numeric weight.
        """
        if method not in self.METHODS:
            raise ValueError(f"Unknown method '{method}'. Must be one of {self.METHODS}")

        option_ids = [o["id"] for o in options]

        if method == "simple_majority":
            if votes is None:
                raise ValueError("simple_majority requires 'votes' dict")
            winner = self.simple_majority(votes)

        elif method == "ranked_choice":
            if rankings is None:
                raise ValueError("ranked_choice requires 'rankings' dict")
            winner = self.ranked_choice(rankings)

        elif method == "weighted_vote":
            if votes is None:
                raise ValueError("weighted_vote requires 'votes' dict")
            if weights is None:
                weights = {a: 1.0 for a in agents}
            winner = self.weighted_vote(votes, weights)

        elif method == "borda_count":
            if rankings is None:
                raise ValueError("borda_count requires 'rankings' dict")
            winner = self.borda_count(rankings)
        else:
            raise ValueError(f"Unsupported method: {method}")

        scores = self._calculate_scores(method, votes=votes, rankings=rankings, weights=weights)

        return {
            "method": method,
            "winner": winner,
            "scores": scores,
            "agents": agents,
            "options": option_ids,
        }

    # ------------------------------------------------------------------
    # Voting methods
    # ------------------------------------------------------------------

    @staticmethod
    def simple_majority(votes: dict) -> str:
        """Return the option with the most votes.

        ``votes``: mapping of voter_id -> option_id.
        """
        counts = Counter(votes.values())
        if not counts:
            return ""
        winner, _ = counts.most_common(1)[0]
        return winner

    @staticmethod
    def ranked_choice(rankings: dict) -> str:
        """Instant-runoff / ranked-choice voting.

        ``rankings``: mapping of voter_id -> [option_id, ...] (best first).
        Eliminates the option with fewest first-place votes each round until
        one option has a majority.
        """
        if not rankings:
            return ""

        # Build mutable copy of rankings
        active_rankings: dict[str, list[str]] = {
            voter: list(r) for voter, r in rankings.items()
        }

        all_options: set[str] = set()
        for r in active_rankings.values():
            all_options.update(r)

        eliminated: set[str] = set()

        while True:
            # Count first-place votes among remaining options
            first_place: Counter = Counter()
            for r in active_rankings.values():
                # First non-eliminated option
                for opt in r:
                    if opt not in eliminated:
                        first_place[opt] += 1
                        break

            if not first_place:
                return ""

            total_voters = sum(first_place.values())
            # Check for majority
            for opt, count in first_place.most_common():
                if count > total_voters / 2:
                    return opt

            # Eliminate option with fewest first-place votes
            min_count = min(first_place.values())
            to_eliminate = [opt for opt, c in first_place.items() if c == min_count]

            # If all remaining are tied, pick the first alphabetically
            if len(to_eliminate) == len(first_place):
                return sorted(first_place.keys())[0]

            eliminated.update(to_eliminate)

    @staticmethod
    def weighted_vote(votes: dict, weights: dict) -> str:
        """Weighted plurality vote.

        ``votes``: voter_id -> option_id.
        ``weights``: voter_id -> numeric weight.
        """
        scores: dict[str, float] = {}
        for voter, option in votes.items():
            w = weights.get(voter, 1.0)
            scores[option] = scores.get(option, 0.0) + w

        if not scores:
            return ""
        return max(scores, key=scores.get)  # type: ignore[arg-type]

    @staticmethod
    def borda_count(rankings: dict) -> str:
        """Borda count: each position awards points (n-1 for 1st, n-2 for 2nd, ...).

        ``rankings``: voter_id -> [option_id, ...] (best first).
        """
        scores: dict[str, float] = {}
        for voter, ranking in rankings.items():
            n = len(ranking)
            for position, option in enumerate(ranking):
                points = n - 1 - position
                scores[option] = scores.get(option, 0.0) + points

        if not scores:
            return ""
        return max(scores, key=scores.get)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _calculate_scores(
        self,
        method: str,
        votes: dict | None = None,
        rankings: dict | None = None,
        weights: dict | None = None,
    ) -> dict:
        """Return a scores dict appropriate for the given method."""
        if method == "simple_majority" and votes is not None:
            return dict(Counter(votes.values()))

        if method == "weighted_vote" and votes is not None:
            if weights is None:
                weights = {}
            scores: dict[str, float] = {}
            for voter, option in votes.items():
                w = weights.get(voter, 1.0)
                scores[option] = scores.get(option, 0.0) + w
            return scores

        if method in ("ranked_choice", "borda_count") and rankings is not None:
            scores_b: dict[str, float] = {}
            for voter, ranking in rankings.items():
                n = len(ranking)
                for pos, option in enumerate(ranking):
                    points = n - 1 - pos
                    scores_b[option] = scores_b.get(option, 0.0) + points
            return scores_b

        return {}
