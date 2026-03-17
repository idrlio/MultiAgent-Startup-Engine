"""
ui/backend/schemas.py
Pydantic models for all API request/response shapes.
"""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    objective: str = Field(..., min_length=10, description="Startup objective")
    enable_critic: bool = True
    enable_feedback_loop: bool = True
    enable_vector_memory: bool = True
    max_feedback_iterations: int = Field(2, ge=0, le=5)
    feedback_score_threshold: float = Field(6.0, ge=0, le=10)


class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class SSEEventType(str, Enum):
    RUN_STARTED      = "run_started"
    STEP_STARTED     = "step_started"
    STEP_COMPLETED   = "step_completed"
    STEP_FAILED      = "step_failed"
    FEEDBACK_STARTED = "feedback_started"
    FEEDBACK_ENDED   = "feedback_ended"
    RUN_COMPLETED    = "run_completed"
    ERROR            = "error"


class SSEEvent(BaseModel):
    event: SSEEventType
    run_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    data: dict[str, Any] = Field(default_factory=dict)


class AgentOutputSchema(BaseModel):
    agent: str
    content: str
    success: bool
    duration_s: float
    iteration: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class StepRecordSchema(BaseModel):
    agent: str
    status: AgentStatus
    duration_s: float
    error: str = ""
    feedback_iteration: int = 0


class RunSummarySchema(BaseModel):
    run_id: str
    objective: str
    status: str
    duration_s: float
    feedback_rounds: int
    succeeded_steps: int
    failed_steps: int
    total_steps: int
    vector_chunks: int
    created_at: datetime


class RunDetailSchema(RunSummarySchema):
    steps: list[StepRecordSchema] = Field(default_factory=list)
    results: dict[str, AgentOutputSchema] = Field(default_factory=dict)
    critic_score: float | None = None
    agents_revised: list[str] = Field(default_factory=list)


class MemoryStatsSchema(BaseModel):
    kv_keys: int
    vector_chunks: int
    vector_available: bool
    embed_cache_size: int


class SettingsSchema(BaseModel):
    model_name: str
    embedding_model: str
    max_tokens: int
    temperature: float
    tavily_configured: bool
    enable_vector_memory: bool
    enable_feedback_loop: bool
    feedback_score_threshold: float
    max_feedback_iterations: int
    memory_backend: str
    rag_top_k: int
