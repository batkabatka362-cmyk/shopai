"""MessageBus — publish/subscribe message delivery for agent communication."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


class MessageBus:
    """In-process pub/sub message bus.

    Subscribers receive messages on topics they subscribe to.  An optional
    callback is invoked on publish; messages are also stored for later
    retrieval via ``get_messages``.
    """

    def __init__(self) -> None:
        # topic -> list of {subscriber_id, callback}
        self._topics: dict[str, list[dict]] = {}
        # topic -> list of message dicts
        self._message_queue: dict[str, list[dict]] = {}

    @staticmethod
    def _generate_message_id() -> str:
        return f"msg-{uuid.uuid4().hex[:16]}"

    def publish(self, topic: str, message: dict, sender: str) -> str:
        """Publish a message to a topic. Returns the generated message id."""
        msg_id = self._generate_message_id()
        envelope = {
            "id": msg_id,
            "topic": topic,
            "sender": sender,
            "payload": dict(message),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Store message in queue
        self._message_queue.setdefault(topic, []).append(envelope)

        # Notify subscribers with callbacks
        for subscriber in self._topics.get(topic, []):
            cb = subscriber.get("callback")
            if cb is not None:
                try:
                    cb(envelope)
                except Exception:
                    pass  # fire-and-forget; callers can log separately

        return msg_id

    def subscribe(
        self, topic: str, subscriber_id: str, callback: callable = None
    ) -> None:
        """Subscribe to a topic. Optionally provide a callback(message)."""
        subs = self._topics.setdefault(topic, [])

        # Prevent duplicate subscriptions for the same subscriber on this topic
        for sub in subs:
            if sub["subscriber_id"] == subscriber_id:
                sub["callback"] = callback
                return

        subs.append({"subscriber_id": subscriber_id, "callback": callback})

    def unsubscribe(self, topic: str, subscriber_id: str) -> None:
        """Remove a subscriber from a topic."""
        if topic not in self._topics:
            return
        self._topics[topic] = [
            s for s in self._topics[topic] if s["subscriber_id"] != subscriber_id
        ]

    def get_messages(
        self,
        subscriber_id: str,
        topic: str | None = None,
        since: str | None = None,
    ) -> list[dict]:
        """Retrieve messages for a subscriber.

        Parameters
        ----------
        subscriber_id:
            Only return messages from topics this id is subscribed to.
        topic:
            If provided, restrict to this single topic.
        since:
            ISO-8601 timestamp; only messages after this time are returned.
        """
        # Determine which topics the subscriber is on
        subscribed_topics: set[str] = set()
        for t, subs in self._topics.items():
            for sub in subs:
                if sub["subscriber_id"] == subscriber_id:
                    subscribed_topics.add(t)
                    break

        if topic is not None:
            if topic not in subscribed_topics:
                return []
            subscribed_topics = {topic}

        results: list[dict] = []
        for t in subscribed_topics:
            for msg in self._message_queue.get(t, []):
                if since is not None and msg["timestamp"] <= since:
                    continue
                results.append(dict(msg))

        # Sort by timestamp ascending
        results.sort(key=lambda m: m["timestamp"])
        return results
