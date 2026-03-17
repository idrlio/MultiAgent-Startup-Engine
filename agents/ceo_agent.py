"""
agents/ceo_agent.py
Sets the overall strategy, vision, and guiding principles for the startup.
"""

from __future__ import annotations

from agents.base_agent import BaseAgent


class CEOAgent(BaseAgent):
    name = "ceo"
    role = "Chief Executive Officer — strategy, vision, priorities"

    system_prompt = """You are the CEO of an ambitious AI startup.
Your job is to:
- Define a clear, compelling product vision based on the objective
- Set strategic priorities and success metrics
- Identify the primary target customer and core value proposition
- Make decisive, opinionated choices — avoid wishy-washy answers

Output a concise strategy memo (300-500 words) with the following sections:
1. Vision Statement
2. Target Customer
3. Core Value Proposition
4. Top 3 Strategic Priorities
5. Key Success Metrics
"""

    def run(self, objective: str, context: dict[str, str]) -> str:
        ctx = self._build_context_block(context)
        prompt = f"""Startup Objective: {objective}

{ctx}

Write the strategy memo now."""

        self._log.info("ceo.running")
        result = self._call_claude(prompt)
        self._log.info("ceo.done")
        return result
