"""Tests for audit-pass-30 fixes in agents/communication.

  Protocol:
    1. dict(payload) crashed with TypeError on a non-dict payload.
    2. validate_message treated present-but-None required fields
       as VALID — every downstream consumer would crash on the
       None values but the validator gave a thumbs-up.

  Negotiation:
    3. _resolve_weighted abused vote.reason as a numeric weight,
       conflating two semantically distinct fields.
    4. No thread lock on _negotiations table.
    5. Direct dict access on negotiation records.
    6. Shallow-copy returns from get_status / resolve.
    7. dict(proposal) crashed on a non-dict proposal.
"""
import threading

import pytest


# ── Protocol fixes ──────────────────────────────────────────


class TestProtocolPayloadDefensive:
    def test_non_dict_payload_does_not_crash(self):
        from agents.communication.protocol import Protocol
        # Previously: dict("not a dict") raised TypeError
        msg = Protocol.create_message("event", "a", "b", "raw text")
        assert msg["payload"] == {"raw": "raw text"}

    def test_none_payload_becomes_empty(self):
        from agents.communication.protocol import Protocol
        msg = Protocol.create_message("event", "a", "b", None)
        assert msg["payload"] == {}

    def test_dict_payload_is_deep_copied(self):
        from agents.communication.protocol import Protocol
        original = {"items": ["a", "b"]}
        msg = Protocol.create_message("event", "a", "b", original)
        original["items"].append("MUTATED")
        assert msg["payload"]["items"] == ["a", "b"]

    def test_create_request_handles_none_params(self):
        from agents.communication.protocol import Protocol
        # Previously dict(None) crashed
        req = Protocol.create_request("a", "b", "doit", None)
        assert req["payload"]["action"] == "doit"
        assert req["payload"]["params"] == {}


class TestProtocolValidationStrict:
    def test_present_but_none_field_flagged_as_missing(self):
        """Regression: previously a message with `sender: None`
        passed validation because the missing-fields check used
        set(message.keys()) which contains the None-valued key."""
        from agents.communication.protocol import Protocol
        msg = {
            "id": "x",
            "type": "event",
            "sender": None,  # <-- the bad one
            "receiver": "b",
            "payload": {},
            "timestamp": "2026-04-07T00:00:00Z",
            "correlation_id": "x",
        }
        ok, errors = Protocol.validate_message(msg)
        assert ok is False
        assert any("sender" in e for e in errors)

    def test_all_fields_none_caught(self):
        from agents.communication.protocol import Protocol
        msg = {k: None for k in Protocol.REQUIRED_FIELDS}
        ok, errors = Protocol.validate_message(msg)
        assert ok is False
        assert any("Missing required" in e for e in errors)

    def test_valid_message_passes(self):
        from agents.communication.protocol import Protocol
        msg = Protocol.create_message("event", "a", "b", {"k": "v"})
        ok, errors = Protocol.validate_message(msg)
        assert ok is True
        assert errors == []


# ── Negotiation fixes ───────────────────────────────────────


def _neg():
    from agents.communication.negotiation import Negotiation
    return Negotiation()


class TestNegotiationWeightedFix:
    def test_weighted_uses_explicit_weight_field(self):
        """Regression: previously _resolve_weighted parsed
        vote.reason as a float, abusing the human-readable text
        field."""
        n = _neg()
        nid = n.propose("p", {"plan": "x"}, ["a", "b", "c"])
        n.vote(nid, "p", "accept", reason="proposer", weight=3.0)
        n.vote(nid, "a", "accept", reason="agree", weight=2.0)
        n.vote(nid, "b", "reject", reason="disagree", weight=4.0)
        n.vote(nid, "c", "abstain", reason="unsure")
        n._negotiations[nid]["strategy"] = "weighted"
        result = n.resolve(nid)
        # accept_weight = 3 + 2 = 5
        # reject_weight = 4
        # 5 > 4 → accepted
        assert result["result"]["accept_weight"] == 5.0
        assert result["result"]["reject_weight"] == 4.0
        assert result["result"]["accepted"] is True

    def test_weighted_default_weight_is_one(self):
        n = _neg()
        nid = n.propose("p", {}, ["a", "b"])
        n.vote(nid, "p", "accept")  # default weight=1
        n.vote(nid, "a", "accept")
        n.vote(nid, "b", "reject")
        n._negotiations[nid]["strategy"] = "weighted"
        result = n.resolve(nid)
        assert result["result"]["accept_weight"] == 2.0
        assert result["result"]["reject_weight"] == 1.0

    def test_negotiate_helper_passes_weights(self):
        n = _neg()
        result = n.negotiate(
            agents=["a", "b", "c"],
            proposal={
                "plan": "x",
                "votes": {"a": "accept", "b": "reject", "c": "accept"},
                "weights": {"a": 5, "b": 10, "c": 1},
            },
            strategy="weighted",
        )
        # accept = 5 + 1 = 6, reject = 10 → rejected
        assert result["result"]["accept_weight"] == 6.0
        assert result["result"]["reject_weight"] == 10.0
        assert result["result"]["accepted"] is False


class TestNegotiationThreadSafety:
    def test_concurrent_propose_no_lost_negotiations(self):
        n = _neg()
        errors: list[Exception] = []

        def worker(start):
            try:
                for i in range(20):
                    n.propose(f"p_{start}", {}, [f"a_{start}_{i}"])
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert len(n._negotiations) == 80


class TestNegotiationDefensive:
    def test_get_status_returns_deep_copy(self):
        n = _neg()
        nid = n.propose("p", {"plan": "x"}, ["a"])
        n.vote(nid, "a", "accept")
        snap = n.get_status(nid)
        # Mutating the snapshot must not poison internal state
        snap["votes"]["leak"] = {"vote": "reject"}
        snap["proposal"]["mutated"] = True
        again = n.get_status(nid)
        assert "leak" not in again["votes"]
        assert "mutated" not in again["proposal"]

    def test_resolve_returns_deep_copy(self):
        n = _neg()
        nid = n.propose("p", {"x": 1}, ["a"])
        n.vote(nid, "a", "accept")
        result = n.resolve(nid)
        result["votes"]["poison"] = {}
        again = n.get_status(nid)
        assert "poison" not in again["votes"]

    def test_non_dict_proposal_wrapped(self):
        n = _neg()
        # Previously dict("not a dict") crashed
        nid = n.propose("p", "raw proposal text", ["a"])
        snap = n.get_status(nid)
        assert snap["proposal"] == {"raw": "raw proposal text"}

    def test_malformed_vote_record_does_not_crash_resolve(self):
        n = _neg()
        nid = n.propose("p", {}, ["a", "b"])
        # Inject malformed vote record without "vote" field
        n._negotiations[nid]["votes"]["a"] = {"reason": "broken"}
        n.vote(nid, "b", "accept")
        # Resolution doesn't crash on missing "vote" key
        result = n.resolve(nid)
        # Only "b" counted as accept
        assert result["result"]["accept_count"] == 1
