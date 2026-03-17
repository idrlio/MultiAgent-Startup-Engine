"""
core/messaging.py
==================
Structured inter-agent messaging system.

Design principles:
- Messages are immutable value objects with typed payloads.
- The MessageBus is the single communication channel; agents never call
  each other directly.
- Topic routing uses dot-separated namespaces (e.g. "agent.ceo.completed")
  with optional wildcard subscription ("agent.*.completed").
- Every message is appended to an append-only history so the orchestrator
  can reconstruct the full execution trace.
- Handler errors are isolated: one bad subscriber never silences others.
"""

from __future__ import annotations

import fnmatch
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Iterator

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class MessagePriority(int, Enum):
    """Delivery priority hint for future async implementations."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class MessageStatus(str, Enum):
    """Lifecycle state of a message after publication."""
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    NO_SUBSCRIBERS = "no_subscribers"


# ---------------------------------------------------------------------------
# Core value objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Message:
    """
    Immutable, self-describing message exchanged between agents.

    Attributes:
        id:           Unique message identifier (UUID4).
        sender:       Name of the originating agent or system component.
        recipient:    Optional target agent name; empty string means broadcast.
        topic:        Dot-separated routing key (e.g. "agent.research.completed").
        content:      Human-readable payload — the main text body.
        payload:      Arbitrary structured data attached to this message.
        priority:     Delivery priority (default: NORMAL).
        reply_to:     ID of the message this is responding to, if any.
        timestamp:    UTC creation time (auto-set on construction).
        metadata:     Optional key-value annotations (tracing, versioning, ...).
    """

    sender: str
    topic: str
    content: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    recipient: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    priority: MessagePriority = MessagePriority.NORMAL
    reply_to: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def reply(cls, original: "Message", sender: str, content: str, **kwargs: Any) -> "Message":
        """Create a reply that is automatically addressed to the original sender."""
        return cls(
            sender=sender,
            recipient=original.sender,
            topic=f"{original.topic}.reply",
            content=content,
            reply_to=original.id,
            **kwargs,
        )

    @classmethod
    def broadcast(cls, sender: str, topic: str, content: str, **kwargs: Any) -> "Message":
        """Create a message with no specific recipient (broadcast to all subscribers)."""
        return cls(sender=sender, topic=topic, content=content, **kwargs)

    def with_payload(self, **data: Any) -> "Message":
        """Return a copy of this message with additional payload fields merged in."""
        import dataclasses
        return dataclasses.replace(self, payload={**self.payload, **data})

    def __str__(self) -> str:
        ts = self.timestamp.strftime("%H:%M:%S.%f")[:-3]
        recipient = f" -> {self.recipient}" if self.recipient else " -> *"
        return (
            f"[{ts}] [{self.priority.name}] "
            f"{self.sender}{recipient} [{self.topic}]: {self.content[:120]}"
        )


# ---------------------------------------------------------------------------
# Typing alias
# ---------------------------------------------------------------------------

Handler = Callable[[Message], None]


# ---------------------------------------------------------------------------
# Delivery receipt
# ---------------------------------------------------------------------------

@dataclass
class DeliveryReceipt:
    """
    Returned by MessageBus.publish() to give the caller full visibility
    into how the message was handled.

    Attributes:
        message_id:       ID of the published message.
        status:           Final delivery status.
        handlers_invoked: Number of subscribers that received the message.
        failed_handlers:  Qualified names of handlers that raised an exception.
    """

    message_id: str
    status: MessageStatus
    handlers_invoked: int
    failed_handlers: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """True when at least one handler was invoked without error."""
        return self.status == MessageStatus.DELIVERED and not self.failed_handlers


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------

@dataclass
class Subscription:
    """
    Represents a registered topic-pattern -> handler mapping.

    Topic patterns use fnmatch glob syntax:
        - "agent.ceo.*"         matches any sub-topic under agent.ceo
        - "agent.*.completed"   matches all agent completion events
        - "*"                   matches every topic
    """

    topic_pattern: str
    handler: Handler
    subscriber_name: str = ""

    def matches(self, topic: str) -> bool:
        """Return True if *topic* satisfies this subscription's pattern."""
        return fnmatch.fnmatch(topic, self.topic_pattern)

    def __repr__(self) -> str:
        return (
            f"<Subscription pattern={self.topic_pattern!r} "
            f"handler={self.handler.__qualname__!r} "
            f"subscriber={self.subscriber_name!r}>"
        )


