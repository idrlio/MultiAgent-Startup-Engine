"""
agents/research_agent.py
Gathers market research, competitor analysis, and trend data.
"""

from __future__ import annotations

from agents.base_agent import AgentResult, BaseAgent


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
4. Risks and Opportunities
Keep it factual, concise, and actionable (400-600 words)."""

    def run(self, objective: str, context: dict[str, AgentResult]) -> AgentResult:
        """
        Execute the research agent task.

        Args:
            objective: The top-level startup goal.
            context:   Results from prior agents in the pipeline.

        Returns:
            AgentResult containing the research output.
        """
        self._log.info("research.run.start")
        prompt = self._build_prompt(objective, context)
        content = self._call_claude(prompt)
        self._log.info("research.run.complete", content_chars=len(content))
        return AgentResult(agent=self.name, content=content)
