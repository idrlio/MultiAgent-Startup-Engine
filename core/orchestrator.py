"""
core/orchestrator.py
=====================
Central coordinator for AgentForge.

Architecture
------------
* Agents are registered into a typed registry and injected with a shared
  MemoryManager and MessageBus.
* Execution is driven by Workflow / WorkflowStep objects — first-class
  descriptors of the pipeline, its ordering, and step dependencies.
* After the primary pipeline completes, an optional feedback loop invokes
  the CriticAgent and, if the confidence score falls below a threshold,
  selectively re-runs flagged agents for up to ``max_feedback_iterations``
  rounds.
* Every run produces a RunRecord — a full, immutable audit trail capturing
  timing, status, result, and iteration number for every step.
* Bus events are emitted at every transition so external observers (UI,
  logging sinks, test harnesses) can react without polling.
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
from core.memory import MemoryManager
from core.messaging import Message, MessageBus, MessagePriority

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"     # some non-required agents failed
    FAILED = "failed"       # required agent failed or aborted


class StepStatus(str, Enum):
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
        agent_name:  Agent to invoke.
        required:    If True and this step fails, the run aborts immediately.
        depends_on:  Names of prior steps that must have SUCCEEDED before this
                     step is eligible to run.
    """

    agent_name: str
    required: bool = False
    depends_on: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        flags = (["required"] if self.required else []) + (
            [f"depends_on={self.depends_on}"] if self.depends_on else []
        )
        tag = f" [{', '.join(flags)}]" if flags else ""
        return f"<WorkflowStep {self.agent_name!r}{tag}>"


@dataclass
class Workflow:
    """
    Ordered sequence of WorkflowStep objects.

    Use Workflow.linear() for the common sequential case.
    Use Workflow.with_critic() to append a critic step automatically.
    """

    name: str
    steps: list[WorkflowStep]
    description: str = ""

    @classmethod
    def linear(cls, name: str, agent_names: list[str], *, required: bool = False) -> "Workflow":
        """Build a simple sequential workflow — each step follows the previous."""
        steps = [WorkflowStep(agent_name=n, required=required) for n in agent_names]
        return cls(name=name, steps=steps)

    @classmethod
    def with_critic(
        cls,
        name: str,
        agent_names: list[str],
        critic_name: str = "critic",
    ) -> "Workflow":
        """
        Build a workflow where the critic step runs last and is explicitly
        marked as the feedback evaluator.  The critic is not required — a
        failure does not abort the run.
        """
        steps = [WorkflowStep(agent_name=n) for n in agent_names]
        steps.append(WorkflowStep(agent_name=critic_name, required=False))
        return cls(name=name, steps=steps)

    def agent_names(self) -> list[str]:
        return [s.agent_name for s in self.steps]

    def __len__(self) -> int:
        return len(self.steps)

    def __repr__(self) -> str:
        return f"<Workflow name={self.name!r} steps={len(self.steps)}>"


# ---------------------------------------------------------------------------
# Execution records
# ---------------------------------------------------------------------------

