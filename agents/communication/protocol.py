"""Protocol — standardised message formats for agent communication."""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone


def _as_dict(value, label: str) -> dict:
    """Coerce a value to a dict via deep-copy.

    Replaces `dict(value)` which crashed with TypeError when the
    caller passed a non-dict (string, list, None, etc.). The
    deep-copy also prevents the publisher from mutating the
    original after we've stored it in the envelope.
    """
    if isinstance(value, dict):
        return copy.deepcopy(value)
    if value is None:
        return {}
    return {label: value}


class Protocol:
    """Defines and validates structured message formats exchanged between agents."""

    MESSAGE_TYPES = ["request", "response", "broadcast", "event", "error"]

    REQUIRED_FIELDS = {"id", "type", "sender", "receiver", "payload", "timestamp", "correlation_id"}

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _new_id() -> str:
        return f"proto-{uuid.uuid4().hex[:16]}"

    @classmethod
    def create_message(
        cls,
        msg_type: str,
        sender: str,
        receiver: str,
        payload: dict,
        correlation_id: str | None = None,
    ) -> dict:
        """Create a generic protocol message."""
        if msg_type not in cls.MESSAGE_TYPES:
            raise ValueError(
                f"Invalid message type '{msg_type}'. Must be one of {cls.MESSAGE_TYPES}"
            )

        msg_id = cls._new_id()
        return {
            "id": msg_id,
            "type": msg_type,
            "sender": sender,
            "receiver": receiver,
            # Defensive deep-copy through _as_dict so a non-dict
            # payload doesn't crash with TypeError, AND so the
            # caller mutating the original after create_message
            # doesn't bleed into the envelope.
            "payload": _as_dict(payload, "raw"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": correlation_id or msg_id,
        }

    @classmethod
    def create_request(
        cls, sender: str, receiver: str, action: str, params: dict
    ) -> dict:
        """Convenience: create a *request* message."""
        payload = {"action": action, "params": _as_dict(params, "raw")}
        return cls.create_message("request", sender, receiver, payload)

    @classmethod
    def create_response(
        cls, request_id: str, sender: str, result: dict, status: str = "success"
    ) -> dict:
        """Convenience: create a *response* that correlates to a prior request."""
        payload = {"result": _as_dict(result, "raw"), "status": status}
        return cls.create_message(
            "response", sender, receiver="*", payload=payload, correlation_id=request_id
        )

    @classmethod
    def create_broadcast(cls, sender: str, topic: str, payload: dict) -> dict:
        """Convenience: create a *broadcast* message (receiver is '*')."""
        full_payload = {"topic": topic, **_as_dict(payload, "raw")}
        return cls.create_message("broadcast", sender, receiver="*", payload=full_payload)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @classmethod
    def validate_message(cls, message: dict) -> tuple[bool, list[str]]:
        """Validate a message dict against the protocol schema.

        Returns (is_valid, list_of_errors).

        Note: a present-but-None required field is treated as
        MISSING. The previous version only flagged absent keys, so
        a message with `sender: None` silently passed validation
        even though every downstream consumer would crash on it.
        """
        errors: list[str] = []

        if not isinstance(message, dict):
            return False, ["Message must be a dict"]

        # Treat present-but-None required fields as missing.
        present_keys = {k for k, v in message.items() if v is not None}
        missing = cls.REQUIRED_FIELDS - present_keys
        if missing:
            errors.append(f"Missing required fields: {sorted(missing)}")

        # Type check — explicit None now flagged via the missing
        # check above, so this branch only runs for present values.
        msg_type = message.get("type")
        if msg_type is not None and msg_type not in cls.MESSAGE_TYPES:
            errors.append(
                f"Invalid message type '{msg_type}'. Must be one of {cls.MESSAGE_TYPES}"
            )

        # Payload must be a dict
        payload = message.get("payload")
        if payload is not None and not isinstance(payload, dict):
            errors.append("Payload must be a dict")

        # Sender / receiver should be non-empty strings
        for field in ("sender", "receiver"):
            val = message.get(field)
            if val is not None and (not isinstance(val, str) or not val):
                errors.append(f"'{field}' must be a non-empty string")

        return (len(errors) == 0, errors)
