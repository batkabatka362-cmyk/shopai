"""Protocol — standard message format for agent communication."""
from __future__ import annotations
from typing import Any
from utils.helpers import generate_id, timestamp_now


class MessageProtocol:
    @staticmethod
    def create_request(sender: str, receiver: str, action: str, data: dict[str, Any]) -> dict[str, Any]:
        return {"id": generate_id("req"), "type": "request", "sender": sender, "receiver": receiver, "action": action, "data": data, "timestamp": timestamp_now()}

    @staticmethod
    def create_response(request_id: str, sender: str, receiver: str, result: dict[str, Any], status: str = "success") -> dict[str, Any]:
        return {"id": generate_id("res"), "type": "response", "request_id": request_id, "sender": sender, "receiver": receiver, "result": result, "status": status, "timestamp": timestamp_now()}
