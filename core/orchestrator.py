"""
core/orchestrator.py
=====================
Central coordinator for the AI Startup Engine.

Design principles:
- The Orchestrator owns the agent registry and is the single point of
  authority over execution order.
- Workflows are first-class objects: a Workflow is an ordered list of steps,
  each of which may be sequential or parallel (parallel reserved for future
  async extension).
- Every agent run is wrapped in a structured ExecutionRecord that captures
  timing, status, and result — giving the caller a full audit trail.
- The Orchestrator emits bus events at every stage so external listeners
  (logging sinks, UI layers, test harnesses) can observe progress without
  coupling to internal state.
- Failures are isolated per-agent; one failing agent does not halt the
  pipeline unless it is declared a required dependency of the next step.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import structlog

from agents.base_agent import AgentResult, BaseAgent
from core.memory import SharedMemory
from core.messaging import Message, MessageBus, MessagePriority

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class RunStatus(str, Enum):
    """Overall status of an orchestrated run."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"       # some agents failed but run finished
    FAILED = "failed"         # run aborted due to critical failure


class StepStatus(str, Enum):
    """Status of a single step within a workflow."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Workflow primitives
# ---------------------------------------------------------------------------

@dataclass
class WorkflowStep:
    """
    A single step in a Workflow.

    Attributes:
        agent_name:  Name of the agent to invoke.
        required:    If True and this step fails, the run aborts immediately.
        depends_on:  Names of prior steps that must have SUCCEEDED before
                     this step is allowed to run. An empty list means the
                     step can always run (respecting pipeline order).
    """

    agent_name: str
    required: bool = False
    depends_on: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        flags = []
        if self.required:
            flags.append("required")
        if self.depends_on:
            flags.append(f"depends_on={self.depends_on}")
        tag = f" [{', '.join(flags)}]" if flags else ""
        return f"<WorkflowStep {self.agent_name!r}{tag}>"


@dataclass
class Workflow:
    """
    An ordered sequence of WorkflowStep objects that the Orchestrator
    executes on behalf of a caller.

    Attributes:
        name:         Human-readable workflow identifier.
        steps:        Ordered list of steps to execute.
        description:  Optional long-form description.
    """

    name: str
    steps: list[WorkflowStep]
    description: str = ""

    @classmethod
    def linear(cls, name: str, agent_names: list[str], *, required: bool = False) -> "Workflow":
        """
        Create a simple linear workflow where every step follows the previous.

        Args:
            name:         Workflow name.
            agent_names:  Ordered list of agent names.
            required:     Whether all steps are required (default False).

        Returns:
            A Workflow with one WorkflowStep per agent.
        """
        steps = [WorkflowStep(agent_name=n, required=required) for n in agent_names]
        return cls(name=name, steps=steps)

    def __len__(self) -> int:
        return len(self.steps)

    def __repr__(self) -> str:
        return f"<Workflow name={self.name!r} steps={len(self.steps)}>"


# ---------------------------------------------------------------------------
# Execution records
# ---------------------------------------------------------------------------

@dataclass
class StepRecord:
    """Audit record for a single workflow step execution."""

    step: WorkflowStep
    status: StepStatus = StepStatus.PENDING
    result: AgentResult | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str = ""

    @property
    def duration_s(self) -> float:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0.0


@dataclass
class RunRecord:
    """
    Full audit trail for a single Orchestrator.run() invocation.

    Attributes:
        run_id:     Unique identifier for this run.
        objective:  The startup goal passed to run().
        workflow:   The Workflow that was executed.
        status:     Overall run status.
        steps:      One StepRecord per workflow step.
        started_at: UTC timestamp when the run began.
        finished_at: UTC timestamp when the run ended (None if still running).
        metadata:   Arbitrary annotations (e.g. caller info, environment).
    """

    run_id: str
    objective: str
    workflow: Workflow
    status: RunStatus = RunStatus.PENDING
    steps: list[StepRecord] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        if self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0.0

    @property
    def results(self) -> dict[str, AgentResult]:
        """Convenience mapping of agent_name -> AgentResult for completed steps."""
        return {
            rec.step.agent_name: rec.result
            for rec in self.steps
            if rec.result is not None
        }

    @property
    def failed_steps(self) -> list[StepRecord]:
        return [r for r in self.steps if r.status == StepStatus.FAILED]

    @property
    def succeeded_steps(self) -> list[StepRecord]:
        return [r for r in self.steps if r.status == StepStatus.SUCCEEDED]

    def __repr__(self) -> str:
        return (
            f"<RunRecord id={self.run_id[:8]} "
            f"status={self.status.value} "
            f"steps={len(self.succeeded_steps)}/{len(self.steps)} succeeded>"
        )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    """
    Central coordinator for the AI Startup Engine.

    Responsibilities
    ----------------
    * **Agent registry** — register, retrieve, and manage agent lifecycle.
    * **Workflow execution** — run ordered, dependency-aware pipelines.
    * **Multi-step coordination** — pass prior results as context to each
      subsequent agent, building cumulative knowledge through the pipeline.
    * **Event emission** — publish structured bus messages at every stage so
      external consumers can observe execution without polling.
    * **Audit trail** — return a RunRecord that captures every step's timing,
      status, and output for post-run inspection or persistence.

    Usage::

        memory = SharedMemory()
        bus = MessageBus()
        orchestrator = Orchestrator(memory=memory, bus=bus)

        orchestrator.register(ResearchAgent())
        orchestrator.register(CEOAgent())
        orchestrator.register(ProductAgent())

        workflow = Workflow.linear(
            "startup-engine",
            ["research", "ceo", "product"],
        )
        record = orchestrator.run(
            objective="Build a SaaS tool for indie hackers",
            workflow=workflow,
        )
        print(record.status)           # RunStatus.COMPLETED
        print(record.results["ceo"])   # AgentResult(...)
    """

    # Topics emitted on the bus during a run
    TOPIC_RUN_STARTED = "orchestrator.run.started"
    TOPIC_RUN_COMPLETED = "orchestrator.run.completed"
    TOPIC_STEP_STARTED = "orchestrator.step.started"
    TOPIC_STEP_COMPLETED = "orchestrator.step.completed"
    TOPIC_STEP_FAILED = "orchestrator.step.failed"
    TOPIC_STEP_SKIPPED = "orchestrator.step.skipped"

    def __init__(
        self,
        memory: SharedMemory | None = None,
        bus: MessageBus | None = None,
    ) -> None:
        self._memory = memory or SharedMemory()
        self._bus = bus or MessageBus()
        self._agents: dict[str, BaseAgent] = {}
        self._run_history: list[RunRecord] = []
        logger.info("orchestrator.initialized")

    # ------------------------------------------------------------------
    # Agent registry
    # ------------------------------------------------------------------

    def register(self, agent: BaseAgent) -> None:
        """
        Add an agent to the registry and inject shared infrastructure.

        After registration the agent's memory and bus properties are set;
        it is fully ready to be used in a workflow.

        Args:
            agent: An instantiated BaseAgent subclass.

        Raises:
            ValueError: If an agent with the same name is already registered.
        """
        if agent.name in self._agents:
            raise ValueError(
                f"Agent '{agent.name}' is already registered. "
                "Unregister it first or use a different name."
            )
        agent.attach(memory=self._memory, bus=self._bus)
        self._agents[agent.name] = agent
        logger.info(
            "orchestrator.agent_registered",
            agent=agent.name,
            role=agent.role,
            total_agents=len(self._agents),
        )

    def unregister(self, agent_name: str) -> bool:
        """
        Remove an agent from the registry and detach its infrastructure.

        Args:
            agent_name: The name of the agent to remove.

        Returns:
            True if the agent was found and removed, False otherwise.
        """
        agent = self._agents.pop(agent_name, None)
        if agent is None:
            return False
        agent.detach()
        logger.info("orchestrator.agent_unregistered", agent=agent_name)
        return True

    def get_agent(self, name: str) -> BaseAgent:
        """
        Retrieve a registered agent by name.

        Args:
            name: Agent identifier.

        Returns:
            The registered BaseAgent instance.

        Raises:
            KeyError: If no agent with *name* is registered.
        """
        if name not in self._agents:
            raise KeyError(
                f"Agent '{name}' is not registered. "
                f"Available agents: {list(self._agents)}"
            )
        return self._agents[name]

    @property
    def agents(self) -> dict[str, BaseAgent]:
        """Read-only view of the agent registry."""
        return dict(self._agents)

    # ------------------------------------------------------------------
    # Workflow execution
    # ------------------------------------------------------------------

    def run(
        self,
        objective: str,
        *,
        workflow: Workflow | None = None,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunRecord:
        """
        Execute a workflow for the given startup objective.

        If *workflow* is omitted, a default linear pipeline is built from
        every registered agent in registration order.

        Each agent receives the *objective* plus an accumulated context dict
        containing the AgentResult of every agent that ran before it.
        Results are also stored in shared memory under ``output:{agent_name}``.

        A bus event is emitted at the start and end of the run and at the
        start, completion, and failure of every individual step.

        Args:
            objective: High-level startup goal
                       (e.g. "Build a SaaS CRM for freelancers").
            workflow:  Optional Workflow describing execution order and
                       constraints. Defaults to a linear pipeline over all
                       registered agents.
            run_id:    Optional caller-supplied run identifier. A UUID4 is
                       generated automatically when omitted.
            metadata:  Arbitrary annotations attached to the RunRecord.

        Returns:
            A RunRecord capturing the full execution trace.
        """
        from config import settings

        effective_workflow = workflow or Workflow.linear(
            name="default",
            agent_names=list(self._agents),
        )
        effective_run_id = run_id or str(uuid.uuid4())

        record = RunRecord(
            run_id=effective_run_id,
            objective=objective,
            workflow=effective_workflow,
            status=RunStatus.RUNNING,
            metadata=metadata or {},
        )

        logger.info(
            "orchestrator.run.start",
            run_id=effective_run_id,
            objective=objective,
            workflow=effective_workflow.name,
            steps=len(effective_workflow.steps),
        )

        self._memory.store("run:id", effective_run_id)
        self._memory.store("run:objective", objective)

        self._emit(
            self.TOPIC_RUN_STARTED,
            content=f"Run {effective_run_id[:8]} started: {objective[:100]}",
            payload={"run_id": effective_run_id, "objective": objective},
            priority=MessagePriority.HIGH,
        )

        # Accumulated context passed to each successive agent
        context: dict[str, AgentResult] = {}
        aborted = False

        for step in effective_workflow.steps:
            if aborted:
                rec = self._make_step_record(step, StepStatus.SKIPPED)
                record.steps.append(rec)
                self._emit_step_skipped(step, effective_run_id, reason="prior required step failed")
                continue

            # Dependency check
            if not self._dependencies_satisfied(step, context):
                rec = self._make_step_record(step, StepStatus.SKIPPED)
                record.steps.append(rec)
                self._emit_step_skipped(
                    step, effective_run_id,
                    reason=f"unsatisfied dependencies: {step.depends_on}",
                )
                logger.warning(
                    "orchestrator.step.deps_unmet",
                    step=step.agent_name,
                    depends_on=step.depends_on,
                )
                continue

            # Iteration guard
            if len(context) >= settings.max_iterations:
                logger.warning(
                    "orchestrator.max_iterations_reached",
                    limit=settings.max_iterations,
                )
                break

            step_record = self._execute_step(step, objective, context, effective_run_id)
            record.steps.append(step_record)

            if step_record.status == StepStatus.SUCCEEDED and step_record.result:
                context[step.agent_name] = step_record.result
                self._memory.store(f"output:{step.agent_name}", step_record.result.content)

            elif step_record.status == StepStatus.FAILED and step.required:
                logger.error(
                    "orchestrator.required_step_failed",
                    step=step.agent_name,
                    run_id=effective_run_id,
                )
                aborted = True

        # Finalise record
        record.finished_at = datetime.now(timezone.utc)
        record.status = self._compute_run_status(record, aborted)

        self._run_history.append(record)

        logger.info(
            "orchestrator.run.complete",
            run_id=effective_run_id,
            status=record.status.value,
            duration_s=round(record.duration_s, 2),
            succeeded=len(record.succeeded_steps),
            failed=len(record.failed_steps),
        )

        self._emit(
            self.TOPIC_RUN_COMPLETED,
            content=f"Run {effective_run_id[:8]} {record.status.value} in {record.duration_s:.1f}s",
            payload={
                "run_id": effective_run_id,
                "status": record.status.value,
                "duration_s": record.duration_s,
                "succeeded": len(record.succeeded_steps),
                "failed": len(record.failed_steps),
            },
            priority=MessagePriority.HIGH,
        )

        return record

    # ------------------------------------------------------------------
    # Multi-step workflow helpers
    # ------------------------------------------------------------------

    def run_step(
        self,
        agent_name: str,
        objective: str,
        context: dict[str, AgentResult] | None = None,
    ) -> AgentResult:
        """
        Invoke a single agent outside of a full workflow run.

        Useful for interactive use, testing individual agents, or building
        custom orchestration logic on top of the Orchestrator.

        Args:
            agent_name: Name of the registered agent to invoke.
            objective:  The prompt / objective for this invocation.
            context:    Optional prior-agent context.

        Returns:
            The agent's AgentResult.

        Raises:
            KeyError: If the agent is not registered.
        """
        agent = self.get_agent(agent_name)
        ctx = context or {}

        agent.on_start(objective, ctx)
        t0 = time.perf_counter()
        try:
            result = agent.run(objective=objective, context=ctx)
            result.duration_s = time.perf_counter() - t0
            agent.on_complete(result)
            return result
        except Exception as exc:
            agent.on_error(exc)
            return AgentResult(
                agent=agent_name,
                content="",
                success=False,
                error=str(exc),
                duration_s=time.perf_counter() - t0,
            )

    # ------------------------------------------------------------------
    # History & introspection
    # ------------------------------------------------------------------

    @property
    def run_history(self) -> list[RunRecord]:
        """All RunRecords produced by this Orchestrator instance."""
        return list(self._run_history)

    def stats(self) -> dict[str, Any]:
        """Return a snapshot of orchestrator-level metrics."""
        total = len(self._run_history)
        completed = sum(1 for r in self._run_history if r.status == RunStatus.COMPLETED)
        return {
            "registered_agents": len(self._agents),
            "total_runs": total,
            "completed_runs": completed,
            "partial_runs": sum(1 for r in self._run_history if r.status == RunStatus.PARTIAL),
            "failed_runs": sum(1 for r in self._run_history if r.status == RunStatus.FAILED),
            "bus_stats": self._bus.stats(),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _execute_step(
        self,
        step: WorkflowStep,
        objective: str,
        context: dict[str, AgentResult],
        run_id: str,
    ) -> StepRecord:
        """Run a single workflow step and return its StepRecord."""
        if step.agent_name not in self._agents:
            logger.warning("orchestrator.agent_missing", agent=step.agent_name)
            rec = self._make_step_record(step, StepStatus.SKIPPED)
            rec.error = f"Agent '{step.agent_name}' is not registered."
            self._emit_step_skipped(step, run_id, reason=rec.error)
            return rec

        agent = self._agents[step.agent_name]
        rec = self._make_step_record(step, StepStatus.RUNNING)
        rec.started_at = datetime.now(timezone.utc)

        logger.info(
            "orchestrator.step.start",
            step=step.agent_name,
            run_id=run_id,
            prior_agents=list(context),
        )

        self._emit(
            self.TOPIC_STEP_STARTED,
            content=f"Step '{step.agent_name}' started.",
            payload={"run_id": run_id, "agent": step.agent_name},
        )

        agent.on_start(objective, context)
        t0 = time.perf_counter()

        try:
            result = agent.run(objective=objective, context=context)
            result.duration_s = time.perf_counter() - t0
            agent.on_complete(result)

            rec.result = result
            rec.status = StepStatus.SUCCEEDED if result.success else StepStatus.FAILED
            rec.error = result.error
            rec.finished_at = datetime.now(timezone.utc)

            log_fn = logger.info if result.success else logger.warning
            log_fn(
                "orchestrator.step.complete",
                step=step.agent_name,
                success=result.success,
                duration_s=round(result.duration_s, 2),
                content_chars=len(result.content),
            )

            self._emit(
                self.TOPIC_STEP_COMPLETED,
                content=result.content[:500],
                payload={
                    "run_id": run_id,
                    "agent": step.agent_name,
                    "success": result.success,
                    "duration_s": result.duration_s,
                },
                priority=MessagePriority.NORMAL,
            )

        except Exception as exc:
            elapsed = time.perf_counter() - t0
            agent.on_error(exc)

            rec.status = StepStatus.FAILED
            rec.error = str(exc)
            rec.finished_at = datetime.now(timezone.utc)
            rec.result = AgentResult(
                agent=step.agent_name,
                content="",
                success=False,
                error=str(exc),
                duration_s=elapsed,
            )

            logger.exception(
                "orchestrator.step.exception",
                step=step.agent_name,
                run_id=run_id,
                error=str(exc),
            )

            self._emit(
                self.TOPIC_STEP_FAILED,
                content=f"Step '{step.agent_name}' raised: {exc}",
                payload={
                    "run_id": run_id,
                    "agent": step.agent_name,
                    "error": str(exc),
                },
                priority=MessagePriority.HIGH,
            )

        return rec

    def _dependencies_satisfied(
        self,
        step: WorkflowStep,
        context: dict[str, AgentResult],
    ) -> bool:
        """Return True if all declared dependencies for *step* have succeeded."""
        for dep in step.depends_on:
            result = context.get(dep)
            if result is None or not result.success:
                return False
        return True

    @staticmethod
    def _make_step_record(step: WorkflowStep, status: StepStatus) -> StepRecord:
        return StepRecord(step=step, status=status)

    @staticmethod
    def _compute_run_status(record: RunRecord, aborted: bool) -> RunStatus:
        if aborted:
            return RunStatus.FAILED
        if record.failed_steps:
            return RunStatus.PARTIAL
        return RunStatus.COMPLETED

    def _emit(
        self,
        topic: str,
        content: str,
        payload: dict[str, Any] | None = None,
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> None:
        """Publish an orchestrator-originated bus message."""
        self._bus.publish(
            Message(
                sender="orchestrator",
                topic=topic,
                content=content,
                payload=payload or {},
                priority=priority,
            )
        )

    def _emit_step_skipped(self, step: WorkflowStep, run_id: str, reason: str) -> None:
        self._emit(
            self.TOPIC_STEP_SKIPPED,
            content=f"Step '{step.agent_name}' skipped: {reason}",
            payload={"run_id": run_id, "agent": step.agent_name, "reason": reason},
        )

    def __repr__(self) -> str:
        return (
            f"<Orchestrator "
            f"agents={list(self._agents)} "
            f"runs={len(self._run_history)}>"
        )
