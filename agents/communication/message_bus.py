"""MessageBus — publish/subscribe message delivery for agent communication."""

from __future__ import annotations

import copy
import threading
import uuid
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger("agents.message_bus")


class MessageBus:
    """In-process pub/sub message bus.

    Subscribers receive messages on topics they subscribe to.  An optional
    callback is invoked on publish; messages are also stored for later
    retrieval via ``get_messages``.

    Thread-safe via an internal RLock — publishers and subscribers can
    operate concurrently. The per-topic message queue is bounded so a
    long-running daemon doesn't slowly leak memory through high-volume
    topics.
    """

    # Cap on retained messages per topic. Older entries are dropped
    # FIFO once the cap is reached so the queue can't grow forever.
    _MAX_MESSAGES_PER_TOPIC = 1000

    def __init__(self, max_messages_per_topic: int | None = None) -> None:
        # topic -> list of {subscriber_id, callback}
        self._topics: dict[str, list[dict]] = {}
        # topic -> list of message dicts
        self._message_queue: dict[str, list[dict]] = {}
        # RLock so a callback that re-enters the bus doesn't deadlock.
        self._lock = threading.RLock()
        self._max_per_topic = int(
            max_messages_per_topic or self._MAX_MESSAGES_PER_TOPIC
        )

    @staticmethod
    def _generate_message_id() -> str:
        return f"msg-{uuid.uuid4().hex[:16]}"

    def publish(self, topic: str, message: dict, sender: str) -> str:
        """Publish a message to a topic. Returns the generated message id."""
        msg_id = self._generate_message_id()
        # Deep-copy the payload so the publisher mutating the original
        # dict after publish() can't bleed into the stored envelope.
        # Coerces non-dict messages defensively to {"raw": ...}.
        if isinstance(message, dict):
            payload = copy.deepcopy(message)
        else:
            payload = {"raw": str(message)[:500]}
        envelope = {
            "id": msg_id,
            "topic": topic,
            "sender": sender,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        with self._lock:
            queue = self._message_queue.setdefault(topic, [])
            queue.append(envelope)
            # Trim FIFO once we exceed the cap. Without this, a high-
            # volume topic in a long-running daemon would silently leak
            # memory.
            if len(queue) > self._max_per_topic:
                self._message_queue[topic] = queue[-self._max_per_topic:]
            # Snapshot subscribers under the lock so concurrent
            # subscribe/unsubscribe doesn't mutate the iterator.
            subscribers = list(self._topics.get(topic, []))

        # Fire callbacks OUTSIDE the lock so a slow handler can't
        # block other publishers/subscribers. Failures log a warning
        # — the previous version swallowed every callback exception
        # silently with `except: pass`, so a broken handler was
        # invisible to the operator.
        for subscriber in subscribers:
            cb = subscriber.get("callback")
            if cb is None:
                continue
            try:
                cb(envelope)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "MessageBus: subscriber %r callback raised on topic %r (%s)",
                    subscriber.get("subscriber_id"), topic, exc,
                )

        return msg_id

    def subscribe(
        self, topic: str, subscriber_id: str, callback=None
    ) -> None:
        """Subscribe to a topic. Optionally provide a callback(message)."""
        with self._lock:
            subs = self._topics.setdefault(topic, [])

            # Prevent duplicate subscriptions for the same subscriber on this topic
            for sub in subs:
                if sub.get("subscriber_id") == subscriber_id:
                    sub["callback"] = callback
                    return

            subs.append({"subscriber_id": subscriber_id, "callback": callback})

    def unsubscribe(self, topic: str, subscriber_id: str) -> None:
        """Remove a subscriber from a topic."""
        with self._lock:
            if topic not in self._topics:
                return
            self._topics[topic] = [
                s for s in self._topics[topic]
                if s.get("subscriber_id") != subscriber_id
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
        with self._lock:
            # Determine which topics the subscriber is on
            subscribed_topics: set[str] = set()
            for t, subs in self._topics.items():
                for sub in subs:
                    if sub.get("subscriber_id") == subscriber_id:
                        subscribed_topics.add(t)
                        break

            if topic is not None:
                if topic not in subscribed_topics:
                    return []
                subscribed_topics = {topic}

            results: list[dict] = []
            for t in subscribed_topics:
                for msg in self._message_queue.get(t, []):
                    msg_ts = msg.get("timestamp", "")
                    if since is not None and msg_ts <= since:
                        continue
                    # Deep copy so caller mutation can't poison the
                    # in-memory queue or another reader.
                    results.append(copy.deepcopy(msg))

        # Sort by timestamp ascending. Defensive .get so a malformed
        # entry without a timestamp lands at the start instead of
        # crashing the sort.
        results.sort(key=lambda m: m.get("timestamp", ""))
        return results

    def get_stats(self) -> dict:
        """Return per-topic queue depth + subscriber counts."""
        with self._lock:
            return {
                "topics": {
                    t: {
                        "queued_messages": len(self._message_queue.get(t, [])),
                        "subscribers": len(self._topics.get(t, [])),
                    }
                    for t in set(self._topics) | set(self._message_queue)
                },
                "max_messages_per_topic": self._max_per_topic,
            }
