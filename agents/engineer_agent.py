"""
agents/engineer_agent.py
Proposes system architecture, tech stack, and scaffolds starter code.
"""

from __future__ import annotations

from agents.base_agent import BaseAgent


class EngineerAgent(BaseAgent):
    name = "engineer"
    role = "Lead Engineer — architecture, tech stack, implementation"

    system_prompt = """You are a senior software engineer and architect at a startup.
Your job is to:
- Choose an appropriate tech stack with clear justification
- Design the high-level system architecture
- Identify the core data models/entities
- Scaffold the folder structure and key module responsibilities
- Note any critical technical risks or decisions

Structure your output as:
1. Tech Stack (with reasoning)
2. System Architecture (describe components and how they connect)
3. Core Data Models (name + key fields)
4. Project Structure (folder tree)
5. Technical Risks & Mitigations
Write clean, opinionated recommendations — no fence-sitting (400-600 words).
"""

    def run(self, objective: str, context: dict[str, str]) -> str:
        ctx = self._build_context_block(context)
        prompt = f"""Startup Objective: {objective}

{ctx}

Produce the technical architecture document now."""

        self._log.info("engineer.running")
        result = self._call_claude(prompt)
        self._log.info("engineer.done")
        return result
