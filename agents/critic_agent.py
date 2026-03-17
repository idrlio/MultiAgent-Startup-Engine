"""
agents/critic_agent.py
======================
Critic agent — red-teams all prior outputs, scores confidence, and
optionally signals which agents should be retried in the feedback loop.
"""

from __future__ import annotations

import re
from agents.base_agent import AgentResult, BaseAgent


class CriticAgent(BaseAgent):
    name = "critic"
    role = "Critic — quality control, red-teaming, risk identification, feedback loop"

    system_prompt = """You are a brutally honest startup advisor and red-teamer reviewing the work
of a multi-agent AI team. Your review must be rigorous, specific, and actionable.

Structure your output EXACTLY as follows (use these exact section headers):

## Critical Assumptions
List each major assumption made across all agent outputs. Mark each as VALIDATED, UNVALIDATED, or RISKY.

## Top 5 Risks
Rank the five most dangerous risks that could kill this startup. For each: name, severity (HIGH/MED/LOW), likelihood, and mitigation.

## Strategy Gaps
Identify specific gaps or contradictions between the research, CEO strategy, product spec, engineering plan, and marketing approach.

## Recommended Improvements
For each gap or risk, provide a concrete, actionable improvement. Reference the specific agent whose output needs revision.

## Agents Requiring Revision
List agent names that produced output below acceptable quality (one per line, exactly as named):
REVISE: <agent_name>

## Overall Confidence Score
Provide a single score: SCORE: <number>/10
Then justify the score in 2-3 sentences.
"""

    def run(self, objective: str, context: dict[str, AgentResult]) -> AgentResult:
        """
        Evaluate all prior agent outputs and return a structured critique.

        The critique includes a numeric confidence score and an explicit list
        of agents that should be retried — consumed by the orchestrator's
        feedback loop.

        Args:
            objective: The top-level startup goal.
            context:   Results from all prior agents.

        Returns:
            AgentResult with critique text and structured metadata containing
            ``confidence_score`` (float) and ``agents_to_revise`` (list[str]).
        """
        self._log.info("critic.run.start", agents_reviewed=list(context))
        prompt = self._build_prompt(objective, context)
        content = self._call_claude(prompt)

        # Parse structured fields from the response
        confidence_score = self._parse_score(content)
        agents_to_revise = self._parse_agents_to_revise(content)

        self._log.info(
            "critic.run.complete",
            confidence_score=confidence_score,
            agents_to_revise=agents_to_revise,
        )

        return AgentResult(
            agent=self.name,
            content=content,
            metadata={
                "confidence_score": confidence_score,
                "agents_to_revise": agents_to_revise,
            },
        )

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_score(text: str) -> float:
        """Extract the numeric confidence score from critic output."""
        match = re.search(r"SCORE:\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*10", text, re.IGNORECASE)
        if match:
            try:
                return min(10.0, max(0.0, float(match.group(1))))
            except ValueError:
                pass
        return 5.0   # neutral default if parsing fails

    @staticmethod
    def _parse_agents_to_revise(text: str) -> list[str]:
        """Extract the list of agent names flagged for revision."""
        agents = []
        for match in re.finditer(r"REVISE:\s*(\w+)", text, re.IGNORECASE):
            agents.append(match.group(1).lower().strip())
        return agents
