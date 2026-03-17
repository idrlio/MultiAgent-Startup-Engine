"""
agents/base_agent.py
Abstract base class that all agents must inherit from.
Provides shared Claude API access, memory, and messaging.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import anthropic
import structlog

if TYPE_CHECKING:
    from core.memory import SharedMemory
    from core.messaging import MessageBus

logger = structlog.get_logger(__name__)


class BaseAgent(ABC):
    """
    Foundation for every agent in the system.

    Subclasses must define:
        - `name`  (str)  — unique agent identifier
        - `role`  (str)  — short human-readable description
        - `system_prompt` (str) — persona injected into every Claude call
        - `run(objective, context)` — core agent logic
    """

    name: str
    role: str
    system_prompt: str

    def __init__(self) -> None:
        from config import settings

        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.model_name
        self._max_tokens = settings.max_tokens
        self.memory: SharedMemory | None = None
        self.bus: MessageBus | None = None
        self._log = logger.bind(agent=self.name)

    def attach(self, memory: "SharedMemory", bus: "MessageBus") -> None:
        """Called by the orchestrator after registration."""
        self.memory = memory
        self.bus = bus

    # ------------------------------------------------------------------ #
    # Core interface                                                       #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def run(self, objective: str, context: dict[str, str]) -> str:
        """
        Execute the agent's primary task.

        Args:
            objective: Top-level startup goal.
            context:   Outputs from previously executed agents.

        Returns:
            String output to be stored in memory and passed downstream.
        """
        ...

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _call_claude(self, user_prompt: str, system: str | None = None) -> str:
        """Send a prompt to Claude and return the text response."""
        system_text = system or self.system_prompt
        self._log.debug("claude.call", prompt_length=len(user_prompt))

        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system_text,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = response.content[0].text
        self._log.debug("claude.response", response_length=len(text))
        return text

    def _build_context_block(self, context: dict[str, str]) -> str:
        """Format prior agent outputs as a readable context block."""
        if not context:
            return ""
        lines = ["## Prior Agent Outputs\n"]
        for agent_name, output in context.items():
            lines.append(f"### {agent_name.upper()}\n{output}\n")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} role={self.role!r}>"
