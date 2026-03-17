"""
agents/base_agent.py
=====================
Abstract base class for every AgentForge agent.

Key upgrades over v1:
- Accepts MemoryManager (combined KV + RAG) instead of raw SharedMemory
- RAG-aware prompt building: automatically retrieves relevant prior context
  from the vector index and injects it into each Claude call
- _call_claude() feeds agent output back into the vector index post-response
  so future agents can retrieve it semantically
- Lifecycle hooks: on_start / on_complete / on_error
- Retry on RateLimitError / APITimeoutError via tenacity
- AgentResult typed return value with success flag, metadata, duration
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import anthropic
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

if TYPE_CHECKING:
    from core.memory import MemoryManager
    from core.messaging import MessageBus

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# AgentResult
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    """
    Structured return value from every agent.run() call.

    Attributes:
        agent:       Agent name that produced this result.
        content:     Primary text output (Markdown).
        metadata:    Structured data the agent wants to surface alongside text.
        duration_s:  Wall-clock seconds for the run() invocation.
        success:     False when the agent encountered a handled error.
        error:       Human-readable description when success is False.
        iteration:   Which feedback-loop iteration produced this result (0 = first).
    """

    agent: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    duration_s: float = 0.0
    success: bool = True
    error: str = ""
    iteration: int = 0

    def __bool__(self) -> bool:
        return self.success

    def __str__(self) -> str:
        status = "OK" if self.success else f"ERROR: {self.error}"
        return f"<AgentResult agent={self.agent!r} status={status} chars={len(self.content)}>"


# ---------------------------------------------------------------------------
# BaseAgent
# ---------------------------------------------------------------------------

class BaseAgent(ABC):
    """
    Foundation for every agent in the AgentForge system.

    Subclasses MUST declare:
        name          (str) — unique snake_case identifier
        role          (str) — one-line description
        system_prompt (str) — persona injected into every Claude call

    Subclasses MUST implement:
        run(objective, context) -> AgentResult

    Subclasses MAY override:
        on_start(objective, context)
        on_complete(result)
        on_error(exc)
        _build_prompt(objective, context)   — for custom prompt structure

    RAG enrichment is automatic: _call_claude() retrieves semantically
    relevant chunks from the vector index and prepends them to the prompt
    when available.
    """

    name: str
    role: str
    system_prompt: str

    def __init__(self) -> None:
        from config import settings

        self._settings = settings
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.model_name
        self._max_tokens = settings.max_tokens

        # Injected by orchestrator via attach()
        self.memory: MemoryManager | None = None
        self.bus: MessageBus | None = None

        self._log = logger.bind(agent=self.name, role=self.role)
        self._log.debug("agent.initialized")

    # ------------------------------------------------------------------
    # Lifecycle — called by Orchestrator
    # ------------------------------------------------------------------

    def attach(self, *, memory: "MemoryManager", bus: "MessageBus") -> None:
        """Bind shared infrastructure. Called by Orchestrator after registration."""
        self.memory = memory
        self.bus = bus
        self._log.debug("agent.attached")

    def detach(self) -> None:
        """Release shared infrastructure references."""
        self.memory = None
        self.bus = None
        self._log.debug("agent.detached")

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    @abstractmethod
    def run(self, objective: str, context: dict[str, AgentResult]) -> AgentResult:
        """
        Execute this agent's primary task.

        Args:
            objective: Top-level startup goal for this run.
            context:   AgentResult objects from all prior agents.

        Returns:
            AgentResult with the agent's output and metadata.
        """
        ...

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def on_start(self, objective: str, context: dict[str, AgentResult]) -> None:
        """Called by Orchestrator immediately before run()."""
        self._log.info("agent.start", prior_agents=list(context))

    def on_complete(self, result: AgentResult) -> None:
        """Called by Orchestrator after a successful run()."""
        self._log.info(
            "agent.complete",
            duration_s=round(result.duration_s, 2),
            content_chars=len(result.content),
            iteration=result.iteration,
        )

    def on_error(self, exc: Exception) -> None:
        """Called by Orchestrator when run() raises an unhandled exception."""
        self._log.error("agent.error", error=str(exc), exc_info=True)

    # ------------------------------------------------------------------
    # Claude API
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
        index_response: bool = True,
    ) -> str:
        """
        Send a prompt to Claude and return the text response.

        RAG enrichment: before calling Claude the method retrieves relevant
        chunks from the vector index and prepends them to the prompt.
        After a successful response the output is automatically indexed so
        future agents can retrieve it semantically.

        Args:
            user_prompt:    The user-turn message.
            system:         Override the class-level system_prompt.
            temperature:    Override default temperature.
            max_tokens:     Override default max_tokens.
            index_response: Whether to index the response in vector memory.

        Returns:
            Model response as a plain string.
        """
        # --- RAG enrichment ---
        rag_block = self._retrieve_rag_context(user_prompt)
        if rag_block:
            user_prompt = f"{rag_block}\n\n---\n\n{user_prompt}"

        system_text = system if system is not None else self.system_prompt
        effective_temp = temperature if temperature is not None else self._settings.temperature
        effective_max = max_tokens if max_tokens is not None else self._max_tokens

        self._log.debug(
            "claude.call",
            model=self._model,
            prompt_chars=len(user_prompt),
            rag_enriched=bool(rag_block),
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

        # --- Auto-index output for downstream RAG ---
        if index_response and self.memory:
            self.memory.index(text, source=self.name)

        return text

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _build_prompt(self, objective: str, context: dict[str, AgentResult]) -> str:
        """
        Compose the full user prompt from objective + prior agent context.

        Subclasses can override this to customise the prompt structure.
        The RAG block is injected automatically inside _call_claude().
        """
        parts = [f"## Objective\n{objective}"]
        ctx_block = self._build_context_block(context)
        if ctx_block:
            parts.append(ctx_block)
        parts.append("## Your Task\nBased on the above, fulfil your designated role now.")
        return "\n\n".join(parts)

    def _build_context_block(self, context: dict[str, AgentResult]) -> str:
        """Render prior AgentResult objects as a Markdown context block."""
        if not context:
            return ""
        lines = ["## Prior Agent Outputs\n"]
        for agent_name, result in context.items():
            note = "" if result.success else " *(partial — agent error)*"
            lines.append(f"### {agent_name.upper()}{note}\n{result.content}\n")
        return "\n".join(lines)

    def _retrieve_rag_context(self, query: str) -> str:
        """
        Query the vector index for chunks relevant to *query*.
        Returns a formatted Markdown block, or an empty string.
        """
        if self.memory is None:
            return ""
        return self.memory.rag_context(query)

    # ------------------------------------------------------------------
    # Memory & messaging helpers
    # ------------------------------------------------------------------

    def remember(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Store *value* in KV memory under namespaced key ``{agent}:{key}``."""
        if self.memory is None:
            self._log.warning("agent.remember.no_memory", key=key)
            return
        self.memory.store(f"{self.name}:{key}", value, ttl)

    def recall(self, key: str, default: Any = None) -> Any:
        """Retrieve a value previously stored by this agent."""
        if self.memory is None:
            return default
        return self.memory.retrieve(f"{self.name}:{key}") or default

    def emit(self, topic: str, content: str, **payload: Any) -> None:
        """Publish a message on the bus from this agent."""
        if self.bus is None:
            self._log.warning("agent.emit.no_bus", topic=topic)
            return
        from core.messaging import Message
        self.bus.publish(Message(sender=self.name, topic=topic, content=content, payload=payload))

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"name={self.name!r} "
            f"attached={self.memory is not None}>"
        )
