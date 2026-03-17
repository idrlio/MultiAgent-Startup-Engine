"""
agents/research_agent.py
Gathers market research, competitor analysis, and trend data.
"""

from __future__ import annotations

from agents.base_agent import BaseAgent


class ResearchAgent(BaseAgent):
    name = "research"
    role = "Market Researcher — trends, competitors, data"

    system_prompt = """You are a senior market research analyst at a startup.
Your job is to:
- Identify the target market size and growth trajectory
- Analyse 3-5 key competitors with their strengths and weaknesses
- Surface the top trends driving the space
- Highlight key risks and underserved customer pain points

Structure your output as:
1. Market Overview (TAM/SAM/SOM estimates if possible)
2. Competitor Landscape (table format)
3. Key Trends (bullet points)
4. Risks & Opportunities
Keep it factual, concise, and actionable (400-600 words).
"""

    def run(self, objective: str, context: dict[str, str]) -> str:
        ctx = self._build_context_block(context)
        prompt = f"""Startup Objective: {objective}

{ctx}

Conduct market research for this startup now."""

        self._log.info("research.running")
        result = self._call_claude(prompt)
        self._log.info("research.done")
        return result
