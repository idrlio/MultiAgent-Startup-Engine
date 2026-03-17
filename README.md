# 🚀 AgentForge

> **Autonomous multi-agent AI system** that generates, evaluates, and executes startup ideas using advanced LLM orchestration, retrieval-augmented memory, and tool-augmented reasoning.

![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Status](https://img.shields.io/badge/status-active-brightgreen.svg)
![Claude](https://img.shields.io/badge/powered%20by-Claude%20claude--opus--4--5-orange.svg)

---

## What is AgentForge?

AgentForge simulates the full lifecycle of a startup — from market research to execution plan — using a team of specialised AI agents that collaborate through structured messaging, share a two-tier memory system, and iteratively improve their outputs via a critic-driven feedback loop.

It combines five advanced AI techniques in a single cohesive system:

| Technique | Implementation |
|---|---|
| **Multi-agent orchestration** | 6 specialised agents coordinated by a typed Workflow engine |
| **Retrieval-augmented generation (RAG)** | FAISS vector index + sentence-transformers; auto-injected into every agent prompt |
| **Feedback loops** | Critic agent scores outputs; low-scoring agents are automatically retried |
| **Tool augmentation** | Web search (Tavily / mock), sandboxed code execution, artifact management |
| **Structured audit trail** | RunRecord + StepRecord with per-step timing, status, errors, and iteration counts |

---

## Architecture

```
agentforge/
├── main.py                    # CLI entry point
│
├── agents/
│   ├── base_agent.py          # Abstract base: RAG-aware prompt building, retry, lifecycle hooks
│   ├── research_agent.py      # Web search → structured market report → indexes in vector memory
│   ├── ceo_agent.py           # Vision, strategy, target customer, priorities
│   ├── product_agent.py       # MVP scope, user stories, roadmap, acceptance criteria
│   ├── engineer_agent.py      # Tech stack, architecture, data models, project structure
│   ├── marketing_agent.py     # Positioning, GTM, acquisition channels, launch plan
│   └── critic_agent.py        # Red-teams all outputs; scores confidence; signals retries
│
├── core/
│   ├── memory.py              # SharedMemory (KV) + VectorMemory (FAISS RAG) + MemoryManager
│   ├── messaging.py           # Typed MessageBus with glob subscriptions, delivery receipts
│   └── orchestrator.py        # Workflow execution + dependency resolution + feedback loop
│
├── tools/
│   ├── web_search.py          # Tavily API with automatic mock fallback
│   ├── code_executor.py       # Sandboxed subprocess Python runner
│   └── file_manager.py        # Per-run artifact directory + consolidated report export
│
└── config/
    └── settings.py            # Pydantic-settings; all config from .env
```

---

## Agent Pipeline

```
Research ──→ CEO ──→ Product ──→ Engineer ──→ Marketing ──→ Critic
   │           │         │           │             │            │
   │     [Each agent receives RAG context from vector memory]  │
   │                                                            │
   └──── If Critic score < threshold: re-run flagged agents ───┘
                      (up to N feedback rounds)
```

### Agent Roles

| Agent | Role | Key Output |
|---|---|---|
| **Research** | Market intelligence via web search | Market size, competitors, trends, pain points |
| **CEO** | Vision and strategy | Strategy memo: vision, ICP, priorities, KPIs |
| **Product** | Product definition | MVP scope, user stories, roadmap, acceptance criteria |
| **Engineer** | Technical architecture | Tech stack, system design, data models, folder structure |
| **Marketing** | Go-to-market | Brand positioning, landing page copy, GTM, launch plan |
| **Critic** | Quality control + feedback | Critique, risk register, confidence score (0–10) |

---

## Memory System

### Tier 1 — Short-term (KV)
Fast in-process or disk-backed key-value store. Used for:
- Run metadata (`run:id`, `run:objective`)
- Agent outputs (`output:ceo`, `output:research`)
- Arbitrary agent state via `remember()` / `recall()`

### Tier 2 — Long-term vector memory (RAG)
FAISS flat inner-product index with `all-MiniLM-L6-v2` embeddings.

- Every agent response is **automatically chunked, embedded, and indexed** after generation.
- Before every Claude call, the most semantically relevant chunks are **retrieved and prepended** to the prompt.
- The index is **persisted to disk** after each run and can be **loaded across sessions** (`--load-memory`).

This means Agent 5 can recall a specific detail from Agent 1's output even if it wasn't in the explicit context dict.

---

## Feedback Loop

```
After primary pipeline:
  score = critic.metadata["confidence_score"]   # 0.0 – 10.0
  if score < FEEDBACK_SCORE_THRESHOLD (default 6.0):
      for agent in critic.metadata["agents_to_revise"]:
          re-run agent with critic review injected into prompt
      re-run critic → new score
  repeat up to MAX_FEEDBACK_ITERATIONS times
```

---

## Quickstart

### 1. Clone & install

```bash
git clone https://github.com/idrlio/MultiAgent-Startup-Engine.git
cd MultiAgent-Startup-Engine
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Add ANTHROPIC_API_KEY (required)
# Add TAVILY_API_KEY (optional — mock search used if blank)
```

### 3. Run

```bash
# Interactive — will prompt for objective
python main.py

# With objective
python main.py --objective "Build an AI-native CRM for freelancers"

# Disable feedback loop for faster runs
python main.py --objective "..." --no-feedback

# Disable RAG (useful for debugging)
python main.py --objective "..." --no-vector-memory

# Load previous run's vector memory
python main.py --objective "..." --load-memory
```

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Required.** Anthropic API key |
| `TAVILY_API_KEY` | `""` | Web search key. Mock used if blank |
| `MODEL_NAME` | `claude-opus-4-5` | Claude model |
| `ENABLE_CRITIC` | `true` | Run critic agent |
| `ENABLE_FEEDBACK_LOOP` | `true` | Enable critic-driven retries |
| `FEEDBACK_SCORE_THRESHOLD` | `6.0` | Score below which retries trigger |
| `MAX_FEEDBACK_ITERATIONS` | `2` | Max retry rounds per run |
| `ENABLE_VECTOR_MEMORY` | `true` | FAISS RAG layer |
| `EMBEDDING_MODEL` | `claude-haiku-4-5-20251001` | Claude model for RAG embeddings |
| `RAG_TOP_K` | `5` | Chunks retrieved per query |
| `MEMORY_BACKEND` | `in_memory` | `in_memory` or `diskcache` |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

---

## Output

Each run creates a timestamped directory under `.artifacts/`:

```
.artifacts/20250617_143022/
├── research/research.md
├── ceo/ceo.md
├── product/product.md
├── engineer/engineer.md
├── marketing/marketing.md
├── critic/critic.md
├── report.md           ← Consolidated Markdown report
└── run_record.json     ← Full structured audit trail
```

---

## Requirements

- Python 3.11+
- Anthropic API key
- Tavily API key *(optional)*
- No model weights downloaded — embeddings are generated by Claude Haiku

---

## License

MIT © 2025 AgentForge Contributors

---

## UI — Web Interface

AgentForge ships with a full web UI: a **React** frontend + **FastAPI** backend with real-time streaming via Server-Sent Events.

### Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite, react-markdown |
| Backend  | FastAPI, Uvicorn |
| Streaming | Server-Sent Events (SSE) — real-time pipeline updates |
| Fonts | DM Sans + DM Mono |

### Starting the UI

```bash
# One command — starts both backend and frontend
./start.sh          # macOS / Linux
start.bat           # Windows
```

Then open **http://localhost:5173** in your browser.

### Manual start (if preferred)

```bash
# Terminal 1 — backend
PYTHONPATH=. uvicorn ui.backend.main:app --reload --port 8000

# Terminal 2 — frontend
cd ui/frontend
npm install
npm run dev
```

### UI Pages

| Page | What it shows |
|---|---|
| **Workspace** | Objective input · live pipeline progress · agent output tabs · critic panel |
| **History** | All past runs with status, duration, steps, feedback rounds |
| **Memory** | KV keys · FAISS chunk count · embedding cache · RAG explanation |
| **Settings** | Read-only view of current .env configuration |

### API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/runs/stream` | Start a run — returns SSE stream |
| `GET`  | `/api/runs` | List all runs |
| `GET`  | `/api/runs/{id}` | Get full run detail |
| `DELETE` | `/api/runs/{id}` | Delete a run from history |
| `GET`  | `/api/settings` | Current configuration |
| `GET`  | `/api/memory/stats` | Live memory statistics |
| `GET`  | `/health` | Health check |