@dataclass
class StepRecord:
    """Audit record for one step execution within a run."""

    step: WorkflowStep
    status: StepStatus = StepStatus.PENDING
    result: AgentResult | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str = ""
    feedback_iteration: int = 0     # 0 = initial run; ≥1 = feedback retry

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
        run_id:         Unique identifier for this run.
        objective:      The startup goal that was passed to run().
        workflow:       Workflow that was executed.
        status:         Final run status.
        steps:          StepRecord for each workflow step (may include retries).
        started_at:     UTC run start time.
        finished_at:    UTC run end time (None while running).
        feedback_rounds: Number of feedback-loop iterations performed.
        metadata:       Arbitrary caller-supplied annotations.
    """

    run_id: str
    objective: str
    workflow: Workflow
    status: RunStatus = RunStatus.PENDING
    steps: list[StepRecord] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    feedback_rounds: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        if self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0.0

    @property
    def results(self) -> dict[str, AgentResult]:
        """Most recent AgentResult per agent (includes retried outputs)."""
        out: dict[str, AgentResult] = {}
        for rec in self.steps:
            if rec.result is not None:
                out[rec.step.agent_name] = rec.result
        return out

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
            f"steps={len(self.succeeded_steps)}/{len(self.steps)} ok "
            f"feedback_rounds={self.feedback_rounds}>"
        )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    """
    Central coordinator for AgentForge.

    Responsibilities
    ----------------
    1. **Agent registry** — register / unregister agents; inject shared
       MemoryManager and MessageBus into each agent on registration.

    2. **Workflow execution** — run an ordered, dependency-aware pipeline.
       Each agent receives the *objective* plus accumulated context from all
       prior successful agents.

    3. **Feedback loop** — after the primary pipeline, the CriticAgent is
       invoked to score the collective output.  If the score falls below
       ``feedback_score_threshold`` and feedback loops are enabled, the
       agents flagged by the Critic are re-run (up to
       ``max_feedback_iterations`` rounds).

    4. **Event emission** — structured bus messages at every stage boundary
       so observers can react without coupling to internal state.

    5. **Audit trail** — every run returns a RunRecord with per-step timing,
       status, result, and iteration number.

    6. **Vector memory persistence** — after a run completes the vector
       index is flushed to disk automatically.

    Example::

        memory  = MemoryManager()
        bus     = MessageBus()
        orch    = Orchestrator(memory=memory, bus=bus)

        orch.register(ResearchAgent())
        orch.register(CEOAgent())
        orch.register(ProductAgent())
        orch.register(EngineerAgent())
        orch.register(MarketingAgent())
        orch.register(CriticAgent())

        workflow = Workflow.with_critic(
            "agentforge",
            ["research", "ceo", "product", "engineer", "marketing"],
        )
        record = orch.run("Build a B2B SaaS CRM for freelancers", workflow=workflow)
        print(record.status)
        print(record.results["ceo"].content)
    """

    # Bus topic constants
    TOPIC_RUN_STARTED    = "orchestrator.run.started"
    TOPIC_RUN_COMPLETED  = "orchestrator.run.completed"
    TOPIC_STEP_STARTED   = "orchestrator.step.started"
    TOPIC_STEP_COMPLETED = "orchestrator.step.completed"
    TOPIC_STEP_FAILED    = "orchestrator.step.failed"
    TOPIC_STEP_SKIPPED   = "orchestrator.step.skipped"
    TOPIC_FEEDBACK_START = "orchestrator.feedback.started"
    TOPIC_FEEDBACK_END   = "orchestrator.feedback.completed"

    def __init__(
        self,
        memory: MemoryManager | None = None,
        bus: MessageBus | None = None,
    ) -> None:
        self._memory = memory or MemoryManager()
        self._bus = bus or MessageBus()
        self._agents: dict[str, BaseAgent] = {}
        self._run_history: list[RunRecord] = []
        logger.info("orchestrator.initialized")

    # ------------------------------------------------------------------
    # Agent registry
    # ------------------------------------------------------------------

    def register(self, agent: BaseAgent) -> None:
        """
        Register *agent* and inject shared infrastructure.

        Args:
            agent: Instantiated BaseAgent subclass.

        Raises:
            ValueError: If an agent with the same name is already registered.
        """
        if agent.name in self._agents:
            raise ValueError(
                f"Agent '{agent.name}' is already registered. "
                "Call unregister() first or use a unique name."
            )
        agent.attach(memory=self._memory, bus=self._bus)
        self._agents[agent.name] = agent
        logger.info(
            "orchestrator.agent_registered",
            agent=agent.name,
            role=agent.role,
            total=len(self._agents),
        )

    def unregister(self, agent_name: str) -> bool:
        """
        Remove *agent_name* from the registry and detach its infrastructure.

        Returns:
            True if found and removed, False otherwise.
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

        Raises:
            KeyError: If *name* is not registered.
        """
        if name not in self._agents:
            raise KeyError(
                f"Agent '{name}' is not registered. "
                f"Available: {list(self._agents)}"
            )
        return self._agents[name]

    @property
    def agents(self) -> dict[str, BaseAgent]:
        return dict(self._agents)

    # ------------------------------------------------------------------
    # Primary execution
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
        Execute a workflow for *objective*, then run the feedback loop.

        Pipeline
        --------
        1. Execute all WorkflowSteps in order (respecting ``depends_on`` and
           ``required`` flags).
        2. If the critic agent ran and ``enable_feedback_loop`` is True:
           a. Parse the confidence score and agent-revision list.
           b. If score < threshold, re-run flagged agents with the critic's
              review injected as additional context.
           c. Repeat up to ``max_feedback_iterations`` rounds.
        3. Persist the vector memory index.
        4. Return the RunRecord.

        Args:
            objective: High-level startup goal.
            workflow:  Workflow to execute (defaults to linear over all agents).
            run_id:    Optional caller-supplied ID (UUID4 auto-generated if omitted).
            metadata:  Arbitrary annotations stored in the RunRecord.

        Returns:
            RunRecord containing the full execution trace.
        """
        from config import settings

        effective_workflow = workflow or Workflow.linear(
            "default", list(self._agents)
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
            steps=len(effective_workflow),
        )

        self._memory.store("run:id", effective_run_id)
        self._memory.store("run:objective", objective)

        self._emit(
            self.TOPIC_RUN_STARTED,
            f"Run {effective_run_id[:8]} started: {objective[:100]}",
            priority=MessagePriority.HIGH,
            payload={"run_id": effective_run_id, "objective": objective},
        )

        # ---- Primary pipeline ----------------------------------------
        context: dict[str, AgentResult] = {}
        aborted = False
        iteration_count = 0

        for step in effective_workflow.steps:
            if aborted:
                record.steps.append(self._skip_record(step, "prior required step failed"))
                self._emit_skipped(step, effective_run_id, "prior required step failed")
                continue

            if not self._deps_ok(step, context):
                record.steps.append(self._skip_record(step, f"unmet deps: {step.depends_on}"))
                self._emit_skipped(step, effective_run_id, f"unmet deps: {step.depends_on}")
                logger.warning("orchestrator.step.deps_unmet", step=step.agent_name)
                continue

            if iteration_count >= settings.max_iterations:
                logger.warning("orchestrator.max_iterations", limit=settings.max_iterations)
                break

            step_rec = self._run_step(step, objective, context, effective_run_id)
            record.steps.append(step_rec)
            iteration_count += 1

            if step_rec.status == StepStatus.SUCCEEDED and step_rec.result:
                context[step.agent_name] = step_rec.result
                self._memory.store(f"output:{step.agent_name}", step_rec.result.content)

            elif step_rec.status == StepStatus.FAILED and step.required:
                logger.error("orchestrator.required_step_failed", step=step.agent_name)
                aborted = True

        # ---- Feedback loop -------------------------------------------
        if (
            not aborted
            and settings.enable_feedback_loop
            and settings.enable_critic
            and "critic" in context
        ):
            record.feedback_rounds = self._run_feedback_loop(
                objective=objective,
                context=context,
                record=record,
                run_id=effective_run_id,
                workflow=effective_workflow,
            )

        # ---- Finalise ------------------------------------------------
        record.finished_at = datetime.now(timezone.utc)
        record.status = self._compute_status(record, aborted)
        self._run_history.append(record)

        # Persist vector memory
        try:
            self._memory.persist_vector()
        except Exception:
            logger.warning("orchestrator.vector_persist_failed")

        logger.info(
            "orchestrator.run.complete",
            run_id=effective_run_id,
            status=record.status.value,
            duration_s=round(record.duration_s, 2),
            succeeded=len(record.succeeded_steps),
            failed=len(record.failed_steps),
            feedback_rounds=record.feedback_rounds,
        )

        self._emit(
            self.TOPIC_RUN_COMPLETED,
            f"Run {effective_run_id[:8]} {record.status.value} "
            f"in {record.duration_s:.1f}s ({record.feedback_rounds} feedback rounds)",
            priority=MessagePriority.HIGH,
            payload={
                "run_id": effective_run_id,
                "status": record.status.value,
                "duration_s": record.duration_s,
                "feedback_rounds": record.feedback_rounds,
            },
        )
        return record

    # ------------------------------------------------------------------
    # Feedback loop
    # ------------------------------------------------------------------

    def _run_feedback_loop(
        self,
        *,
        objective: str,
        context: dict[str, AgentResult],
        record: RunRecord,
        run_id: str,
        workflow: Workflow,
    ) -> int:
        """
        Selectively re-run agents flagged by the Critic until the confidence
        score exceeds the threshold or max iterations are exhausted.

        Returns:
            Number of feedback rounds performed.
        """
        from config import settings

        critic_result = context.get("critic")
        if critic_result is None:
            return 0

        rounds = 0
        score: float = critic_result.metadata.get("confidence_score", 10.0)
        agents_to_revise: list[str] = critic_result.metadata.get("agents_to_revise", [])

        while (
            score < settings.feedback_score_threshold
            and agents_to_revise
            and rounds < settings.max_feedback_iterations
        ):
            rounds += 1
            logger.info(
                "orchestrator.feedback.round",
                round=rounds,
                score=score,
                threshold=settings.feedback_score_threshold,
                revising=agents_to_revise,
            )

            self._emit(
                self.TOPIC_FEEDBACK_START,
                f"Feedback round {rounds}: revising {agents_to_revise}",
                payload={
                    "run_id": run_id,
                    "round": rounds,
                    "score": score,
                    "agents": agents_to_revise,
                },
            )

            # Build a revised context that injects the critic review
            critic_note = (
                f"\n\n---\n**Critic Review (round {rounds}):**\n"
                f"{critic_result.content}\n"
                f"Please address the critique and improve your output.\n---\n"
            )
            revised_objective = f"{objective}{critic_note}"

            for agent_name in agents_to_revise:
                if agent_name not in self._agents:
                    logger.warning("orchestrator.feedback.unknown_agent", agent=agent_name)
                    continue

                # Find the matching workflow step (keep original required flag)
                original_step = next(
                    (s for s in workflow.steps if s.agent_name == agent_name),
                    WorkflowStep(agent_name=agent_name),
                )
                step_rec = self._run_step(
                    original_step,
                    revised_objective,
                    context,
                    run_id,
                    feedback_iteration=rounds,
                )
                record.steps.append(step_rec)

                if step_rec.status == StepStatus.SUCCEEDED and step_rec.result:
                    context[agent_name] = step_rec.result
                    self._memory.store(f"output:{agent_name}:r{rounds}", step_rec.result.content)

            # Re-run critic to get updated score
            if "critic" in self._agents:
                critic_step = WorkflowStep(agent_name="critic")
                critic_rec = self._run_step(
                    critic_step,
                    objective,
                    context,
                    run_id,
                    feedback_iteration=rounds,
                )
                record.steps.append(critic_rec)

                if critic_rec.result:
                    context["critic"] = critic_rec.result
                    critic_result = critic_rec.result
                    score = critic_result.metadata.get("confidence_score", 10.0)
                    agents_to_revise = critic_result.metadata.get("agents_to_revise", [])

            self._emit(
                self.TOPIC_FEEDBACK_END,
                f"Feedback round {rounds} complete. New score: {score:.1f}/10",
                payload={"run_id": run_id, "round": rounds, "new_score": score},
            )

        return rounds

    # ------------------------------------------------------------------
    # Single-step execution
    # ------------------------------------------------------------------

    def _run_step(
        self,
        step: WorkflowStep,
        objective: str,
        context: dict[str, AgentResult],
        run_id: str,
        feedback_iteration: int = 0,
    ) -> StepRecord:
        """Execute one workflow step and return a populated StepRecord."""
        if step.agent_name not in self._agents:
            logger.warning("orchestrator.step.missing_agent", agent=step.agent_name)
            rec = StepRecord(step=step, status=StepStatus.SKIPPED)
            rec.error = f"Agent '{step.agent_name}' not registered."
            self._emit_skipped(step, run_id, rec.error)
            return rec

        agent = self._agents[step.agent_name]
        rec = StepRecord(
            step=step,
            status=StepStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            feedback_iteration=feedback_iteration,
        )

        logger.info(
            "orchestrator.step.start",
            step=step.agent_name,
            run_id=run_id,
            feedback_iteration=feedback_iteration,
            prior_agents=list(context),
        )
        self._emit(
            self.TOPIC_STEP_STARTED,
            f"Step '{step.agent_name}' started (iteration {feedback_iteration}).",
            payload={"run_id": run_id, "agent": step.agent_name, "iteration": feedback_iteration},
        )

        agent.on_start(objective, context)
        t0 = time.perf_counter()

        try:
            result = agent.run(objective=objective, context=context)
            result.duration_s = time.perf_counter() - t0
            result.iteration = feedback_iteration
            agent.on_complete(result)

            rec.result = result
            rec.status = StepStatus.SUCCEEDED if result.success else StepStatus.FAILED
            rec.error = result.error
            rec.finished_at = datetime.now(timezone.utc)

            (logger.info if result.success else logger.warning)(
                "orchestrator.step.complete",
                step=step.agent_name,
                success=result.success,
                duration_s=round(result.duration_s, 2),
            )
            self._emit(
                self.TOPIC_STEP_COMPLETED,
                result.content[:400],
                payload={
                    "run_id": run_id,
                    "agent": step.agent_name,
                    "success": result.success,
                    "duration_s": result.duration_s,
                    "iteration": feedback_iteration,
                },
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
                iteration=feedback_iteration,
            )
            logger.exception(
                "orchestrator.step.exception",
                step=step.agent_name,
                run_id=run_id,
                error=str(exc),
            )
            self._emit(
                self.TOPIC_STEP_FAILED,
                f"Step '{step.agent_name}' raised: {exc}",
                priority=MessagePriority.HIGH,
                payload={"run_id": run_id, "agent": step.agent_name, "error": str(exc)},
            )

        return rec

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def run_step(
        self,
        agent_name: str,
        objective: str,
        context: dict[str, AgentResult] | None = None,
    ) -> AgentResult:
        """
        Invoke a single agent outside of a full workflow (useful for testing).

        Args:
            agent_name: Registered agent to invoke.
            objective:  Prompt / goal.
            context:    Optional prior-agent context.

        Returns:
            The agent's AgentResult.
        """
        step = WorkflowStep(agent_name=agent_name)
        rec = self._run_step(step, objective, context or {}, "adhoc")
        return rec.result or AgentResult(agent=agent_name, content="", success=False)

    @property
    def run_history(self) -> list[RunRecord]:
        return list(self._run_history)

    def stats(self) -> dict[str, Any]:
        total = len(self._run_history)
        return {
            "registered_agents": len(self._agents),
            "total_runs": total,
            "completed_runs": sum(1 for r in self._run_history if r.status == RunStatus.COMPLETED),
            "partial_runs": sum(1 for r in self._run_history if r.status == RunStatus.PARTIAL),
            "failed_runs": sum(1 for r in self._run_history if r.status == RunStatus.FAILED),
            "total_feedback_rounds": sum(r.feedback_rounds for r in self._run_history),
            "bus": self._bus.stats(),
            "memory": repr(self._memory),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _deps_ok(self, step: WorkflowStep, context: dict[str, AgentResult]) -> bool:
        return all(
            context.get(dep) is not None and context[dep].success
            for dep in step.depends_on
        )

    @staticmethod
    def _skip_record(step: WorkflowStep, reason: str) -> StepRecord:
        rec = StepRecord(step=step, status=StepStatus.SKIPPED)
        rec.error = reason
        return rec

    @staticmethod
    def _compute_status(record: RunRecord, aborted: bool) -> RunStatus:
        if aborted:
            return RunStatus.FAILED
        if record.failed_steps:
            return RunStatus.PARTIAL
        return RunStatus.COMPLETED

    def _emit(
        self,
        topic: str,
        content: str,
        priority: MessagePriority = MessagePriority.NORMAL,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._bus.publish(Message(
            sender="orchestrator",
            topic=topic,
            content=content,
            priority=priority,
            payload=payload or {},
        ))

    def _emit_skipped(self, step: WorkflowStep, run_id: str, reason: str) -> None:
        self._emit(
            self.TOPIC_STEP_SKIPPED,
            f"Step '{step.agent_name}' skipped: {reason}",
            payload={"run_id": run_id, "agent": step.agent_name, "reason": reason},
        )

    def __repr__(self) -> str:
        return (
            f"<Orchestrator agents={list(self._agents)} "
            f"runs={len(self._run_history)}>"
        )
