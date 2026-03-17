"""
core/orchestrator.py
Coordinates agent lifecycle, task routing, and the main execution loop.
"""

from __future__ import annotations

import structlog

from core.memory import SharedMemory
from core.messaging import Message, MessageBus

logger = structlog.get_logger(__name__)


class Orchestrator:
    """
    Central coordinator for the AI Startup Engine.

    Responsibilities:
    - Register and manage agents
    - Route tasks to the appropriate agent
    - Run the main multi-agent loop
    - Persist results to shared memory
    """

    def __init__(self, memory: SharedMemory | None = None, bus: MessageBus | None = None) -> None:
        self.memory = memory or SharedMemory()
        self.bus = bus or MessageBus()
        self._agents: dict[str, "BaseAgent"] = {}  # noqa: F821
        self._iteration = 0
        logger.info("orchestrator.initialized")

    # ------------------------------------------------------------------ #
    # Agent registry                                                       #
    # ------------------------------------------------------------------ #

    def register(self, agent: "BaseAgent") -> None:  # noqa: F821
        """Add an agent to the roster."""
        self._agents[agent.name] = agent
        agent.attach(memory=self.memory, bus=self.bus)
        logger.info("orchestrator.agent_registered", agent=agent.name, role=agent.role)

    def get_agent(self, name: str) -> "BaseAgent":  # noqa: F821
        if name not in self._agents:
            raise KeyError(f"Agent '{name}' is not registered.")
        return self._agents[name]

    # ------------------------------------------------------------------ #
    # Execution loop                                                       #
    # ------------------------------------------------------------------ #

    def run(self, objective: str) -> dict:
        """
        Execute the full multi-agent pipeline for a given startup objective.

        Args:
            objective: High-level goal (e.g. "Build a SaaS tool for indie hackers").

        Returns:
            Dictionary of outputs keyed by agent name.
        """
        from config import settings

        logger.info("orchestrator.run.start", objective=objective)
        self.memory.store("objective", objective)

        results: dict[str, str] = {}

        # Ordered pipeline: research → ceo → product → engineer → marketing → critic
        pipeline: list[str] = [
            "research",
            "ceo",
            "product",
            "engineer",
            "marketing",
        ]

        if settings.enable_critic:
            pipeline.append("critic")

        for agent_name in pipeline:
            if agent_name not in self._agents:
                logger.warning("orchestrator.agent_missing", agent=agent_name)
                continue

            self._iteration += 1
            if self._iteration > settings.max_iterations:
                logger.warning("orchestrator.max_iterations_reached")
                break

            agent = self._agents[agent_name]
            logger.info("orchestrator.running_agent", agent=agent_name, iteration=self._iteration)

            try:
                output = agent.run(objective=objective, context=results)
                results[agent_name] = output
                self.memory.store(f"output:{agent_name}", output)

                self.bus.publish(
                    Message(
                        sender=agent_name,
                        topic=f"{agent_name}.completed",
                        content=output[:500],
                    )
                )

            except Exception:
                logger.exception("orchestrator.agent_error", agent=agent_name)
                results[agent_name] = "[ERROR] Agent failed — see logs."

        logger.info("orchestrator.run.complete", agents_ran=len(results))
        return results
