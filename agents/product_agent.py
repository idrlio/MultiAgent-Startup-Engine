"""
agents/product_agent.py
Defines product specifications, user stories, and MVP scope.
"""

from __future__ import annotations

from agents.base_agent import AgentResult, BaseAgent


class ProductAgent(BaseAgent):
    name = "product"
    role = "Product Manager — specs, roadmap, user stories"

    system_prompt = """You are a sharp product manager at a fast-moving startup.
Your job is to:
- Define the MVP feature set (ruthlessly scoped)
- Write clear user stories: As a [persona], I want [feature] so that [benefit]
- Outline a 3-phase product roadmap
- Define acceptance criteria for the top 3 features

Structure your output as:
1. MVP Scope (what is IN and what is deliberately OUT)
2. User Stories (top 5-8 stories)
3. Product Roadmap (Phase 1 / 2 / 3)
4. Acceptance Criteria for top 3 features
Keep it concrete and developer-ready (400-600 words)."""

    def run(self, objective: str, context: dict[str, AgentResult]) -> AgentResult:
        """
        Execute the product agent task.

        Args:
            objective: The top-level startup goal.
            context:   Results from prior agents in the pipeline.

        Returns:
            AgentResult containing the product output.
        """
        self._log.info("product.run.start")
        prompt = self._build_prompt(objective, context)
        content = self._call_claude(prompt)
        self._log.info("product.run.complete", content_chars=len(content))
        return AgentResult(agent=self.name, content=content)
