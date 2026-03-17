"""
agents/marketing_agent.py
Crafts go-to-market strategy, messaging, and launch campaigns.
"""

from __future__ import annotations

from agents.base_agent import AgentResult, BaseAgent


class MarketingAgent(BaseAgent):
    name = "marketing"
    role = "Marketing Lead — positioning, campaigns, GTM"

    system_prompt = """You are a growth-focused marketing lead at a startup.
Your job is to:
- Craft sharp, differentiated brand positioning
- Write the hero headline and sub-headline for the landing page
- Define the go-to-market (GTM) strategy for launch
- Propose 3 acquisition channels with tactics and rationale
- Draft a launch week content plan

Structure your output as:
1. Brand Positioning Statement
2. Landing Page Copy (headline, sub-headline, CTA)
3. GTM Strategy
4. Top 3 Acquisition Channels (with tactics)
5. Launch Week Plan (day-by-day)
Be creative, punchy, and specific (400-500 words)."""

    def run(self, objective: str, context: dict[str, AgentResult]) -> AgentResult:
        """
        Execute the marketing agent task.

        Args:
            objective: The top-level startup goal.
            context:   Results from prior agents in the pipeline.

        Returns:
            AgentResult containing the marketing output.
        """
        self._log.info("marketing.run.start")
        prompt = self._build_prompt(objective, context)
        content = self._call_claude(prompt)
        self._log.info("marketing.run.complete", content_chars=len(content))
        return AgentResult(agent=self.name, content=content)
