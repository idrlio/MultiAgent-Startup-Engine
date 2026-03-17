"""
agents/ceo_agent.py
Sets overall strategy, vision, and guiding principles.
"""

from __future__ import annotations

from agents.base_agent import AgentResult, BaseAgent


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
5. Key Success Metrics"""

    def run(self, objective: str, context: dict[str, AgentResult]) -> AgentResult:
        """
        Execute the ceo agent task.

        Args:
            objective: The top-level startup goal.
            context:   Results from prior agents in the pipeline.

        Returns:
            AgentResult containing the ceo output.
        """
        self._log.info("ceo.run.start")
        prompt = self._build_prompt(objective, context)
        content = self._call_claude(prompt)
        self._log.info("ceo.run.complete", content_chars=len(content))
        return AgentResult(agent=self.name, content=content)
