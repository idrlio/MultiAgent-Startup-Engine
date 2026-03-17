"""
agents/engineer_agent.py
Proposes system architecture, tech stack, and scaffolds starter code.
"""

from __future__ import annotations

from agents.base_agent import AgentResult, BaseAgent


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
2. System Architecture (components and how they connect)
3. Core Data Models (name and key fields)
4. Project Structure (folder tree)
5. Technical Risks and Mitigations
Write clean, opinionated recommendations (400-600 words)."""

    def run(self, objective: str, context: dict[str, AgentResult]) -> AgentResult:
        """
        Execute the engineer agent task.

        Args:
            objective: The top-level startup goal.
            context:   Results from prior agents in the pipeline.

        Returns:
            AgentResult containing the engineer output.
        """
        self._log.info("engineer.run.start")
        prompt = self._build_prompt(objective, context)
        content = self._call_claude(prompt)
        self._log.info("engineer.run.complete", content_chars=len(content))
        return AgentResult(agent=self.name, content=content)
