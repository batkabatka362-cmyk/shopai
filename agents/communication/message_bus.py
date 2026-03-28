"""Message Bus — inter-agent message passing."""
from __future__ import annotations
from typing import Any
from collections import defaultdict
from utils.helpers import generate_id, timestamp_now
from utils.logger import get_logger

logger = get_logger("agents.message_bus")


class MessageBus:
    def __init__(self) -> None:
        self._queues: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def send(self, sender: str, receiver: str, content: dict[str, Any]) -> str:
        msg_id = generate_id("msg")
        message = {"id": msg_id, "sender": sender, "receiver": receiver, "content": content, "timestamp": timestamp_now()}
        self._queues[receiver].append(message)
        logger.info("Message %s: %s -> %s", msg_id, sender, receiver)
        return msg_id

    def receive(self, agent_id: str) -> list[dict[str, Any]]:
        messages = self._queues.pop(agent_id, [])
        return messages

    def peek(self, agent_id: str) -> int:
        return len(self._queues.get(agent_id, []))
