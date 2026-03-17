# 🚀 AI Startup Engine

> A production-grade multi-agent AI system that simulates a fully autonomous startup — from ideation to execution.

![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Status](https://img.shields.io/badge/status-active-brightgreen.svg)

---

## Overview

**AI Startup Engine** orchestrates a team of specialized AI agents that collaborate to research markets, define products, write code, craft marketing strategies, and critique decisions — all autonomously.

Each agent has a distinct role and communicates through a shared messaging bus and memory layer, mimicking a real startup team.

---

## Architecture

```
ai-startup-engine/
├── main.py                  # Entry point
├── agents/
│   ├── base_agent.py        # Abstract base class for all agents
│   ├── ceo_agent.py         # Strategy, vision, decision-making
│   ├── product_agent.py     # Product specs, roadmap, user stories
│   ├── engineer_agent.py    # Code generation and architecture
│   ├── marketing_agent.py   # Campaigns, copy, go-to-market
│   ├── critic_agent.py      # Quality control and red-teaming
│   └── research_agent.py    # Market research and data gathering
├── core/
│   ├── orchestrator.py      # Coordinates agent lifecycle and tasks
│   ├── memory.py            # Shared persistent memory layer
│   └── messaging.py         # Inter-agent messaging bus
├── tools/
│   ├── web_search.py        # Web search integration
│   ├── code_executor.py     # Safe sandboxed code execution
│   └── file_manager.py      # File I/O and artifact management
└── config/
    └── settings.py          # Central configuration
```

---

## Agent Roles

| Agent | Role |
|---|---|
| **CEO** | Sets strategy, prioritizes tasks, makes final calls |
| **Product** | Defines features, user stories, and acceptance criteria |
| **Engineer** | Implements code, designs architecture, reviews PRs |
| **Marketing** | Crafts messaging, campaigns, and positioning |
| **Critic** | Challenges assumptions, finds flaws, ensures quality |
| **Research** | Gathers market data, competitor analysis, trends |

---

## Quickstart

### 1. Clone the repository

```bash
git clone https://github.com/your-org/ai-startup-engine.git
cd ai-startup-engine
```

### 2. Set up environment

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
# Edit .env and add your API keys
```

### 4. Run the engine

```bash
python main.py
```

---

## Configuration

All settings are managed via environment variables. See [`.env.example`](.env.example) for the full reference.

Key variables:

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `TAVILY_API_KEY` | Web search API key (Tavily) |
| `MODEL_NAME` | Claude model to use (default: `claude-opus-4-5`) |
| `MAX_ITERATIONS` | Max agent loop iterations (default: `10`) |
| `LOG_LEVEL` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`) |

---

## Requirements

- Python 3.11+
- Anthropic API key
- Tavily API key (for web search)

---

## License

MIT © 2025 AI Startup Engine Contributors
