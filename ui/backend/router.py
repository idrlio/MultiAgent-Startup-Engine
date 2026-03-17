"""
ui/backend/router.py
All FastAPI route handlers.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from typing import AsyncIterator

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ui.backend.schemas import (
    AgentOutputSchema, AgentStatus, MemoryStatsSchema, RunDetailSchema,
    RunRequest, RunSummarySchema, SSEEvent, SSEEventType, SettingsSchema,
    StepRecordSchema,
)

logger = structlog.get_logger(__name__)
router = APIRouter()

# In-memory run store — keyed by run_id
_runs: dict[str, RunDetailSchema] = {}


# ---------------------------------------------------------------------------
# SSE stream
# ---------------------------------------------------------------------------

async def _event_stream(run_id: str, request: RunRequest) -> AsyncIterator[str]:
    """
    Execute the AgentForge pipeline and yield SSE-formatted events.
    Runs the blocking orchestrator in a thread pool so the event loop stays free.
    """
    import anthropic
    from config import settings as cfg

    # Apply request overrides to settings
    cfg.enable_critic            = request.enable_critic
    cfg.enable_feedback_loop     = request.enable_feedback_loop
    cfg.enable_vector_memory     = request.enable_vector_memory
    cfg.max_feedback_iterations  = request.max_feedback_iterations
    cfg.feedback_score_threshold = request.feedback_score_threshold

    def _emit(event_type: SSEEventType, data: dict) -> str:
        evt = SSEEvent(event=event_type, run_id=run_id, data=data)
        return f"event: {evt.event.value}\ndata: {evt.model_dump_json()}\n\n"

    yield _emit(SSEEventType.RUN_STARTED, {
        "objective": request.objective,
        "agents": ["research", "ceo", "product", "engineer", "marketing"]
                  + (["critic"] if request.enable_critic else []),
    })

    # Build the record skeleton
    run_record = RunDetailSchema(
        run_id=run_id,
        objective=request.objective,
        status="running",
        duration_s=0.0,
        feedback_rounds=0,
        succeeded_steps=0,
        failed_steps=0,
        total_steps=0,
        vector_chunks=0,
        created_at=datetime.utcnow(),
    )
    _runs[run_id] = run_record

    # Subscribe to bus events so we can forward them as SSE
    from core.memory import MemoryManager
    from core.messaging import MessageBus
    from core.orchestrator import Orchestrator, Workflow
    from agents import (
        ResearchAgent, CEOAgent, ProductAgent,
        EngineerAgent, MarketingAgent, CriticAgent,
    )

    event_queue: asyncio.Queue[str | None] = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def _on_step_started(msg):
        agent = msg.payload.get("agent", "")
        event_queue.put_nowait(_emit(SSEEventType.STEP_STARTED, {
            "agent": agent,
            "iteration": msg.payload.get("iteration", 0),
        }))

    def _on_step_completed(msg):
        agent = msg.payload.get("agent", "")
        event_queue.put_nowait(_emit(SSEEventType.STEP_COMPLETED, {
            "agent": agent,
            "success": msg.payload.get("success", True),
            "duration_s": msg.payload.get("duration_s", 0),
            "content_preview": msg.content[:300],
        }))

    def _on_step_failed(msg):
        event_queue.put_nowait(_emit(SSEEventType.STEP_FAILED, {
            "agent": msg.payload.get("agent", ""),
            "error": msg.payload.get("error", ""),
        }))

    def _on_feedback_started(msg):
        event_queue.put_nowait(_emit(SSEEventType.FEEDBACK_STARTED, {
            "round": msg.payload.get("round", 0),
            "score": msg.payload.get("score", 0),
            "agents": msg.payload.get("agents", []),
        }))

    def _on_feedback_ended(msg):
        event_queue.put_nowait(_emit(SSEEventType.FEEDBACK_ENDED, {
            "round": msg.payload.get("round", 0),
            "new_score": msg.payload.get("new_score", 0),
        }))

    memory = MemoryManager()
    bus    = MessageBus()

    bus.subscribe("orchestrator.step.started",    _on_step_started,    subscriber_name="ui")
    bus.subscribe("orchestrator.step.completed",  _on_step_completed,  subscriber_name="ui")
    bus.subscribe("orchestrator.step.failed",     _on_step_failed,     subscriber_name="ui")
    bus.subscribe("orchestrator.feedback.started",_on_feedback_started,subscriber_name="ui")
    bus.subscribe("orchestrator.feedback.completed",_on_feedback_ended,subscriber_name="ui")

    orchestrator = Orchestrator(memory=memory, bus=bus)
    for AgentClass in [ResearchAgent, CEOAgent, ProductAgent, EngineerAgent, MarketingAgent]:
        orchestrator.register(AgentClass())
    if request.enable_critic:
        orchestrator.register(CriticAgent())

    pipeline = ["research", "ceo", "product", "engineer", "marketing"]
    workflow = (
        Workflow.with_critic("agentforge", pipeline)
        if request.enable_critic
        else Workflow.linear("agentforge", pipeline)
    )

    # Run pipeline in thread pool
    import concurrent.futures
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    orchestrator_record = None
    exc_holder: list[Exception] = []

    def _run_sync():
        try:
            return orchestrator.run(request.objective, workflow=workflow)
        except Exception as e:
            exc_holder.append(e)
            return None

    future = loop.run_in_executor(executor, _run_sync)

    # Drain event queue while pipeline runs
    while not future.done():
        try:
            event = event_queue.get_nowait()
            yield event
        except asyncio.QueueEmpty:
            await asyncio.sleep(0.1)

    # Drain remaining queued events
    while not event_queue.empty():
        yield event_queue.get_nowait()

    if exc_holder:
        yield _emit(SSEEventType.ERROR, {"message": str(exc_holder[0])})
        return

    orchestrator_record = await future

    # Build final run detail
    results = {}
    for name, result in orchestrator_record.results.items():
        results[name] = AgentOutputSchema(
            agent=name,
            content=result.content,
            success=result.success,
            duration_s=result.duration_s,
            iteration=result.iteration,
            metadata=result.metadata,
        )

    steps = []
    for rec in orchestrator_record.steps:
        steps.append(StepRecordSchema(
            agent=rec.step.agent_name,
            status=AgentStatus(rec.status.value),
            duration_s=rec.duration_s,
            error=rec.error,
            feedback_iteration=rec.feedback_iteration,
        ))

    critic_result = orchestrator_record.results.get("critic")
    critic_score  = critic_result.metadata.get("confidence_score") if critic_result else None
    agents_revised = critic_result.metadata.get("agents_to_revise", []) if critic_result else []

    vec_chunks = memory.vector.size if memory.vector else 0

    run_record.status          = orchestrator_record.status.value
    run_record.duration_s      = orchestrator_record.duration_s
    run_record.feedback_rounds = orchestrator_record.feedback_rounds
    run_record.succeeded_steps = len(orchestrator_record.succeeded_steps)
    run_record.failed_steps    = len(orchestrator_record.failed_steps)
    run_record.total_steps     = len(orchestrator_record.steps)
    run_record.vector_chunks   = vec_chunks
    run_record.steps           = steps
    run_record.results         = results
    run_record.critic_score    = critic_score
    run_record.agents_revised  = agents_revised
    _runs[run_id] = run_record

    yield _emit(SSEEventType.RUN_COMPLETED, {
        "status":          orchestrator_record.status.value,
        "duration_s":      orchestrator_record.duration_s,
        "feedback_rounds": orchestrator_record.feedback_rounds,
        "critic_score":    critic_score,
        "agents_revised":  agents_revised,
        "vector_chunks":   vec_chunks,
        "succeeded":       len(orchestrator_record.succeeded_steps),
        "failed":          len(orchestrator_record.failed_steps),
    })


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/runs/stream")
async def stream_run(request: RunRequest):
    """Start a new AgentForge run and stream events via SSE."""
    run_id = str(uuid.uuid4())
    logger.info("api.run.stream", run_id=run_id, objective=request.objective[:60])
    return StreamingResponse(
        _event_stream(run_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/runs", response_model=list[RunSummarySchema])
async def list_runs():
    """Return all completed runs, newest first."""
    return sorted(
        [RunSummarySchema(**r.model_dump()) for r in _runs.values()],
        key=lambda r: r.created_at,
        reverse=True,
    )


@router.get("/runs/{run_id}", response_model=RunDetailSchema)
async def get_run(run_id: str):
    """Return full detail for a single run."""
    if run_id not in _runs:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found.")
    return _runs[run_id]


@router.delete("/runs/{run_id}", status_code=204)
async def delete_run(run_id: str):
    """Remove a run from history."""
    if run_id not in _runs:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found.")
    del _runs[run_id]


@router.get("/settings", response_model=SettingsSchema)
async def get_settings():
    """Return current AgentForge configuration."""
    from config import settings as cfg
    return SettingsSchema(
        model_name=cfg.model_name,
        embedding_model=cfg.embedding_model,
        max_tokens=cfg.max_tokens,
        temperature=cfg.temperature,
        tavily_configured=bool(cfg.tavily_api_key),
        enable_vector_memory=cfg.enable_vector_memory,
        enable_feedback_loop=cfg.enable_feedback_loop,
        feedback_score_threshold=cfg.feedback_score_threshold,
        max_feedback_iterations=cfg.max_feedback_iterations,
        memory_backend=cfg.memory_backend,
        rag_top_k=cfg.rag_top_k,
    )


@router.get("/memory/stats", response_model=MemoryStatsSchema)
async def memory_stats():
    """Return live memory layer statistics."""
    from core.memory import MemoryManager
    mgr = MemoryManager()
    return MemoryStatsSchema(
        kv_keys=len(mgr.kv.keys()),
        vector_chunks=mgr.vector.size if mgr.vector else 0,
        vector_available=mgr.vector.available if mgr.vector else False,
        embed_cache_size=mgr.vector._embedder.cache_size if mgr.vector and mgr.vector.available else 0,
    )
