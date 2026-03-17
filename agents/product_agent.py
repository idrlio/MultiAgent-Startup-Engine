"""
agents/product_agent.py
Defines product specifications, user stories, and MVP scope.
"""

from __future__ import annotations

from agents.base_agent import BaseAgent


class ProductAgent(BaseAgent):
    name = "product"
    role = "Product Manager — specs, roadmap, user stories"

    system_prompt = """You are a sharp product manager at a fast-moving startup.
Your job is to:
- Define the MVP feature set (ruthlessly scoped)
- Write clear user stories in the format: "As a [persona], I want [feature] so that [benefit]"
- Outline a 3-phase product roadmap
- Define acceptance criteria for the top 3 features

Your output should be structured as:
1. MVP Scope (what's IN and what's deliberately OUT)
2. User Stories (top 5-8 stories)
3. Product Roadmap (Phase 1 / 2 / 3)
4. Acceptance Criteria for top 3 features
Keep it concrete and developer-ready (400-600 words).
"""

    def run(self, objective: str, context: dict[str, str]) -> str:
        ctx = self._build_context_block(context)
        prompt = f"""Startup Objective: {objective}

{ctx}

Write the product specification now."""

        self._log.info("product.running")
        result = self._call_claude(prompt)
        self._log.info("product.done")
        return result
