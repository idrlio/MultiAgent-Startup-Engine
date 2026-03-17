"""
agents/base_agent.py
=====================
Abstract base class that every agent in the system must subclass.

Design principles:
- BaseAgent owns the Claude API client and exposes a clean _call_claude()
  helper so subclasses never touch the raw SDK.
- Agents are stateless between runs; all persistent state goes through
  SharedMemory via the memory property.
- Inter-agent communication is routed exclusively through MessageBus;
  agents never hold references to each other.
- Retry logic and timeout enforcement live here, keeping subclasses clean.
- Lifecycle hooks (on_start, on_complete, on_error) let subclasses react
  to orchestrator events without overriding run().
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import anthropic
import structlog
from tenacity import (
    RetryError,
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

if TYPE_CHECKING:
    from core.memory import SharedMemory
    from core.messaging import MessageBus, Message

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Agent result
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    """
    Structured return value from every agent.run() invocation.

    Attributes:
        agent:      Name of the agent that produced this result.
        content:    Primary text output.
        metadata:   Optional structured data to attach alongside the text.
        duration_s: Wall-clock seconds taken by the agent's run() call.
        success:    False if the agent encountered a handled error.
        error:      Human-readable error description when success is False.
    """

    agent: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    duration_s: float = 0.0
    success: bool = True
    error: str = ""

    def __bool__(self) -> bool:
        return self.success

    def __str__(self) -> str:
        status = "OK" if self.success else f"ERROR: {self.error}"
        return f"<AgentResult agent={self.agent!r} status={status} chars={len(self.content)}>"


# ---------------------------------------------------------------------------
# Base agent
# ---------------------------------------------------------------------------

class BaseAgent(ABC):
    """
    Foundation class for every agent in the AI Startup Engine.

    Subclasses MUST declare the following class-level attributes:

        name          (str) — unique snake_case identifier (e.g. "ceo")
        role          (str) — one-line human-readable description
        system_prompt (str) — persona / instructions injected into every
                              Claude API call made by this agent

    Subclasses MUST implement:

        run(objective, context) -> AgentResult

    Subclasses MAY override lifecycle hooks:

        on_start(objective, context)     — called before run()
        on_complete(result)              — called after a successful run()
        on_error(exc)                    — called when run() raises

    Example::

        class CEOAgent(BaseAgent):
            name = "ceo"
            role = "Chief Executive Officer"
            system_prompt = "You are a strategic CEO..."

            def run(self, objective: str, context: dict[str, AgentResult]) -> AgentResult:
                prompt = self._build_prompt(objective, context)
                content = self._call_claude(prompt)
                return AgentResult(agent=self.name, content=content)
    """

    # Subclasses must define these at class level
    name: str
    role: str
    system_prompt: str

    def __init__(self) -> None:
        from config import settings

        self._settings = settings
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.model_name
        self._max_tokens = settings.max_tokens
        self._timeout = settings.agent_timeout_seconds

        # Injected by the orchestrator via attach()
        self.memory: SharedMemory | None = None
        self.bus: MessageBus | None = None

        self._log = logger.bind(agent=self.name, role=self.role)
        self._log.debug("agent.initialized")

    # ------------------------------------------------------------------
    # Orchestrator lifecycle
    # ------------------------------------------------------------------

    def attach(self, *, memory: "SharedMemory", bus: "MessageBus") -> None:
        """
        Bind shared infrastructure to this agent.

        Called by the Orchestrator immediately after registration.
        After this call, self.memory and self.bus are guaranteed non-None.

        Args:
            memory: The shared memory store for the current run.
            bus:    The inter-agent message bus for the current run.
        """
        self.memory = memory
        self.bus = bus
        self._log.debug("agent.attached")

    def detach(self) -> None:
        """
        Remove the agent's reference to shared infrastructure.

        Useful for garbage collection after a run completes.
        """
        self.memory = None
        self.bus = None
        self._log.debug("agent.detached")

    # ------------------------------------------------------------------
    # Core interface — must be implemented by subclasses
    # ------------------------------------------------------------------

    @abstractmethod
    def run(self, objective: str, context: dict[str, "AgentResult"]) -> AgentResult:
        """
        Execute this agent's primary task.

        Args:
            objective: The top-level startup goal for this run.
            context:   A mapping of agent_name -> AgentResult for all agents
                       that have already completed. Agents earlier in the
                       pipeline appear here; later ones do not.

        Returns:
            An AgentResult containing the agent's output and metadata.

        Raises:
            Should not raise — catch expected errors and return an AgentResult
            with success=False. Truly unexpected errors may propagate and will
            be caught by the Orchestrator.
        """
        ...

    # ------------------------------------------------------------------
    # Lifecycle hooks — override as needed
    # ------------------------------------------------------------------

    def on_start(self, objective: str, context: dict[str, "AgentResult"]) -> None:
        """
        Called by the Orchestrator immediately before run().

        Use this hook to perform setup, emit a "started" bus message, or
        pre-fetch data from memory.

        Args:
            objective: The run objective.
            context:   Results from prior agents.
        """
        self._log.info("agent.start", objective_length=len(objective), prior_agents=list(context))

    def on_complete(self, result: AgentResult) -> None:
        """
        Called by the Orchestrator after a successful run().

        Use this hook to emit completion messages, update memory, or
        trigger downstream actions.

        Args:
            result: The AgentResult returned by run().
        """
        self._log.info(
            "agent.complete",
            duration_s=round(result.duration_s, 2),
            content_chars=len(result.content),
        )

    def on_error(self, exc: Exception) -> None:
        """
        Called by the Orchestrator when run() raises an unhandled exception.

        Args:
            exc: The exception that was raised.
        """
        self._log.error("agent.error", error=str(exc), exc_info=True)

    # ------------------------------------------------------------------
    # Claude API helpers
    # ------------------------------------------------------------------

    @retry(
        retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APITimeoutError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    def _call_claude(
        self,
        user_prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """
        Send a prompt to Claude and return the text response.

        Automatically retries on rate-limit and timeout errors (up to 3
        attempts with exponential back-off).

        Args:
            user_prompt: The user-turn message content.
            system:      Override the class-level system_prompt for this call.
            temperature: Override the default temperature (0.0 – 1.0).
            max_tokens:  Override the default max_tokens limit.

        Returns:
            The model's response as a plain string.

        Raises:
            anthropic.APIError: On non-retryable API errors.
            RetryError:         If all retry attempts are exhausted.
        """
        system_text = system if system is not None else self.system_prompt
        effective_temp = temperature if temperature is not None else self._settings.temperature
        effective_max = max_tokens if max_tokens is not None else self._max_tokens

        self._log.debug(
            "claude.call",
            model=self._model,
            prompt_chars=len(user_prompt),
            max_tokens=effective_max,
        )
        t0 = time.perf_counter()

        response = self._client.messages.create(
            model=self._model,
            max_tokens=effective_max,
            temperature=effective_temp,
            system=system_text,
            messages=[{"role": "user", "content": user_prompt}],
        )

        elapsed = time.perf_counter() - t0
        text: str = response.content[0].text

        self._log.debug(
            "claude.response",
            response_chars=len(text),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            elapsed_s=round(elapsed, 2),
        )
        return text

    # ------------------------------------------------------------------
    # Prompt-building helpers
    # ------------------------------------------------------------------

    def _build_context_block(self, context: dict[str, "AgentResult"]) -> str:
        """
        Render prior agent results as a structured Markdown block suitable
        for injection into a Claude prompt.

        Args:
            context: Mapping of agent_name -> AgentResult.

        Returns:
            Formatted string, or empty string if context is empty.
        """
        if not context:
            return ""

        lines = ["## Prior Agent Outputs\n"]
        for agent_name, result in context.items():
            status = "" if result.success else " [PARTIAL — agent encountered an error]"
            lines.append(f"### {agent_name.upper()}{status}\n{result.content}\n")
        return "\n".join(lines)

    def _build_prompt(self, objective: str, context: dict[str, "AgentResult"]) -> str:
        """
        Compose a full user prompt from the objective and prior context.

        Subclasses can override this for custom prompt structure, or simply
        call _call_claude() with their own hand-crafted prompt.

        Args:
            objective: The run's top-level startup goal.
            context:   Prior agent outputs.

        Returns:
            Assembled prompt string ready to pass to _call_claude().
        """
        ctx_block = self._build_context_block(context)
        parts = [f"## Objective\n{objective}"]
        if ctx_block:
            parts.append(ctx_block)
        parts.append("## Your Task\nBased on the above, fulfil your designated role now.")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Memory & messaging convenience
    # ------------------------------------------------------------------

    def remember(self, key: str, value: Any, ttl: int | None = None) -> None:
        """
        Store a value in shared memory under a namespaced key.

        The key is automatically prefixed with the agent name:
        ``{self.name}:{key}``

        Args:
            key:   Short identifier (e.g. "market_size").
            value: Any JSON-serialisable value.
            ttl:   Optional time-to-live in seconds.
        """
        if self.memory is None:
            self._log.warning("agent.remember.no_memory", key=key)
            return
        namespaced = f"{self.name}:{key}"
        self.memory.store(namespaced, value, ttl=ttl)

    def recall(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a value previously stored by this agent.

        Args:
            key:     The same key passed to remember() (without the prefix).
            default: Value returned when the key is absent or expired.

        Returns:
            Stored value, or *default*.
        """
        if self.memory is None:
            return default
        return self.memory.retrieve(f"{self.name}:{key}") or default

    def emit(self, topic: str, content: str, **payload: Any) -> None:
        """
        Publish a message on the bus from this agent.

        Args:
            topic:   Dot-separated topic string (e.g. "agent.ceo.decision").
            content: Human-readable message body.
            **payload: Additional key-value data attached to Message.payload.
        """
        if self.bus is None:
            self._log.warning("agent.emit.no_bus", topic=topic)
            return

        from core.messaging import Message  # local import avoids circular dep

        msg = Message(
            sender=self.name,
            topic=topic,
            content=content,
            payload=payload,
        )
        self.bus.publish(msg)

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        attached = self.memory is not None
        return (
            f"<{self.__class__.__name__} "
            f"name={self.name!r} "
            f"role={self.role!r} "
            f"attached={attached}>"
        )
