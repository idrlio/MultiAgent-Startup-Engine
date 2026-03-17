"""
agents/critic_agent.py
Red-teams all prior agent outputs and identifies weaknesses and risks.
"""

from __future__ import annotations

from agents.base_agent import AgentResult, BaseAgent


class CriticAgent(BaseAgent):
    name = "critic"
    role = "Critic — quality control, red-teaming, risk identification"

    system_prompt = """You are a brutally honest startup advisor and red-teamer.
Your job is to review all prior agent outputs and:
- Challenge assumptions that are weak or unsupported
- Identify the top 5 risks that could kill this startup
- Spot gaps in the strategy, product, or go-to-market plan
- Suggest concrete improvements for each weakness found
- Provide an overall confidence score (1-10) with justification

Structure your output as:
1. Critical Assumptions Being Made (validated or not)
2. Top 5 Startup Risks (ranked by severity)
3. Strategy Gaps
4. Recommended Improvements
5. Overall Confidence Score and Verdict
Be honest, rigorous, and constructive (400-500 words)."""

    def run(self, objective: str, context: dict[str, AgentResult]) -> AgentResult:
        """
        Execute the critic agent task.

        Args:
            objective: The top-level startup goal.
            context:   Results from prior agents in the pipeline.

        Returns:
            AgentResult containing the critic output.
        """
        self._log.info("critic.run.start")
        prompt = self._build_prompt(objective, context)
        content = self._call_claude(prompt)
        self._log.info("critic.run.complete", content_chars=len(content))
        return AgentResult(agent=self.name, content=content)