# ---------------------------------------------------------------------------
# Message bus
# ---------------------------------------------------------------------------

class MessageBus:
    """
    Synchronous publish/subscribe message bus for inter-agent communication.

    Key design decisions
    --------------------
    * **Topic patterns** — subscriptions use fnmatch glob syntax so a
      single handler can cover a family of topics ("agent.*.completed").
    * **Isolation** — an exception in one handler is caught, logged, and
      recorded in the DeliveryReceipt, but does NOT prevent remaining
      handlers from executing.
    * **Append-only history** — every published message is stored in order;
      consumers can replay or audit the full conversation trace.
    * **Direct routing** — if a message carries a non-empty ``recipient``
      field, only handlers registered under that subscriber name are invoked
      (alongside broadcast handlers with no subscriber_name).

    Example::

        bus = MessageBus()

        def on_research_done(msg: Message) -> None:
            print(f"Research complete: {msg.content[:60]}")

        bus.subscribe("agent.research.completed", on_research_done, subscriber="ceo")

        receipt = bus.publish(
            Message(
                sender="research",
                topic="agent.research.completed",
                content="Market analysis finished.",
                priority=MessagePriority.HIGH,
            )
        )
        assert receipt.success
    """

    def __init__(self) -> None:
        self._subscriptions: list[Subscription] = []
        self._history: list[Message] = []
        self._dead_letter: list[tuple[Message, str]] = []

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    def subscribe(
        self,
        topic_pattern: str,
        handler: Handler,
        *,
        subscriber_name: str = "",
    ) -> Subscription:
        """
        Register *handler* to be invoked for messages matching *topic_pattern*.

        Args:
            topic_pattern:   Glob-style topic filter (e.g. "agent.*").
            handler:         Callable that accepts a Message instance.
            subscriber_name: Optional label used for direct-routing and
                             debugging output.

        Returns:
            The Subscription object (pass to unsubscribe() to deregister).
        """
        sub = Subscription(
            topic_pattern=topic_pattern,
            handler=handler,
            subscriber_name=subscriber_name,
        )
        self._subscriptions.append(sub)
        logger.debug(
            "bus.subscribe",
            pattern=topic_pattern,
            handler=handler.__qualname__,
            subscriber=subscriber_name,
        )
        return sub

    def unsubscribe(self, subscription: Subscription) -> bool:
        """
        Remove a previously registered subscription.

        Args:
            subscription: The Subscription object returned by subscribe().

        Returns:
            True if the subscription was found and removed, False otherwise.
        """
        try:
            self._subscriptions.remove(subscription)
            logger.debug(
                "bus.unsubscribe",
                pattern=subscription.topic_pattern,
                subscriber=subscription.subscriber_name,
            )
            return True
        except ValueError:
            return False

    def unsubscribe_all(self, subscriber_name: str) -> int:
        """
        Remove all subscriptions registered under *subscriber_name*.

        Args:
            subscriber_name: The name used when calling subscribe().

        Returns:
            The number of subscriptions removed.
        """
        before = len(self._subscriptions)
        self._subscriptions = [
            s for s in self._subscriptions if s.subscriber_name != subscriber_name
        ]
        removed = before - len(self._subscriptions)
        logger.debug("bus.unsubscribe_all", subscriber=subscriber_name, removed=removed)
        return removed

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish(self, message: Message) -> DeliveryReceipt:
        """
        Dispatch *message* to all matching subscribers.

        Matching rules:
          1. The subscription's topic_pattern must match message.topic
             (glob / fnmatch semantics).
          2. If message.recipient is non-empty, only subscriptions whose
             subscriber_name equals message.recipient (or is empty) are
             invoked.

        All handlers are called even if a prior one raises — errors are
        isolated, captured in the DeliveryReceipt, and forwarded to the
        dead-letter queue for inspection.

        Args:
            message: The Message to dispatch.

        Returns:
            A DeliveryReceipt describing delivery outcome.
        """
        self._history.append(message)

        matched = self._resolve_subscribers(message)
        failed: list[str] = []

        for sub in matched:
            try:
                sub.handler(message)
            except Exception:
                label = sub.handler.__qualname__
                failed.append(label)
                self._dead_letter.append((message, label))
                logger.exception(
                    "bus.handler_error",
                    topic=message.topic,
                    handler=label,
                    message_id=message.id,
                )

        if not matched:
            status = MessageStatus.NO_SUBSCRIBERS
        elif len(failed) == len(matched):
            status = MessageStatus.FAILED
        else:
            status = MessageStatus.DELIVERED

        receipt = DeliveryReceipt(
            message_id=message.id,
            status=status,
            handlers_invoked=len(matched),
            failed_handlers=failed,
        )

        logger.info(
            "bus.publish",
            topic=message.topic,
            sender=message.sender,
            recipient=message.recipient or "*",
            priority=message.priority.name,
            handlers_invoked=len(matched),
            failed=len(failed),
            status=status.value,
        )
        return receipt

    # ------------------------------------------------------------------
    # History & introspection
    # ------------------------------------------------------------------

    def history(
        self,
        *,
        topic_pattern: str | None = None,
        sender: str | None = None,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[Message]:
        """
        Query the append-only message history with optional filters.

        Args:
            topic_pattern: Glob filter applied to message.topic.
            sender:        If provided, only messages from this sender.
            since:         If provided, only messages after this UTC datetime.
            limit:         Maximum number of messages to return (most recent).

        Returns:
            Filtered list of Message objects in chronological order.
        """
        stream: Iterator[Message] = iter(self._history)

        if topic_pattern:
            stream = (m for m in stream if fnmatch.fnmatch(m.topic, topic_pattern))
        if sender:
            stream = (m for m in stream if m.sender == sender)
        if since:
            stream = (m for m in stream if m.timestamp >= since)

        result = list(stream)
        if limit is not None:
            result = result[-limit:]
        return result

    def dead_letters(self) -> list[tuple[Message, str]]:
        """Return messages whose handlers all raised exceptions."""
        return list(self._dead_letter)

    def clear_history(self) -> None:
        """Wipe the message history and dead-letter queue. Intended for tests."""
        self._history.clear()
        self._dead_letter.clear()
        logger.debug("bus.history_cleared")

    def stats(self) -> dict[str, Any]:
        """Return a snapshot of bus health and throughput metrics."""
        topic_counts: dict[str, int] = defaultdict(int)
        for m in self._history:
            topic_counts[m.topic] += 1
        return {
            "total_messages": len(self._history),
            "dead_letters": len(self._dead_letter),
            "active_subscriptions": len(self._subscriptions),
            "topics": dict(topic_counts),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_subscribers(self, message: Message) -> list[Subscription]:
        """
        Return subscriptions that should receive *message*, applying both
        topic-pattern matching and optional direct-recipient filtering.
        """
        result = []
        for sub in self._subscriptions:
            if not sub.matches(message.topic):
                continue
            # Direct routing: if a recipient is specified, only deliver to
            # that named subscriber (or to broadcast subs with no name).
            if message.recipient and sub.subscriber_name:
                if sub.subscriber_name != message.recipient:
                    continue
            result.append(sub)
        return result

    def __repr__(self) -> str:
        return (
            f"<MessageBus subscriptions={len(self._subscriptions)} "
            f"history={len(self._history)} "
            f"dead_letters={len(self._dead_letter)}>"
        )
