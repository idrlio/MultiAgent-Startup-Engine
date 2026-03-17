"""
core/messaging.py
Lightweight inter-agent messaging bus.
Agents publish messages to named topics; subscribers receive them in order.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class Message:
    """Immutable message passed between agents."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    sender: str = ""
    topic: str = ""
    content: str = ""
    metadata: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __str__(self) -> str:
        return f"[{self.timestamp:%H:%M:%S}] {self.sender} → {self.topic}: {self.content[:80]}"


Handler = Callable[[Message], None]


class MessageBus:
    """
    Simple synchronous pub/sub bus.

    Usage:
        bus = MessageBus()
        bus.subscribe("product.spec_ready", my_handler)
        bus.publish(Message(sender="product", topic="product.spec_ready", content="..."))
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Handler]] = defaultdict(list)
        self._history: list[Message] = []

    def subscribe(self, topic: str, handler: Handler) -> None:
        """Register a callback for a given topic."""
        self._subscribers[topic].append(handler)
        logger.debug("bus.subscribe", topic=topic, handler=handler.__qualname__)

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        handlers = self._subscribers.get(topic, [])
        if handler in handlers:
            handlers.remove(handler)

    def publish(self, message: Message) -> int:
        """
        Dispatch a message to all subscribers of its topic.
        Returns the number of handlers invoked.
        """
        self._history.append(message)
        handlers = self._subscribers.get(message.topic, [])
        logger.info("bus.publish", topic=message.topic, sender=message.sender, handlers=len(handlers))
        for handler in handlers:
            try:
                handler(message)
            except Exception:
                logger.exception("bus.handler_error", topic=message.topic, handler=handler.__qualname__)
        return len(handlers)

    def get_history(self, topic: str | None = None) -> list[Message]:
        """Return message history, optionally filtered by topic."""
        if topic:
            return [m for m in self._history if m.topic == topic]
        return list(self._history)

    def clear_history(self) -> None:
        self._history.clear()
