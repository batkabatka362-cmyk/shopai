"""Protocol — standardised message formats for agent communication."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


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
            "payload": dict(payload),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": correlation_id or msg_id,
        }

    @classmethod
    def create_request(
        cls, sender: str, receiver: str, action: str, params: dict
    ) -> dict:
        """Convenience: create a *request* message."""
        payload = {"action": action, "params": dict(params)}
        return cls.create_message("request", sender, receiver, payload)

    @classmethod
    def create_response(
        cls, request_id: str, sender: str, result: dict, status: str = "success"
    ) -> dict:
        """Convenience: create a *response* that correlates to a prior request."""
        payload = {"result": dict(result), "status": status}
        return cls.create_message(
            "response", sender, receiver="*", payload=payload, correlation_id=request_id
        )

    @classmethod
    def create_broadcast(cls, sender: str, topic: str, payload: dict) -> dict:
        """Convenience: create a *broadcast* message (receiver is '*')."""
        full_payload = {"topic": topic, **payload}
        return cls.create_message("broadcast", sender, receiver="*", payload=full_payload)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @classmethod
    def validate_message(cls, message: dict) -> tuple[bool, list[str]]:
        """Validate a message dict against the protocol schema.

        Returns (is_valid, list_of_errors).
        """
        errors: list[str] = []

        if not isinstance(message, dict):
            return False, ["Message must be a dict"]

        # Check required fields
        missing = cls.REQUIRED_FIELDS - set(message.keys())
        if missing:
            errors.append(f"Missing required fields: {sorted(missing)}")

        # Type check
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
