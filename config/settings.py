"""
config/settings.py
==================
Central configuration for AgentForge.
All values are loaded from environment variables / .env file.
Import the `settings` singleton everywhere — never instantiate Settings directly.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------
    # Anthropic / LLM
    # ------------------------------------------------------------------
    anthropic_api_key: str = Field(..., description="Anthropic API key")
    model_name: str = Field("claude-opus-4-5", description="Primary Claude model")
    max_tokens: int = Field(4096, ge=256, description="Max tokens per completion")
    temperature: float = Field(0.7, ge=0.0, le=1.0)

    # ------------------------------------------------------------------
    # Web search
    # ------------------------------------------------------------------
    tavily_api_key: str = Field("", description="Tavily API key (leave blank to use mock)")

    # ------------------------------------------------------------------
    # Orchestration & feedback loops
    # ------------------------------------------------------------------
    max_iterations: int = Field(10, ge=1, le=50, description="Hard cap on pipeline steps")
    agent_timeout_seconds: int = Field(120, ge=10)
    enable_critic: bool = Field(True, description="Run the critic agent at end of pipeline")
    # Feedback loop: critic can trigger re-runs of agents that scored below threshold
    enable_feedback_loop: bool = Field(True, description="Allow critic to trigger agent retries")
    feedback_score_threshold: float = Field(
        6.0, ge=0.0, le=10.0,
        description="Confidence score below which critic triggers a retry"
    )
    max_feedback_iterations: int = Field(2, ge=0, le=5, description="Max retry rounds per agent")

    # ------------------------------------------------------------------
    # Short-term memory (diskcache / in_memory)
    # ------------------------------------------------------------------
    memory_backend: str = Field("in_memory", pattern="^(diskcache|in_memory)$")
    memory_dir: str = Field(".cache/memory")

    # ------------------------------------------------------------------
    # Long-term vector memory (FAISS + sentence-transformers)
    # ------------------------------------------------------------------
    enable_vector_memory: bool = Field(True, description="Enable FAISS RAG layer")
    vector_memory_dir: str = Field(".cache/vector_memory", description="FAISS index persistence dir")
    embedding_model: str = Field(
        "all-MiniLM-L6-v2",
        description="sentence-transformers model name"
    )
    rag_top_k: int = Field(5, ge=1, le=20, description="Number of chunks retrieved per RAG query")
    rag_chunk_size: int = Field(512, ge=64, description="Character chunk size for indexing")
    rag_chunk_overlap: int = Field(64, ge=0, description="Overlap between consecutive chunks")

    # ------------------------------------------------------------------
    # Artifacts & output
    # ------------------------------------------------------------------
    artifacts_dir: str = Field(".artifacts")

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    log_level: str = Field("INFO", pattern="^(DEBUG|INFO|WARNING|ERROR)$")
    log_format: str = Field("console", pattern="^(json|console)$")


# Singleton — import this everywhere
settings = Settings()  # type: ignore[call-arg]
